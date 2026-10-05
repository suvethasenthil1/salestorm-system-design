# C. ASSUMPTIONS

## Traffic Assumptions

| Metric | Value |
|--------|-------|
| Normal load | 10,000 req/sec |
| Flash-sale peak | 500,000 req/sec (burst) |
| Concurrent purchase attempts (one product) | 10,000 |
| Available stock | 100 units |
| Reservation TTL | 10 minutes |
| Payment timeout | 30 seconds |
| Idempotency key TTL | 24 hours |

## Business Assumptions

- A customer may hold at most 1 active reservation per product per sale.
- Reservations not paid within 10 minutes are automatically released.
- Refunds are supported in schema but the refund flow is out of scope for core design.
- Admin and Seller portals exist but are not the primary scaling concern.
- Payment gateway is a third-party provider (Stripe/Razorpay equivalent).

## Infrastructure Assumptions

- Cloud-hosted (AWS equivalent).
- Redis Cluster with AOF persistence enabled.
- PostgreSQL 15 with streaming replication (1 primary, 2 replicas).
- Kafka 3.x cluster with replication factor 3, min.insync.replicas = 2.
- All services containerized (Docker) and orchestrated (Kubernetes).
- Services are stateless — no in-memory session state.

## Guarantee Classification

| Guarantee | Type | Rationale |
|-----------|------|-----------|
| No overselling | **Hard** | Core business rule, enforced at DB layer |
| No negative inventory | **Hard** | SQL constraint + atomic UPDATE guard |
| No duplicate charges | **Hard** | Idempotency key + unique payment reference |
| Order eventually created after payment | **Hard** | Outbox pattern + Kafka retry |
| P99 reservation latency < 200ms | Performance target | Redis gate + optimized SQL |
| P99 payment latency < 2s | Performance target | Gateway-dependent |
| 99.99% availability | Target | Multi-AZ deployment |
| Notification delivery | **Eventual** | At-least-once, non-blocking |

---

# D. FUNCTIONAL REQUIREMENTS

## Authentication
- User registration (email + password, hashed with bcrypt).
- Login returns JWT access token (15-min TTL) + refresh token (7-day TTL).
- Token refresh endpoint.
- Token revocation via Redis blacklist.
- Role-based access: CUSTOMER, ADMIN, SELLER.

## Product Discovery
- Browse product catalogue with pagination and filters.
- Full-text search by name, category, price range.
- View flash-sale products with countdown timer and stock indicator (approximate).
- Product detail page with images, description, price, sale price.

## Cart
- Add, remove, update quantity of items.
- View cart with current prices.
- Cart persists across sessions for logged-in users.
- Cart performs soft availability check (does NOT reserve stock).

## Flash-Sale Purchase
- Customer clicks BUY NOW on a flash-sale product.
- System attempts atomic inventory reservation.
- Reservation is time-bounded (10 minutes).
- Customer must complete payment within reservation window.

## Inventory
- Real-time available quantity tracking.
- Atomic reservation (decrement available, increment reserved).
- Atomic release (increment available, decrement reserved).
- Atomic confirmation (decrement reserved, increment sold).
- Version field for audit and optimistic locking fallback.

## Reservation
- Create reservation with expiry timestamp.
- Query reservation status.
- Release reservation on payment failure or timeout.
- Prevent duplicate reservations: one active reservation per customer per product.

## Checkout
- Validate reservation is still RESERVED or PAYMENT_PENDING.
- Apply coupon/discount codes.
- Calculate final price breakdown.
- Confirm order summary before payment.

## Payment
- Initiate payment with idempotency key.
- Handle success, failure, timeout, and gateway unavailability.
- Receive webhook from payment gateway for async confirmation.
- Retry failed payments within reservation window.
- Prevent duplicate charges via idempotency.

## Order
- Create order on payment confirmation.
- Track order through full lifecycle.
- Cancel order (pre-shipment only).
- Trigger refund on cancellation.

## Shipment
- Create shipment record on order confirmation.
- Integrate with external shipment provider.
- Track shipment status updates via webhook.

## Notifications
- Email/SMS/push on: reservation created, payment success/failure,
  order confirmed, order shipped, order delivered.
- Asynchronous, non-blocking, at-least-once delivery.

## Delivery Tracking
- Customer queries current delivery status.
- Webhook from delivery provider updates status in real time.

## Reservation Expiry
- Background worker scans expired reservations every 30 seconds.
- Releases inventory atomically.
- Idempotent — safe to run multiple times.

## Cancellation / Refund
- Customer cancels order before shipment.
- System initiates refund via payment gateway.
- Inventory released back to available pool.

## Duplicate Request Handling
- Every mutating endpoint requires Idempotency-Key header.
- Duplicate requests return the original response without re-processing.

---

# E. NON-FUNCTIONAL REQUIREMENTS

## Measurable Targets

| Dimension | Target | Notes |
|-----------|--------|-------|
| Throughput | 500,000 req/sec peak | With horizontal scaling |
| P50 reservation latency | < 30ms | Redis gate only |
| P95 reservation latency | < 100ms | Redis + SQL |
| P99 reservation latency | < 200ms | Redis + SQL |
| P99 payment latency | < 2s | Gateway-dependent |
| P99 order creation latency | < 500ms | Async via Kafka |
| Availability | 99.99% | ~52 min downtime/year |
| Inventory consistency | Strong | No eventual consistency for stock |
| Payment consistency | Strong | Exactly-once charge |
| Order consistency | Strong | No lost orders |
| Notification consistency | Eventual | At-least-once acceptable |
| Durability | 99.999% | No data loss on service crash |
| Horizontal scalability | Linear | All services stateless |
| Recovery time (most failures) | < 30s | Circuit breaker + retry |
| Audit trail | Complete | Every state change logged |
| Security | PCI-DSS aligned | For payment data |

## Scalability Targets

| Load Level | Strategy |
|------------|----------|
| 10,000 req/sec (normal) | 3–5 pods per service |
| 500,000 req/sec (flash-sale) | HPA autoscaling, Redis sharding, Kafka partitioning |
| 10,000 concurrent BUY NOW | Redis Lua gate + SQL atomic UPDATE |

## Consistency Model

| Data | Consistency | Reason |
|------|-------------|--------|
| Inventory count | Strong (linearizable) | Oversell prevention |
| Reservation status | Strong | Payment correctness |
| Payment record | Strong | Financial integrity |
| Order status | Strong | Customer trust |
| Product catalogue | Eventual | Read-heavy, staleness acceptable |
| Notifications | Eventual | Non-critical path |
| Search index | Eventual | Elasticsearch sync lag acceptable |
