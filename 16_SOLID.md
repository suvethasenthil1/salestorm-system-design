# S. SOLID PRINCIPLES MAPPING

SOLID is applied at module boundaries; it is not a reason to create an interface for every class.

## Single Responsibility Principle (SRP)

- `InventoryService` coordinates reservation policy; `InventoryRepository` owns SQL persistence and atomic updates; `ReservationExpiryWorker` finds due work and invokes the same release operation. Expiry scheduling is separate from the stock invariant.
- `PaymentService` owns payment transitions; each gateway adapter translates a provider protocol; `PaymentReconciler` resolves ambiguous outcomes. Provider HTTP details do not leak into order logic.
- `OrderService` enforces order transitions; `ShipmentService` communicates with carriers; `NotificationService` delivers messages. A carrier outage must not mutate payment state.
- `PricingPolicy` calculates a quote; `CouponPolicy` validates coupon eligibility. Sale qualification is separate from stock allocation.

## Open/Closed Principle (OCP)

- Add a payment provider by implementing `PaymentGateway` and registering its adapter, without changing the payment state machine.
- Add pricing behavior through a `PricingStrategy` implementation selected by sale configuration. Persist the evaluated quote, amount, currency, and strategy version so later rule changes cannot rewrite history.
- Add notification channels through `NotificationChannel`; the workflow consumes the same logical request and routes to email, SMS, or push.
- Extension is bounded: provider capabilities that cannot satisfy a port must be modeled explicitly rather than hidden behind unsafe defaults.

## Liskov Substitution Principle (LSP)

Every `PaymentGateway` implementation must honor the same contract: stable merchant reference, idempotent retry semantics (or explicitly report that provider idempotency is unavailable), bounded outcomes including `UNKNOWN`, and verifiable webhook events. A provider adapter that reports success for an ambiguous timeout violates the contract. Contract tests run against adapters and provider sandboxes.

Every `InventoryRepository` implementation must preserve atomic conditional allocation and release semantics. A cache-backed implementation that decrements without durable reservation records is not substitutable.

## Interface Segregation Principle (ISP)

Consumers depend on the narrow capabilities they use: `PaymentAuthorizer`, `RefundProcessor`, `WebhookVerifier`; `ShipmentLabelCreator` and `TrackingReader`; `ReservationReader` and `ReservationWriter`. Read-only catalog consumers should not receive administrative write operations. Avoid a single provider interface with unrelated methods every adapter must fake.

## Dependency Inversion Principle (DIP)

High-level policies (`PaymentService`, `OrderService`, `InventoryService`) depend on domain ports (gateway, repository, event publisher), not concrete Kafka/HTTP/PostgreSQL clients. Infrastructure adapters implement the ports. Dependency injection selects implementations at deployment. The chosen inventory design still depends on PostgreSQL transactional guarantees; state and test that operational contract rather than pretending every database behaves identically.

## Concrete Review Test

When adding a provider, ask whether it preserves idempotency, signature verification, amount/currency checks, timeout classification, and reconciliation. When adding a state, update the transition policy, database constraints where applicable, events, and transition tests. SOLID improves change isolation; it does not remove distributed failure modes.
