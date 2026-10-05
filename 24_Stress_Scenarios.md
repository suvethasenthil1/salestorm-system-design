# AA. PRACTICAL STRESS SCENARIOS

## Shared Scenario

- Initial sellable stock: 100; 10,000 distinct customers attempt purchase concurrently.
- Payment success rate: 95%, failures: 5% (assumed to apply to reservations that reach payment, and independent for this illustrative calculation).
- Duplicate requests: 2% (retries reuse the same customer/operation idempotency key; they are not extra customers).
- Order Service unavailable for 30 seconds.

Exact counts depend on timing, reservation expiry, and retry policy. Under these assumptions, up to 100 initial reservations can be active at once. If all 100 attempt payment, expected definitive successes are 95 and failures 5. The five released units can be reserved by later eligible attempts, so eventual sales could still reach 100 if time remains and requests are admitted. The 95% figure is not a promise of exactly 95 successes.

## 1. Successful Purchase

A request claims `(customer, reserve, idempotency-key)` and atomically decrements stock by quantity if enough remains. The same transaction inserts the reservation and outbox event. Payment intent is persisted with a stable merchant reference; provider success is recorded once and emits `PaymentSucceeded`. Order consumer inserts one order under unique reservation/payment constraints and confirms it. Payment is never retried with a new reference because an HTTP response is slow.

## 2. Failed Payment

A definitive decline changes payment to `FAILED` and emits `PaymentFailed`. A consumer conditionally transitions the still-active reservation to `RELEASED`, decrements reserved stock and increments available stock in one transaction. Later customers may claim the returned unit. On timeout, outcome is `UNKNOWN`; retain the reservation while querying/webhook reconciliation runs. Expire/release only after policy resolves the payment outcome or performs a safe void/refund.

## 3. Duplicate Buy Request (2%)

Each retry uses the original key and identical payload. The unique idempotency record returns the same reservation response without a second decrement. If a client accidentally uses a new key, a business uniqueness rule such as one active reservation per customer/sale/product may reject it; idempotency cannot identify arbitrary semantic duplicates without a business rule. Same key with different payload receives 409.

## 4. Payment Success + Order Service Down for 30 Seconds

Payment state `SUCCEEDED` and its outbox event are durable before API success is reported. Kafka retains the event; Order consumer does not commit an offset when unavailable. After recovery it processes/redelivers the event, using inbox event ID and unique reservation/payment keys to create exactly one order. Monitor oldest-event age. If retry/DLQ/retention boundaries are exceeded, reconciliation queries succeeded payments missing orders and republishes the same logical event. No new charge occurs; reservation is held/confirmed under defined payment-success policy.

## 5. Inventory Reaches Zero

A successful conditional update changes `available_quantity` from 1 to 0. Concurrent/later updates re-evaluate `available_quantity >= quantity` after row-lock wait and affect zero rows. They receive `SOLD_OUT`; no payment intent is created. A DB `CHECK` constraint prevents negative values even if application logic regresses. Redis display counts do not affect this outcome.

## 6. Database Failure

If the primary is unavailable before commit, reservation transaction rolls back or returns a retryable/unknown result; no cache-only reservation or payment request is allowed. Client retries with the same key. If commit acknowledgment is lost, idempotency lookup on recovery returns the committed result or safely retries if no record exists. HA failover must fence the old primary and meet the stated RPO; asynchronous replication can lose acknowledged writes, so configure synchronous durability for critical transaction data or disclose a non-zero RPO. During failover, return 503 until single-writer authority is established.

## 7. Payment Gateway Failure

Circuit breaker opens after configured failures; no new uncontrolled provider calls. Existing payment intents remain pending/unknown. Show `PAYMENT_PROCESSING` and allow status polling; retry only with the exact same provider idempotency key where safe. Webhooks and scheduled reconciliation resolve late outcomes. Definitive failure releases reservation; ambiguous outcomes retain it only up to a bounded deadline and then require safe void/refund resolution. New purchases can be temporarily disabled if payments cannot be accepted.

## 8. Traffic Increases 50x

At 500,000 requests/sec, CDN absorbs static/cacheable reads; WAF/waiting room and per-route quotas shed abusive or excess work; stateless services scale horizontally; caches protect catalog reads; queues decouple noncritical consumers. Reservation requests are bounded and admitted at a rate the authoritative DB can support. The hot product still serializes on its stock row, so app autoscaling alone cannot raise its write throughput. Shard by product only if each product has one authoritative shard; use disjoint escrow stock quotas only with rigorous sum-of-quota and failover proof. If demand is above capacity, return explicit queue/retry/sold-out outcomes rather than dropping correctness.

## Invariants to Verify in Load/Chaos Tests

- `available_quantity >= 0` always.
- `available + reserved + sold` equals configured sellable stock, adjusted only by explicit audited restock/withdrawal operations.
- Successful active reservations plus sold quantities never exceed stock.
- A customer/key maps to one stored result; a reservation and payment map to at most one order.
- Payment gateway calls for one logical payment reuse the same provider idempotency reference.
- Killing any service between its database commit and broker publication does not lose the event (outbox republishes).
- Duplicate event delivery does not duplicate release, charge, or order effects.
