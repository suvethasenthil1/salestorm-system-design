# V. SCALABILITY STRATEGY

## 10,000 Simultaneous Purchase Attempts

Treat this as a burst/concurrency requirement, not a claim that one database must process 10,000 successful writes at once. The system admits requests quickly, rejects invalid or obviously closed sales at the edge, and lets the inventory primary serialize the final stock decision for the product. With stock 100, at most 100 unit reservations can succeed (fewer if payment failures/expiry timing are excluded from the definition of reservation).

1. CDN serves static assets and cacheable catalog/product/sale-page responses.
2. WAF and gateway apply bot controls, per-account/device/IP limits, payload limits, and sale-window checks.
3. Stateless API and sale services scale horizontally; sticky sessions are unnecessary.
4. Redis serves catalog and sale metadata and may provide a short-lived *negative hint* that the product is sold out. It cannot authorize a positive reservation.
5. Reservation requests carry stable idempotency keys and enter the reservation service. A bounded concurrency limit and database connection pool prevent unbounded queued threads.
6. The PostgreSQL primary executes a conditional update on the inventory row. That row is the linearization point for this product. For the 100th unit, one transaction succeeds; later requests see zero affected rows.
7. Successful reservations and associated outbox events commit together. Kafka distributes downstream work; payment and order consumers scale independently.
8. Backpressure returns `429`/`503` with `Retry-After` for overload. Sold-out is a terminal business response, not retried automatically.

Capacity must be load-tested against realistic request mixes, lock-wait distributions, and connection limits. A single hot inventory row is intentionally serialized. It is correct but has a throughput ceiling; the 100-unit result set is small, so high write throughput does not create more sellable stock.

## 500,000 Requests/Second Design Point

This is a system-wide peak assumption, not an assertion that the inventory database accepts 500,000 writes/sec or that the sample 10,000 attempts all hit one product at that rate. Establish a traffic budget by class: cached reads, authenticated writes, purchase intents, webhooks, and background events. Run load tests to size each tier and use admission control for the hot write path.

- **CDN:** serve immutable assets and cacheable product pages; use stale-while-revalidate where business-safe. Purge/version product changes. Do not cache personalized cart/payment data as shared content.
- **WAF/gateway:** global and per-identity quotas, signed sale tokens, bot challenges, request coalescing for safe reads, and overload shedding. Protect reservation capacity as a separate quota.
- **Load balancing/stateless services:** multi-zone deployment, autoscale on CPU plus request concurrency/latency, pre-scale before scheduled sales, warm connection pools, and enforce request deadlines.
- **Redis:** clustered cache for catalog/session/rate-limit hints with TTLs; avoid a single unbounded hot key. Shard/cache replicas help reads, not authoritative inventory decisions.
- **SQL:** primary plus read replicas for catalog/order reads that tolerate lag. Inventory writes remain on the authoritative primary. Partition large append-heavy tables (events, idempotency, audit) by time; shard transaction data only when measured write/storage limits require it. If sharding, route a product to exactly one authoritative shard so conditional update remains local.
- **Queue:** Kafka partitions by aggregate key for consumer scale and ordering; scale partitions before events. Queue lag is monitored and producers are backpressured when downstream cannot keep up.
- **Backpressure:** bounded in-flight requests, short DB pool queues, admission tokens, per-customer limits, and `Retry-After`. Never buffer unlimited purchase requests in memory.
- **Hot product:** keep one authoritative counter/row; cache only a negative sold-out hint; if needed, use an admission queue/token bucket to smooth arrival. Do not split 100 units into independently writable Redis/DB shards unless stock is preallocated as disjoint escrow quotas whose sum cannot exceed 100 and whose failover semantics are proven.
- **Autoscaling:** scale stateless tiers and consumers from CPU, p95/p99, concurrency, and lag; database scaling is planned separately because adding app replicas does not increase a hot-row serialization ceiling.

## Likely Bottlenecks and Controls

| Bottleneck | Signal | Control |
|---|---|---|
| Hot inventory row / lock queue | lock wait, update latency, DB pool saturation | Early admission/rate limit, bounded pool, short transaction, pre-sale load test; maintain one correctness authority |
| DB connection exhaustion | active/queued connections, timeouts | pooling/proxy, strict per-service pool caps, backpressure |
| Gateway/provider latency | timeout and circuit-open rate | deadlines, circuit breaker, bulkhead, async webhook/reconciliation |
| Kafka consumer lag | lag age and DLQ rate | pre-provision partitions, independent groups, autoscale consumers, pause non-critical consumers |
| Cache stampede | origin QPS spikes | request coalescing, jittered TTLs, stale-safe catalog response |
| Noisy bots | challenge/block rates, identity concentration | WAF rules, behavioral signals, account/device quotas, queue-based admission |

## Scaling and Correctness Boundary

Strong consistency is limited to each service's authoritative transaction. Catalog, analytics, notifications, and shipment views may be eventually consistent. A replica/cache never participates in the inventory decision. At a shard boundary, all units for one product are owned by one shard, or explicitly partitioned into non-overlapping escrow quotas. Cross-shard reservation is avoided.
