# P. EVENT-DRIVEN ARCHITECTURE

## Synchronous vs Asynchronous Decision

| Operation | Sync/Async | Reason |
|-----------|-----------|--------|
| Inventory reservation | Sync | Customer waits for confirmation; must be immediate |
| Payment initiation | Sync | Customer waits for payment result |
| Order creation | Async | Triggered by PaymentSucceeded event; customer already has payment confirmation |
| Shipment creation | Async | Non-critical path; customer doesn't wait |
| Notifications | Async | Non-critical; failure doesn't affect purchase |
| Search index update | Async | Eventual consistency acceptable |
| Reservation expiry | Async | Background worker |
| Delivery status update | Async | Webhook-driven |

**Rule:** If the customer is waiting for the response, it must be synchronous.
If the customer has already received a response, subsequent processing can be async.

---

## Event Catalogue

### ReservationCreated

```json
{
  "event_id": "uuid",
  "event_type": "ReservationCreated",
  "version": "1.0",
  "timestamp": "2026-01-15T17:30:00Z",
  "payload": {
    "reservation_id": "uuid",
    "product_id": "uuid",
    "customer_id": "uuid",
    "quantity": 1,
    "expires_at": "2026-01-15T17:40:00Z",
    "sale_id": "uuid"
  }
}
```
- Producer: Reservation Service
- Consumers: Notification Service
- Topic: `reservation.created`
- Purpose: Trigger "Reservation confirmed" notification
- Retry: 3 attempts, exponential backoff
- DLQ: After 3 failures → `reservation.created.dlq`

---

### ReservationExpired

```json
{
  "event_type": "ReservationExpired",
  "payload": {
    "reservation_id": "uuid",
    "product_id": "uuid",
    "customer_id": "uuid",
    "quantity": 1
  }
}
```
- Producer: Reservation Expiry Worker
- Consumers: Notification Service, Analytics Service
- Topic: `reservation.expired`
- Purpose: Notify customer, update analytics

---

### ReservationReleased

```json
{
  "event_type": "ReservationReleased",
  "payload": {
    "reservation_id": "uuid",
    "product_id": "uuid",
    "customer_id": "uuid",
    "quantity": 1,
    "reason": "PAYMENT_FAILED"
  }
}
```
- Producer: Payment Service (on payment failure)
- Consumers: Notification Service
- Topic: `reservation.released`

---

### PaymentInitiated

```json
{
  "event_type": "PaymentInitiated",
  "payload": {
    "payment_id": "uuid",
    "reservation_id": "uuid",
    "customer_id": "uuid",
    "amount": 560.00,
    "currency": "USD"
  }
}
```
- Producer: Payment Service
- Consumers: Analytics Service
- Topic: `payment.initiated`

---

### PaymentSucceeded

```json
{
  "event_type": "PaymentSucceeded",
  "payload": {
    "payment_id": "uuid",
    "reservation_id": "uuid",
    "customer_id": "uuid",
    "amount": 560.00,
    "currency": "USD",
    "gateway_txn_id": "ch_3abc123",
    "items": [
      { "product_id": "uuid", "quantity": 1, "unit_price": 560.00 }
    ],
    "shipping_address": { ... }
  }
}
```
- Producer: Payment Service (via Outbox Worker)
- Consumers: **Order Service** (critical), Notification Service, Analytics
- Topic: `payment.succeeded`
- Partitioned by: customer_id (ensures ordering per customer)
- Retry: Kafka consumer retries on failure
- DLQ: After 5 failures → `payment.succeeded.dlq` (manual review required)
- Idempotency: Order Service checks `payment_id` before creating order

---

### PaymentFailed

```json
{
  "event_type": "PaymentFailed",
  "payload": {
    "payment_id": "uuid",
    "reservation_id": "uuid",
    "customer_id": "uuid",
    "reason": "insufficient_funds"
  }
}
```
- Producer: Payment Service
- Consumers: Notification Service, Analytics
- Topic: `payment.failed`

---

### OrderCreated

```json
{
  "event_type": "OrderCreated",
  "payload": {
    "order_id": "uuid",
    "customer_id": "uuid",
    "payment_id": "uuid",
    "total_amount": 560.00,
    "items": [ ... ]
  }
}
```
- Producer: Order Service
- Consumers: Notification Service, Fulfilment Service, Analytics
- Topic: `order.created`

---

### OrderConfirmed

```json
{
  "event_type": "OrderConfirmed",
  "payload": {
    "order_id": "uuid",
    "customer_id": "uuid",
    "items": [ ... ],
    "shipping_address": { ... }
  }
}
```
- Producer: Order Service
- Consumers: **Shipment Service** (critical), Notification Service
- Topic: `order.confirmed`

---

### OrderShipped

```json
{
  "event_type": "OrderShipped",
  "payload": {
    "order_id": "uuid",
    "customer_id": "uuid",
    "tracking_number": "FX123456789",
    "provider": "FedEx",
    "estimated_delivery": "2026-01-18"
  }
}
```
- Producer: Shipment Service
- Consumers: Order Service (update status), Notification Service
- Topic: `order.shipped`

---

### OrderDelivered

```json
{
  "event_type": "OrderDelivered",
  "payload": {
    "order_id": "uuid",
    "customer_id": "uuid",
    "delivered_at": "2026-01-18T14:30:00Z"
  }
}
```
- Producer: Shipment Service (from delivery webhook)
- Consumers: Order Service, Notification Service, Analytics
- Topic: `order.delivered`

---

### NotificationRequested

```json
{
  "event_type": "NotificationRequested",
  "payload": {
    "customer_id": "uuid",
    "channel": "EMAIL",
    "template": "payment_succeeded",
    "data": { "order_id": "uuid", "amount": 560.00 }
  }
}
```
- Producer: Any service
- Consumers: Notification Service
- Topic: `notification.requested`

---

## Kafka Topic Configuration

| Topic | Partitions | Retention | Key |
|-------|-----------|-----------|-----|
| reservation.created | 12 | 7 days | customer_id |
| reservation.expired | 6 | 7 days | product_id |
| payment.succeeded | 24 | 30 days | customer_id |
| payment.failed | 12 | 7 days | customer_id |
| order.created | 24 | 30 days | customer_id |
| order.confirmed | 12 | 30 days | order_id |
| order.shipped | 12 | 30 days | order_id |
| order.delivered | 12 | 30 days | order_id |
| notification.requested | 12 | 3 days | customer_id |

**Why partition by customer_id?**
Ensures all events for a given customer are processed in order by the same
consumer instance. Prevents race conditions like "OrderShipped processed before
OrderCreated" for the same customer.

## Dead-Letter Queue Strategy

```
Primary topic: payment.succeeded
  → Consumer fails 5 times
  → Message moved to: payment.succeeded.dlq

DLQ consumer:
  → Sends alert to on-call engineer
  → Stores in DLQ table for manual review
  → Engineer can replay or discard
```

**DLQ messages are never automatically retried without human review for
payment.succeeded — the risk of duplicate order creation is too high.**
