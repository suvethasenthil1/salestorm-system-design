# A. EXECUTIVE SUMMARY

SALESTORM is a high-scale flash-sale e-commerce platform engineered to solve the hardest
problem in distributed commerce:

> **10,000 customers simultaneously competing for 100 units of inventory**
> with zero tolerance for overselling, duplicate charges, or lost payments.

## Five Non-Negotiable Guarantees

| # | Guarantee |
|---|-----------|
| 1 | `available_inventory >= 0` at all times — never oversell |
| 2 | No customer is charged twice for the same purchase |
| 3 | No payment is lost even if downstream services fail |
| 4 | Every reservation eventually resolves (confirmed or released) |
| 5 | The system degrades gracefully under extreme load |

## Winning Architecture in One Sentence

> Redis atomic Lua script as the fast-rejection gate → SQL atomic UPDATE as the
> durable correctness guarantee → Kafka for reliable async processing →
> Idempotency keys at every mutation boundary → Outbox pattern for
> payment-to-order reliability.

## Why This Architecture Wins

- **Redis** absorbs 9,900 rejections in < 1ms without touching the database.
- **SQL atomic UPDATE with `available_quantity > 0` guard** is the final, unbreakable
  correctness layer — even if Redis drifts, the database never oversells.
- **Idempotency keys** prevent duplicate reservations, payments, and orders regardless
  of retries or network failures.
- **Outbox pattern** guarantees that a successful payment always produces an order,
  even if the Order Service is down for 30 seconds.
- **Stateless services** allow horizontal scaling to handle 500,000 req/sec.

---

# B. PROBLEM UNDERSTANDING

## The Core Tension

| Speed Demands | Correctness Demands |
|---------------|---------------------|
| Cache reads | Atomic inventory decrements |
| Async processing | Exactly-once payments |
| Horizontal scaling | Consistent order state |
| Sub-100ms responses | Durable audit trail |

## Three Ways a Naive System Fails

### Failure 1 — Overselling (Race Condition)
```
Thread A reads available = 1
Thread B reads available = 1
Thread A decrements → available = 0
Thread B decrements → available = -1  ← OVERSELL
```

### Failure 2 — Lost Payment
```
Payment succeeds at gateway
Response travels back
Order Service crashes
Customer charged, no order exists  ← LOST PAYMENT
```

### Failure 3 — Duplicate Charge
```
Client sends payment request
Network timeout — client retries
Both requests reach Payment Service
Customer charged twice  ← DUPLICATE CHARGE
```

Every architectural decision in this blueprint exists to prevent one of these three
failure modes.

## Business Pipeline

```
Customer
  → Product Discovery
  → Cart
  → Inventory Check (soft)
  → Inventory Reservation (hard, atomic)
  → Checkout
  → Payment
  → Order
  → Fulfilment
  → Shipment
  → Notification
  → Delivery Tracking
```

The critical boundary is between **Inventory Reservation** and **Payment**.
Once a reservation is created, the customer has a time-bounded exclusive claim on
the stock. Everything after that must be reliable enough to honour that claim.
