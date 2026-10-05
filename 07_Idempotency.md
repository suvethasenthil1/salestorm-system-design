# J. IDEMPOTENCY DESIGN

## The Problem

In distributed systems, networks fail. Clients retry. Without idempotency:
- Retry of a reservation creates two reservations → two inventory decrements
- Retry of a payment charges the customer twice
- Retry of order creation creates two orders

**Distributed systems provide at-least-once delivery, not exactly-once execution.
Idempotency is the application-layer mechanism that converts at-least-once into
effectively-once.**

---

## Idempotency Key Design

Every mutating request carries an `Idempotency-Key` header (UUID v4, client-generated).

```
POST /api/v1/reservations
Idempotency-Key: 550e8400-e29b-41d4-a716-446655440000
Content-Type: application/json
```

Rules:
- Client generates a new UUID for each logically distinct operation.
- Client reuses the same UUID when retrying the same operation.
- Server stores the response keyed by (idempotency_key + service + operation).
- TTL: 24 hours (after which the key can be reused for a new operation).

---

## Two-Layer Idempotency Store

### Layer 1 — Redis (fast path, ~1ms)

```
Key:   idempotency:{service}:{operation}:{idempotency_key}
Value: {status_code, response_body, created_at}
TTL:   24 hours
```

On every mutating request:
1. Check Redis for existing response.
2. If found: return cached response immediately (no processing).
3. If not found: process request, store response in Redis + DB.

### Layer 2 — PostgreSQL IDEMPOTENCY_RECORD (durable)

```sql
CREATE TABLE idempotency_record (
    idempotency_key  VARCHAR(255)  NOT NULL,
    service          VARCHAR(50)   NOT NULL,
    operation        VARCHAR(50)   NOT NULL,
    status_code      INT           NOT NULL,
    response_body    JSONB         NOT NULL,
    entity_id        UUID          NULL,   -- reservation_id, payment_id, etc.
    created_at       TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    expires_at       TIMESTAMPTZ   NOT NULL,
    PRIMARY KEY (idempotency_key, service, operation)
);

CREATE INDEX idx_idempotency_expires ON idempotency_record (expires_at);
```

The DB record is written in the same transaction as the business operation.
This ensures atomicity: either both the business record and idempotency record
are committed, or neither is.

---

## Idempotency Per Operation

### Buy / Reservation Request

```
Client sends: POST /reservations with Idempotency-Key: KEY-1

Server flow:
  1. Check Redis: idempotency:reservation:reserve:KEY-1
     → Found: return cached 201 response
     → Not found: continue

  2. Check DB: SELECT FROM idempotency_record WHERE idempotency_key = 'KEY-1'
     → Found: return stored response (Redis was evicted)
     → Not found: continue

  3. Check for existing active reservation:
     SELECT FROM inventory_reservation
     WHERE customer_id = ? AND product_id = ? AND status IN ('RESERVED','PAYMENT_PENDING')
     → Found: return 409 DUPLICATE_RESERVATION

  4. Execute Redis Lua gate + SQL transaction
     → On success: write idempotency record in same transaction
     → Store response in Redis

  5. Return 201 Created
```

### Payment Request

```
Client sends: POST /payments with Idempotency-Key: KEY-2

Server flow:
  1. Check Redis idempotency cache → return if found
  2. Check DB idempotency record → return if found
  3. Check for existing payment with same reservation_id
     → Found: return existing payment (prevent duplicate charge)
  4. Create payment record with status PENDING
  5. Call Payment Gateway with unique payment_reference = UUID
  6. Store result in idempotency record (same transaction as payment update)
  7. Return response
```

**The payment_reference sent to the gateway is the idempotency key for the gateway.
Even if we call the gateway twice with the same payment_reference, the gateway
charges only once.**

### Order Creation (Event-Driven)

```
Order Service consumes PaymentSucceeded event:

  1. Check: SELECT FROM "order" WHERE payment_id = :payment_id
     → Found: skip (idempotent consumption)
     → Not found: create order

  2. The payment_id acts as the natural idempotency key for order creation.
     No separate idempotency key needed for event-driven operations.
```

### Event Consumption Idempotency

```
For every Kafka consumer:

  Before processing:
    Check processed_events table or idempotency store for event_id

  After processing:
    Mark event_id as processed (in same DB transaction as business operation)

  If event_id already processed:
    Acknowledge message and skip (do not reprocess)
```

---

## Duplicate Request Behaviour

| Scenario | Behaviour |
|----------|-----------|
| Exact duplicate (same key, same payload) | Return original response, no reprocessing |
| Same key, different payload | Return 422 IDEMPOTENCY_KEY_CONFLICT |
| Different key, same logical operation | Detected by business-level duplicate check (e.g., active reservation exists) |
| Key expired (> 24h), retry | Treated as new request |

---

## Exactly-Once vs At-Least-Once

**Honest statement:** Distributed systems cannot provide true exactly-once execution
at the infrastructure level. What we can provide is:

- **At-least-once delivery** (Kafka guarantees this with acks=all).
- **Idempotent processing** (application layer converts at-least-once to effectively-once).

The combination gives **effectively-once semantics**:
- A message may be delivered more than once.
- Processing it more than once produces the same result as processing it once.

**Where this holds:**
- Reservation creation: idempotency_key UNIQUE constraint prevents duplicates.
- Payment: payment_reference UNIQUE constraint at gateway prevents duplicate charges.
- Order creation: payment_id UNIQUE constraint prevents duplicate orders.
- Inventory release: `AND status = 'RESERVED'` guard prevents double-release.

**Where this does NOT hold:**
- Notification delivery: a customer may receive the same email twice (acceptable).
- Analytics events: may be counted twice (acceptable, use deduplication in analytics).
