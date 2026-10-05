# M. FAILURE RECOVERY MATRIX

## Critical Scenario: Payment Success + Order Service Failure

### Scenario
1. Customer reserves product.
2. Payment succeeds at gateway.
3. Payment Service writes PaymentSucceeded to OUTBOX_EVENT (same DB transaction).
4. Order Service is unavailable for 30 seconds.

### What Happens

```
T+0s:   Payment Service commits: payment.status=SUCCEEDED + outbox_event.status=PENDING
T+0s:   Payment Service returns 200 to customer: "Payment successful"
T+1s:   Outbox Worker reads PENDING event, publishes to Kafka topic "payment.succeeded"
T+1s:   Kafka stores message (replication factor=3, durable for 7 days)
T+1s:   Order Service consumer tries to consume → service is DOWN
T+1s:   Kafka consumer group lag increases (message sits in Kafka)
T+30s:  Order Service comes back online
T+30s:  Kafka consumer resumes from last committed offset
T+30s:  Consumes PaymentSucceeded event
T+30s:  Checks: SELECT FROM "order" WHERE payment_id = ? → not found
T+30s:  Creates order successfully
T+30s:  Commits Kafka offset

Result:
  ✓ Customer was NOT charged again
  ✓ Payment was NOT lost
  ✓ Reservation was NOT lost
  ✓ No duplicate order created
  ✓ Order created within 30 seconds of service recovery
```

### Why This Works

The Outbox pattern decouples the payment commit from the Kafka publish.
The payment is durable in PostgreSQL the moment it commits.
Kafka retains the message for 7 days — the Order Service has 7 days to consume it.
The `payment_id` UNIQUE constraint on the order table prevents duplicate orders.

---

## Complete Failure Matrix

### API Gateway Failure

| Step | Action |
|------|--------|
| Detection | Load balancer health check fails (5s interval) |
| Immediate response | Load balancer removes instance from pool |
| Retry | Load balancer routes to healthy instance |
| Circuit breaker | Not applicable (LB handles this) |
| User-visible result | Transparent if other instances healthy; 503 if all down |

### Inventory Service Failure

| Step | Action |
|------|--------|
| Detection | Health check fails; API Gateway gets 503 |
| Immediate response | API Gateway returns 503 to client |
| Retry | Client retries with exponential backoff (3 attempts) |
| Circuit breaker | API Gateway opens circuit after 5 failures |
| Compensation | None needed — no state was changed |
| User-visible result | "Service temporarily unavailable, please try again" |

### Database (PostgreSQL Primary) Failure

| Step | Action |
|------|--------|
| Detection | Connection pool timeout; health check fails |
| Immediate response | All write operations fail with 503 |
| Retry | Services retry with backoff |
| Failover | RDS Multi-AZ promotes replica to primary (~30s) |
| Read operations | Continue on read replicas during failover |
| Compensation | In-flight transactions rolled back by DB |
| User-visible result | ~30s degradation; reads continue; writes fail |

### Redis Failure

| Step | Action |
|------|--------|
| Detection | Connection timeout; Redis health check fails |
| Immediate response | Inventory Service falls back to SQL-only path |
| SQL-only path | `UPDATE inventory ... WHERE available_quantity >= qty` |
| Performance impact | Higher DB load; P99 latency increases |
| Cart Service | Cart reads fail; customer sees empty cart (graceful degradation) |
| Rate limiter | Falls back to in-memory rate limiting (less accurate) |
| Recovery | Redis Cluster promotes replica; counter rebuilt from DB |
| User-visible result | Slower responses; cart may appear empty temporarily |

**Redis failure does NOT cause overselling because SQL is the source of truth.**

### Payment Gateway Failure

| Step | Action |
|------|--------|
| Detection | HTTP 5xx or connection timeout from gateway |
| Immediate response | Payment Service records status=TIMED_OUT |
| Circuit breaker | Opens after 5 failures in 10 seconds |
| While open | All payment requests return 503 immediately |
| Reservation | Remains active (customer can retry when gateway recovers) |
| Reconciliation | Worker queries gateway status for TIMED_OUT payments |
| User-visible result | "Payment service unavailable. Your reservation is held." |

### Payment Timeout (Gateway Responds Late)

| Step | Action |
|------|--------|
| Detection | 30-second timeout exceeded |
| Immediate response | Payment status = TIMED_OUT |
| Do NOT | Release reservation or call gateway again |
| Reconciliation worker | Queries gateway status API after 2 minutes |
| If succeeded | Update to SUCCEEDED, publish PaymentSucceeded |
| If failed | Update to FAILED, release reservation |
| User-visible result | "Payment processing. You'll be notified shortly." |

### Order Service Failure

| Step | Action |
|------|--------|
| Detection | Kafka consumer lag increases; health check fails |
| Immediate response | Kafka retains PaymentSucceeded message |
| Retry | Kafka redelivers on consumer restart |
| Idempotency | payment_id UNIQUE prevents duplicate orders |
| User-visible result | Order creation delayed; customer notified when created |

### Message Broker (Kafka) Failure

| Step | Action |
|------|--------|
| Detection | Producer gets connection error |
| Immediate response | Outbox Worker retries with backoff |
| Durability | Outbox events remain in PostgreSQL (PENDING status) |
| Recovery | Kafka cluster recovers; Outbox Worker publishes pending events |
| Compensation | No data lost — Outbox is the durable buffer |
| User-visible result | Delayed notifications and order creation |

### Notification Service Failure

| Step | Action |
|------|--------|
| Detection | Kafka consumer lag; health check fails |
| Immediate response | Kafka retains notification events |
| Retry | Consumer retries on restart |
| DLQ | After 5 failures, event moved to dead-letter queue |
| User-visible result | Delayed notifications (non-critical path) |

### Shipment Provider Failure

| Step | Action |
|------|--------|
| Detection | HTTP 5xx from provider API |
| Immediate response | Shipment Service retries with exponential backoff |
| Circuit breaker | Opens after 5 failures |
| Queue | Shipment creation request queued for retry |
| User-visible result | Shipment creation delayed; order remains CONFIRMED |

### Network Timeout (General)

| Step | Action |
|------|--------|
| Detection | HTTP client timeout |
| Immediate response | Return error to caller |
| Retry | Caller retries with idempotency key |
| Idempotency | Prevents duplicate operations on retry |
| User-visible result | Depends on operation; generally transparent |

---

## Failure Recovery Summary

| Failure | Data Lost? | Oversell? | Duplicate Charge? | Recovery Time |
|---------|-----------|-----------|-------------------|---------------|
| Redis down | No | No (SQL guards) | No | < 30s |
| DB primary down | No (replica) | No | No | ~30s (failover) |
| Payment Service down | No (Outbox) | No | No | On restart |
| Order Service down | No (Kafka) | No | No | On restart |
| Gateway timeout | No (reconciliation) | No | No | < 2 min |
| Kafka down | No (Outbox in DB) | No | No | On recovery |
| Network partition | No (idempotency) | No | No | On reconnect |
