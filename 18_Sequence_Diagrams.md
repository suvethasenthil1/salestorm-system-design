# U. SEQUENCE DIAGRAMS

All mutating requests carry an authenticated principal and an idempotency key. Inventory truth is PostgreSQL; Redis may reject likely-sold-out traffic early but can never authorize a reservation.

## A. Successful Purchase

```mermaid
sequenceDiagram
    autonumber
    actor C as Customer
    participant G as API Gateway
    participant I as Inventory/Reservation
    participant DB as PostgreSQL
    participant K as Kafka
    participant P as Payment Service
    participant PG as Payment Gateway
    participant O as Order Service
    C->>G: POST /buy (key, product, quantity)
    G->>I: Authenticated command + requestId
    I->>DB: BEGIN; claim key; conditional stock update
    DB-->>I: 1 row changed
    I->>DB: Insert reservation + outbox; save response; COMMIT
    I-->>C: 201 reservationId, expiresAt
    C->>G: POST checkout/payment (reservationId, key)
    G->>P: Initiate payment
    P->>DB: Persist PENDING intent + merchant reference
    P->>PG: Charge/authorize with provider idempotency key
    PG-->>P: Success + provider reference
    P->>DB: Mark SUCCEEDED + PaymentSucceeded outbox; COMMIT
    P-->>C: 202 payment status (or result)
    DB-->>K: Outbox publisher sends PaymentSucceeded
    K->>O: At-least-once event
    O->>DB: Inbox claim + unique order insert + outbox; COMMIT
    O-->>K: Commit offset after transaction
    O-->>C: Order status available via GET/push notification
```

## B. Failed Payment

```mermaid
sequenceDiagram
    autonumber
    actor C as Customer
    participant P as Payment Service
    participant PG as Gateway
    participant DB as PostgreSQL
    participant K as Kafka
    participant R as Reservation Service
    C->>P: Initiate payment (same idempotency key on retry)
    P->>PG: Charge using stable provider key
    PG-->>P: Definitive decline
    P->>DB: Mark FAILED + PaymentFailed outbox; COMMIT
    DB-->>K: Publish PaymentFailed
    K->>R: PaymentFailed(reservationId)
    R->>DB: BEGIN; ACTIVE -> RELEASED conditional transition
    R->>DB: Increment available, decrement reserved; outbox; COMMIT
    R-->>K: Ack after commit
    P-->>C: Payment declined; reservation release pending/complete
```

A gateway timeout is not a definitive decline: mark the payment `UNKNOWN`, query or await a webhook, and retain the reservation during bounded reconciliation. Do not charge again or release stock while the money outcome is ambiguous.

## C. Reservation Expiry

```mermaid
sequenceDiagram
    autonumber
    participant W as Expiry Worker
    participant DB as PostgreSQL
    participant K as Kafka
    participant N as Notification Service
    W->>DB: Select due ACTIVE rows (FOR UPDATE SKIP LOCKED, bounded batch)
    W->>DB: Conditional ACTIVE -> EXPIRED; restore stock; outbox; COMMIT
    DB-->>W: Changed rows only
    DB-->>K: ReservationExpired events
    K->>N: Notify affected customer (policy-dependent)
    N-->>K: Ack after durable notification request
```

Two workers may encounter the same due reservation, but only one can change `ACTIVE` to `EXPIRED`; only that transaction restores quantity. Re-running the worker is safe.

## D. Duplicate Buy Request

```mermaid
sequenceDiagram
    autonumber
    actor C as Customer/client retry
    participant G as Gateway
    participant I as Inventory Service
    participant DB as PostgreSQL
    C->>G: POST /reservations, key K, payload H
    G->>I: Request
    I->>DB: Claim (customer, operation, K)
    I->>DB: Conditional decrement + reservation + stored response; COMMIT
    I-->>C: Original reservation response
    C->>G: Retry same key K and payload H
    G->>I: Retry
    I->>DB: Read idempotency record; compare request hash
    DB-->>I: Completed result
    I-->>C: Replay same reservation ID/result; no stock mutation
```

Same key with a different payload returns `409 Idempotency-Key-Reused`. A concurrent duplicate contends on the unique key and then reads the committed result; transaction rollback leaves no partial reservation.

## E. Duplicate Payment Request

```mermaid
sequenceDiagram
    autonumber
    actor C as Customer
    participant P as Payment Service
    participant DB as PostgreSQL
    participant PG as Gateway
    C->>P: POST payment, key K, reservation R
    P->>DB: Create/get unique payment for R and key K
    DB-->>P: Payment PENDING, merchantRef M
    P->>PG: Charge using M as provider idempotency key
    PG-->>P: Success (possibly response lost)
    C->>P: Retry same request/key K
    P->>DB: Lookup same payment and current state
    DB-->>P: Existing payment; no new charge intent
    P-->>C: Existing payment status/reference
```

The application unique key prevents a second logical payment. The provider idempotency key protects the external charge when supported. Ambiguous outcomes are reconciled by `merchantRef`, never by creating a new reference.

## F. Payment Succeeds, Order Service Unavailable for 30 Seconds

```mermaid
sequenceDiagram
    autonumber
    participant PG as Gateway
    participant P as Payment Service
    participant DBP as Payment DB/outbox
    participant K as Kafka
    participant O as Order Service (down 30s)
    participant DBO as Order DB/inbox
    PG-->>P: Verified success
    P->>DBP: SUCCEEDED + PaymentSucceeded outbox; COMMIT
    DBP-->>K: Outbox publishes durable event
    K->>O: Deliver event
    O--xK: Unavailable; no offset commit
    Note over K: Event retained; consumer lag grows and alert fires
    O->>K: Consumer restarts after 30s
    K->>O: Redeliver PaymentSucceeded
    O->>DBO: Inbox + unique order by reservation/payment + outbox; COMMIT
    O-->>K: Commit offset
    Note over P,O: Payment is not invoked again; order creation is idempotent
```

If order creation remains impossible beyond retention or enters a DLQ, reconciliation scans succeeded payments without orders and re-enqueues the same event. A policy deadline may trigger refund and reservation resolution, but not another charge.

## G. Inventory Reaches Zero

```mermaid
sequenceDiagram
    autonumber
    actor C1 as Winning request
    actor C2 as Concurrent request
    participant I as Inventory Service
    participant DB as PostgreSQL primary
    C1->>I: Reserve quantity 1
    C2->>I: Reserve quantity 1
    par Competing atomic updates
        I->>DB: UPDATE ... WHERE available_quantity >= 1
        I->>DB: UPDATE ... WHERE available_quantity >= 1
    end
    Note over DB: Row lock serializes updates; predicate is checked against current row
    DB-->>I: One update may change 1 row; when zero, later update changes 0 rows
    I-->>C1: Reservation created only if row_count=1
    I-->>C2: SOLD_OUT if row_count=0 (or vice versa)
    Note over DB: CHECK available_quantity >= 0 is defense in depth
```

The exact winner among simultaneous callers is not guaranteed to be fair. If fairness is required, add a durable admission token/queue policy before inventory, while retaining the database condition as the final invariant.

## H. Order Through Delivery

```mermaid
sequenceDiagram
    autonumber
    participant K as Kafka
    participant O as Order Service
    participant DB as Order DB
    participant F as Fulfilment/Shipment Service
    participant C as Carrier
    participant N as Notification Service
    K->>O: PaymentSucceeded(reservationId, paymentId)
    O->>DB: Inbox + create/confirm order + outbox; COMMIT
    O-->>K: Ack after commit
    DB-->>K: OrderConfirmed / OrderProcessing
    K->>F: Create fulfilment request (orderId)
    F->>DB: Persist shipment request as PENDING
    F->>C: Create label/consignment with idempotent merchant reference
    C-->>F: Tracking number
    F->>DB: Save shipment + order SHIPPED transition + outbox; COMMIT
    DB-->>K: OrderShipped(trackingNumber)
    K->>N: NotificationRequested
    N-->>K: Durable delivery result / retry
    C-->>F: Signed tracking webhook (in transit/delivered)
    F->>DB: Deduplicate provider event; validate legal order transition; COMMIT
    DB-->>K: OrderOutForDelivery / OrderDelivered
    K->>N: NotificationRequested
```

Carrier label creation is an external side effect and may time out ambiguously. Retry with the same carrier reference or query the carrier before creating another consignment. Tracking webhooks are signature-verified and deduplicated by provider event ID; invalid or out-of-order state transitions are recorded for reconciliation rather than blindly applied.
