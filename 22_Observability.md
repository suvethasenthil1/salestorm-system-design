# Y. OBSERVABILITY

## Metrics

Use RED (rate, errors, duration) for APIs and USE (utilization, saturation, errors) for infrastructure. Tag with bounded-cardinality dimensions such as service, route template, region, result, and provider. Do not put customer IDs or raw product IDs in metric labels.

| Area | Metrics |
|---|---|
| Edge/API | requests/sec, status/error rate, p50/p95/p99 latency, throttles, challenge rate, active requests |
| Reservation | attempts, created/rejected by reason, duplicate replay count, time to reserve, DB lock wait, reservation age, expiry/release rate |
| Inventory | available/reserved/sold totals by controlled audit job, negative quantity constraint violations (must remain zero), reconciliation mismatch count, conditional-update zero-row count |
| Payment | initiated/succeeded/failed/unknown counts, provider latency/timeouts, duplicate-key replay, webhook lag/signature failures, reconciliation age, refund failures |
| Order | order conversion, payment-success-to-order latency, orders per reservation/payment, invalid transition rejects, orphan successful payments |
| Database | transaction latency, pool usage/wait, lock waits/deadlocks, replication lag, WAL, disk, connection errors |
| Kafka | producer errors, broker availability, consumer lag and oldest-event age, retry/DLQ counts, rebalance duration |
| Dependencies | cache hit/miss/eviction/hot-key, carrier latency, notification backlog/failure, circuit state |

## Structured Logs

Every request/event log should include timestamp, severity, service/version, environment, request ID, trace ID, event ID, and relevant reservation/payment/order IDs. Include customer ID only when operationally necessary and pseudonymize it. Record transition, actor type, reason code, and outcome. Redact tokens, secrets, card details, and unnecessary PII. Use sampling for high-volume successful reads while retaining errors and business transitions.

## Distributed Tracing

Propagate W3C trace context through gateway, HTTP/gRPC calls, outbox metadata, Kafka headers, provider calls, and webhook processing. Trace:

`Buy request -> idempotency lookup -> inventory conditional update -> reservation commit -> checkout -> payment intent -> provider -> webhook/reconciliation -> PaymentSucceeded -> order inbox/create -> fulfillment event`.

Asynchronous spans should link to the originating trace rather than keeping a trace open for minutes. Persist correlation IDs in business rows/events for later investigation.

## Critical Alerts and SLOs

- **Inventory invariant:** any negative stock/check-constraint failure or detected mismatch pages immediately; reserve path fails closed if authoritative DB is unavailable.
- **Reservation:** p99 latency above target for 5 minutes; elevated lock wait, pool saturation, or sharp decline in reservation success during an active sale.
- **Payment:** unknown outcomes above threshold, webhook/reconciliation age beyond the reservation safety window, provider timeout/circuit-open rate, or succeeded payments without orders.
- **Order:** oldest unprocessed `PaymentSucceeded` age and consumer lag breach; DLQ increase pages if user-impacting.
- **Platform:** API availability/error budget burn, DB failover/replication lag, Kafka under-replicated partitions, cache outage, notification backlog.

Set numerical paging thresholds only after load tests and baseline SLOs. Example initial targets: public API availability 99.95% monthly; reservation API p99 under 300 ms at the tested 10k-attempt burst, excluding deliberate queue wait; payment/order eventual completion p99 under 60 seconds when dependencies are healthy. These are performance objectives, not guarantees during provider or regional outages.

## Reconciliation Jobs

Periodically compare inventory counters with active reservation/sold ledger totals and payments with provider settlement reports. Reconciliation is read/verify first; automated repair is limited to deterministic, auditable actions. Alert and require review if ledger evidence is ambiguous.
