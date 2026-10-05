# AD. FIVE-MINUTE PITCH AND JURY DEFENSE

## 5-Minute Pitch

### 0:00–0:30 — The Problem

“SALESTORM is a flash-sale platform where demand can overwhelm supply in seconds. In our test case, 10,000 customers race for 100 units. The important failure is not a slow page; it is selling 101 units, charging twice, or losing a paid order.”

### 0:30–1:00 — Requirements and Constraints

“Our hard guarantees are: stock never goes negative, reservations never exceed sellable stock, one logical request creates one reservation/payment/order, and confirmed payment is never silently lost. We target 10,000 normal requests per second and design the edge/read path for 500,000, while treating that as a tested capacity goal, not a promise that a hot SQL row can accept 500,000 writes per second.”

### 1:00–2:00 — High-Level Architecture

“CDN and WAF absorb cacheable traffic and abuse; stateless services scale horizontally. Product discovery and cart reads use Redis and read replicas. Inventory and reservation writes go to a PostgreSQL primary. Payment, order, shipment, and notification communicate through Kafka events backed by transactional outboxes. This keeps the user-facing stock decision synchronous and makes downstream work recoverable.”

### 2:00–3:00 — The 10,000 vs 100 Concurrency Problem

“We do not read stock and then decrement it. Each request issues one atomic conditional update: decrement only where available quantity is at least the requested quantity. The database serializes writes to that product row and rechecks the predicate after a lock wait. Exactly one of the final contenders can take the last unit; later updates affect zero rows. We check affected-row count and insert the reservation, idempotency result, and outbox event in the same transaction. Redis never grants stock. A duplicate key returns the original reservation, and expiry can restore stock only when it wins the ACTIVE-to-EXPIRED transition.”

### 3:00–3:45 — Payment and Order Reliability

“We persist a payment intent and stable provider reference before calling the gateway. A timeout is unknown, not failure, so retries query or reuse the same provider idempotency key. On success, payment state and a PaymentSucceeded outbox event commit together. If Order Service is down for 30 seconds, Kafka retains the event; the order consumer retries and uses an inbox and unique reservation/payment constraints. No second charge, no lost event, no duplicate order.”

### 3:45–4:30 — LLD, SOLID, Patterns

“The core dependencies are small ports: inventory repository, payment gateway, order repository, and event publisher. Adapters isolate payment/carrier providers; strategy selects pricing or provider routing; state policies reject invalid transitions; repositories preserve transactional rules. The design follows SRP and DIP while keeping interfaces meaningful. We use outbox/inbox and idempotency because delivery is at least once, not magically exactly once.”

### 4:30–5:00 — Scale, Reliability, AI-Assisted Validation

“At higher traffic, the CDN and waiting room protect the write path, services and Kafka consumers scale independently, and the database is scaled or sharded only with one authoritative owner per product. We ran a small concurrent simulation of 10,000 attempts against 100 units: 100 reservations, zero overselling, zero duplicate charges, and zero duplicate orders. That validates invariants in the model; production still requires database load, failover, and chaos testing.”

## Jury Q&A (30 Questions)

1. **Why this architecture?** It separates read scaling from scarce-stock writes and makes payment/order workflows recoverable while keeping the stock invariant in one transactional authority.
2. **Where exactly is inventory consistency guaranteed?** At the PostgreSQL primary's conditional `UPDATE` and affected-row check, in the same transaction as reservation, counters, idempotency, and outbox.
3. **What if two requests reach inventory simultaneously?** The row update is serialized by the database lock; after waiting, each predicate is evaluated against the current value. Only available units can be decremented.
4. **Why can inventory never become negative?** The update requires `available_quantity >= quantity`; a database `CHECK` constraint adds defense in depth; both paths are tested under concurrency.
5. **Why SQL?** It supplies atomic conditional writes, transactions, unique constraints, and auditable state. NoSQL is viable if it proves equivalent conditional/transactional guarantees and hot-key capacity.
6. **Why Redis?** It accelerates catalog/session/rate-limit reads. It is not a correctness store for stock.
7. **What if Redis goes down?** Inventory remains correct; safe reads fall back with origin protection, while abuse controls may fail closed.
8. **What if the database goes down?** Reservation fails closed with retryable status. No cached stock grant; HA failover fences the old writer before resuming writes.
9. **What if payment succeeds but order creation fails?** Payment success and outbox event are committed first; Kafka retains it; retries/inbox/unique constraints create one order later. Reconciliation finds any gap.
10. **What if the payment response is lost?** Mark outcome unknown and query by merchant reference or await signed webhook. Reuse the provider idempotency key; never issue a fresh charge reference.
11. **What if the same request is sent ten times?** Same customer, operation, key, and payload return one stored response. Different payload with same key is rejected.
12. **How do you prevent duplicate payment?** Unique logical payment per reservation/attempt, stable provider idempotency key, persisted provider reference, webhook dedupe, and reconciliation.
13. **Why sync here and async there?** Reservation must be decided before promising stock; fulfillment/notification can lag and need independent retries.
14. **What is the bottleneck?** The hot inventory row/database write capacity and external payment-provider latency; we use admission control and bounded pools, not unbounded app scaling.
15. **How scale toward 500,000 requests/sec?** CDN for read-heavy traffic, WAF/waiting room, stateless horizontal services, cache/read replicas, Kafka consumers, and controlled reservation admission. Load tests determine capacity.
16. **How handle hot products?** One authoritative row per product, bounded admission, negative-only cache hints, and explicit sold-out responses. Optional escrow quotas must be disjoint and sum to stock.
17. **Why not simply use a queue?** A queue smooths bursts and can impose fairness, but SQL must still enforce stock when dequeued; queue delivery is also duplicated and failure-prone.
18. **Why not pessimistic locking?** The conditional update already takes the necessary row lock for a short statement; explicit locks around broader application work lengthen contention.
19. **What happens when a reservation expires?** A worker conditionally transitions ACTIVE to EXPIRED and restores stock in one transaction. Repeated execution changes zero rows and cannot restore twice.
20. **How guarantee no overselling?** All allocation for a product reaches one authoritative conditional update; no Redis/replica allocation and no multi-writer split-brain.
21. **What consistency model?** Strong consistency for inventory and each service's local transaction; eventual consistency across services/projections through durable events.
22. **Biggest trade-off?** The hot product serializes and the service/event topology costs operational complexity; correctness is prioritized over maximizing raw write throughput.
23. **Why trust the design?** Its invariant is expressed as database predicates/constraints, effects are transactionally grouped, and retries are idempotent; then verify via load, failover, and chaos testing.
24. **What changes for production?** Capacity/load tests, threat modeling, managed HA, key/retention policy, provider contract tests, disaster recovery exercises, compliance review, SLOs, and cost modeling.
25. **Can Kafka guarantee exactly once?** Kafka can provide transactional behavior within Kafka, but not one atomic commit across PostgreSQL, provider, and consumer DB. We use at-least-once plus outbox/inbox and unique business keys.
26. **What if Kafka is unavailable after payment commits?** The outbox event remains in the payment database and publisher retries; payment is not rolled back or lost.
27. **What if the outbox publisher crashes after send but before marking published?** It sends again; consumer inbox/event ID and business uniqueness make the duplicate harmless.
28. **When can stock be released after payment timeout?** Only after provider query/webhook establishes failure/void, or a bounded policy safely voids/refunds and resolves money outcome. Timeout alone is not proof of failure.
29. **How do you keep event order?** Partition by aggregate key (reservation/payment/order as appropriate), include aggregate version, and reject stale/invalid transitions. Kafka ordering is per partition only.
30. **How is fairness handled?** The database guarantees stock safety, not first-click fairness. If fairness matters, use signed admission tokens/waiting-room sequencing ahead of the same final SQL guard.
31. **How do you reconcile inventory?** Compare available/reserved/sold counters with reservation/order ledger in an auditable job; alert on mismatch and apply only deterministic repair.
32. **How does cancellation/refund work after shipment?** Validate current state; cancel fulfillment if possible, otherwise follow return workflow. Refund is a separate idempotent payment operation and never rewrites original charge history.
33. **What if the primary fails after commit but before response?** Retry same idempotency key against the promoted, fenced primary; it returns the committed response or safely creates one if the transaction did not commit.
34. **Why not shard inventory immediately?** One product must have a single consistency owner. Sharding adds routing/failover complexity without changing the per-product serialization requirement; measure first.
35. **How does the simulation prove production readiness?** It does not. It demonstrates model invariants and duplicate handling; production readiness requires real SQL concurrency, broker, gateway sandbox, failover, and chaos tests.
