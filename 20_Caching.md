# W. CACHING STRATEGY

## Cache Policy

| Data | Cache? | Suggested TTL/policy | Authority and invalidation |
|---|---|---|---|
| Static images, JS/CSS | Yes, CDN | Versioned immutable assets: long TTL | Build/versioned URL; no runtime write invalidation |
| Product descriptions/category | Yes, CDN + Redis | 1–5 min or versioned cache | Product DB; event-driven invalidation plus TTL fallback |
| Search results | Yes, search index/cache | Seconds to minutes | Search index is a discovery projection, not checkout authority |
| Sale schedule and public deal metadata | Yes, Redis/CDN | Short TTL near start/end; versioned | Sale DB; publish invalidation on edits and enforce time window in service |
| Cart | Redis or cart DB cache-aside | Short TTL; durable DB for recovery | Cart service store; per-customer key, no shared CDN cache |
| Session/rate-limit counters | Redis | Policy-specific short TTL | Redis can be transient; auth/rate-limit fallback policy is explicit |
| Inventory availability display | Optional approximate cache | Very short TTL, labeled estimate | PostgreSQL primary is source of truth; stale data may inform UI only |
| Reservation/payment/order status | Cache read-through only if needed | Short TTL with event invalidation | Service database; status reads can be briefly stale if API contract permits |
| Payment credentials/card data | Never cache in application Redis | N/A | Tokenized provider vault / PCI boundary |

## Flash-Sale Stock Handling

A cached count is not a reservation. A displayed `remaining=1` can become zero before the next request, and a stale `remaining=0` can incorrectly hide a newly released unit. Therefore:

- The product page may show an approximate availability label, not a guarantee.
- The authoritative reservation path always runs the SQL conditional update against the primary.
- Redis may hold a conservative sold-out hint set only after authoritative exhaustion. A stale false-positive hint can delay a sale/re-release, so the hint should have a short TTL and an invalidation path; for strongest correctness simply allow requests through to SQL and rely on admission control.
- Never decrement Redis first and later reconcile to SQL as the correctness mechanism. A Redis restart, replication failover, or partial pipeline can lose or duplicate stock changes.
- On reservation release, SQL restores stock and emits an outbox event; cache hint is invalidated asynchronously. This may create a short period where UI says unavailable while a unit is actually available, but cannot oversell.

## Cache Consistency Patterns

- **Catalog:** cache-aside; update database then publish invalidation/version event. TTL bounds damage if invalidation is lost.
- **Sale status:** cache-aside for discovery; API validates authoritative sale start/end and customer eligibility before reservation.
- **Writes:** never treat Redis write-through as a replacement for the SQL transaction. The outbox can invalidate/update derived caches after commit.
- **Stampede controls:** jitter TTL, single-flight/coalescing for safe reads, bounded stale-while-revalidate for catalog only, and request rate limits.
- **Redis failure:** bypass for noncritical reads with origin protection; fail closed for security controls if bypass would permit abuse. Reservation remains correct because it does not depend on Redis.

## Cache Key and Data Hygiene

Namespace keys by environment/tenant/schema version. Never place raw payment secrets or unnecessary personal data in cache. Set maximum value size, TTL, and eviction policy. Monitor hit ratio, evictions, memory fragmentation, hot keys, and origin fallback rate.
