# Z. ARCHITECTURE DECISION RECORDS

These decisions form one coherent baseline for the stated workload. They should be revisited with measured traffic, team capability, and cloud/provider constraints.

## ADR-01: SQL as Inventory and Transaction Authority

- **Context:** Reservation requires atomic stock decrement, reservation row, idempotency result, and outbox intent.
- **Options:** Relational SQL; NoSQL conditional writes; split Redis counter plus database ledger.
- **Chosen:** PostgreSQL-compatible relational primary for inventory/reservation/payment/order local transactions. NoSQL remains viable if it provides conditional atomic updates, transactions for the required rows, and operationally proven hot-key capacity.
- **Why:** Constraints, transactions, conditional update, unique keys, joins/reporting, and mature recovery semantics are easy to demonstrate and audit.
- **Advantages:** Strong per-row consistency, familiar tooling, explicit constraints.
- **Disadvantages:** Hot-row serialization and write scaling ceiling; schema/connection management.
- **Consequences/failure:** Primary unavailable means reservations fail closed (503), not sold from cache. Use HA failover and backups; verify promoted replica durability and fencing before writes.

## ADR-02: Atomic Conditional Update over Read-Then-Write

- **Context:** 10,000 contenders, only 100 units.
- **Options:** Optimistic version compare-and-swap; pessimistic `SELECT FOR UPDATE`; atomic conditional `UPDATE`; Redis Lua; serialized queue.
- **Chosen:** One conditional SQL update as the allocation linearization point, with row count checked and all reservation side effects in the same transaction.
- **Why:** Direct invariant enforcement without a separate distributed lock or per-request queue hop.
- **Advantages:** No negative stock; straightforward proof and audit.
- **Disadvantages:** A single hot product row serializes writers; fairness is unspecified.
- **Consequences/failure:** Lock/DB errors abort the whole transaction; bounded retries only for transient failures using the same idempotency key. Optimistic locking can work but causes retry storms; pessimistic explicit locks can hold locks longer; Redis lacks durable cross-store atomicity; queue serialization smooths but does not replace SQL authority.

## ADR-03: Redis Is Non-Authoritative

- **Context:** Need low-latency discovery and rate limiting without stale stock authorizations.
- **Options:** Redis stock authority; SQL authority; database+Redis dual writes.
- **Chosen:** Redis for catalog/session/rate limits and conservative hints; PostgreSQL primary for reservations.
- **Why:** Avoid dual-write divergence and unsafe stock grants on cache failover.
- **Advantages:** Fast reads and burst absorption.
- **Disadvantages:** Some read staleness; Redis failure can degrade noncritical features.
- **Consequences/failure:** Cache outage bypasses or degrades safe reads; inventory remains correct. A negative sold-out hint may briefly cause false rejection and is short-lived/invalidated.

## ADR-04: Synchronous Local Decision, Asynchronous Cross-Service Workflow

- **Context:** User needs immediate reservation outcome; payment/order/shipping span failures and provider latency.
- **Options:** Synchronous chain; all-async acceptance; sync reservation plus async saga.
- **Chosen:** Synchronous authenticated reservation transaction; payment intent returns processing/accepted; durable async events for order, fulfilment, notification, and tracking.
- **Why:** Stock is reserved before promising payment; downstream outages must not erase a successful charge.
- **Advantages:** Clear user response and independent recovery.
- **Disadvantages:** Eventual consistency and more operational machinery; user may see `PROCESSING`.
- **Consequences/failure:** Outbox/inbox + retries, DLQ, and reconciliation; no distributed transaction.

## ADR-05: Kafka for Durable Integration Events

- **Context:** Independent consumers, replay, high event volume, and payment-to-order recovery.
- **Options:** Kafka; RabbitMQ; managed SQS/SNS; Redis Streams.
- **Chosen:** Managed Kafka for retained event log and multiple consumer groups; a managed queue could be preferable if the real event volume/retention need is small.
- **Why:** Replay and consumer isolation suit payment/order recovery and analytics.
- **Advantages:** High throughput, retention, partition scaling, replay.
- **Disadvantages:** Operational/schema/partition complexity; ordering only per partition; duplicates remain possible.
- **Consequences/failure:** RF=3, `acks=all`, min ISR, outbox, manual consumer commits, idempotent effects, lag alerts, DLQ and replay procedure. RabbitMQ is not inherently lossy; durable queues/acks can fit command-work queues, but replay is less natural.

## ADR-06: At-Least-Once Delivery + Idempotent Effects

- **Context:** DB and broker cannot generally share one atomic commit.
- **Options:** Claim exactly-once end-to-end; at-most-once; at-least-once with deduplication.
- **Chosen:** At-least-once publication/consumption with outbox, inbox/event ID dedupe, business unique constraints, and provider idempotency keys.
- **Why:** Honest and recoverable under crash/retry.
- **Advantages:** No silent event loss under normal configured durability; safe redelivery.
- **Disadvantages:** Deduplication records and retention are required; external provider behavior must be checked.
- **Consequences/failure:** A crash after effect but before offset causes redelivery, which becomes a no-op via unique constraints/inbox.

## ADR-07: Strong Consistency for Stock, Eventual Consistency Elsewhere

- **Context:** Stock cannot be oversold; notification/search/tracking can converge later.
- **Options:** Strong consistency everywhere; eventual consistency everywhere; per-domain consistency.
- **Chosen:** Strong transaction on inventory primary and local service state; eventual consistency via events for projections and workflow.
- **Why:** Correctness budget is focused on scarce stock and money, not read-only projections.
- **Advantages:** Clear invariant with scalable decoupled consumers.
- **Disadvantages:** Stale product/order views and saga states must be represented in API/UI.
- **Consequences/failure:** Query status/reconciliation; do not infer completion from eventual projections.

## ADR-08: Domain-Oriented Services, Not Maximum Microservice Count

- **Context:** Several domains have distinct scaling/security/failure boundaries; hackathon team and operations are constrained.
- **Options:** Modular monolith; all-in microservices; selective services.
- **Chosen:** Domain-oriented services for catalog, cart/sale, inventory/reservation, payment, order/fulfilment, with managed data/messaging; a modular monolith is a valid first implementation if team capacity is small.
- **Why:** Inventory/payment isolation matters, but each service adds network/operations failure modes.
- **Advantages:** Independent scaling and deploy/recovery boundaries.
- **Disadvantages:** Distributed tracing, schema/event evolution, deployment burden, eventual consistency.
- **Consequences/failure:** Keep bounded contexts and team ownership clear; do not split into tiny services prematurely. Start smaller while preserving transactional and API boundaries.

## ADR-09: No Pessimistic Distributed Lock or Queue as Stock Authority

- **Context:** Need serialize scarce writes for a hot product.
- **Options:** Redis lock; DB row lock; per-product queue; atomic SQL predicate.
- **Chosen:** Conditional update (which itself uses the database row lock internally) is the authority. Admission queue is an optional smoothing/fairness layer only.
- **Why:** Fewer lease/fencing failure cases and no extra correctness store.
- **Trade-off:** Hot row throughput and fairness are limited.
- **Failure behavior:** If database cannot confirm the transaction outcome, return an unknown/retryable result keyed idempotently; do not invent success based on cache.
