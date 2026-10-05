# T. DESIGN PATTERNS

Patterns are used where they isolate a real variation or failure boundary. They do not replace database constraints or idempotency.

| Problem | Pattern and location | Classes/components | Benefit | Trade-off |
|---|---|---|---|---|
| Providers have different protocols | **Adapter** at external boundaries | `StripeAdapter`, `AdyenAdapter` implement `PaymentGateway`; carrier adapters implement shipment ports | Provider details stay out of domain services | Mapping and contract tests required; provider capability gaps remain visible |
| Provider choice or pricing rule varies | **Strategy** | `PaymentRoutingStrategy`, `PricingStrategy` selected from trusted configuration | Add a route/rule without branching throughout core logic | Configuration and strategy version must be auditable; strategy explosion is possible |
| Construct the configured adapter | **Factory/registry** | `PaymentProviderRegistry`, `CarrierRegistry` | Centralizes validated provider selection | Avoid runtime reflection and silent fallback to a wrong provider |
| Order/reservation transitions must be legal | **State policy** (explicit transition table; state objects only if complexity grows) | `OrderStatePolicy`, reservation transition function | Invalid transitions are rejected consistently | State machine and persisted enum must evolve together |
| Durable changes notify other services | **Transactional Outbox + event consumers** | Local outbox publisher, Kafka consumers | DB state and event intent commit atomically; consumers remain decoupled | Eventual consistency, duplicate delivery, schema evolution, and operations overhead |
| SQL access and invariants | **Repository** | `InventoryRepository`, `PaymentRepository`, `OrderRepository` | Keeps transaction/query rules in a testable persistence boundary | Can obscure query behavior if over-generalized; SQL-specific locking remains explicit |
| Reduce client orchestration | **Facade/application service** | `CheckoutService` coordinates quote, reservation, and payment initiation | Gives the API a stable use-case boundary | Must not become a cross-domain god service; long workflow remains a saga |
| Provider outage and slow calls | **Circuit breaker + bulkhead + timeout** | Payment/carrier clients | Stops resource exhaustion and fails fast during outage | Breaker state is process-local unless coordinated; thresholds need tuning |

## Extension Examples

- **New payment provider:** implement the gateway port, webhook verification, provider idempotency mapping, status query/refund capabilities, and contract tests; register it in trusted routing configuration. Core payment transitions do not change.
- **New delivery provider:** implement label-creation and tracking interfaces. Shipment workflow persists the provider shipment reference and normalizes carrier status events.
- **New pricing strategy:** implement quote calculation with explicit currency, rounding, and effective-time rules; persist the evaluated quote/strategy version. Inventory reservation still decides stock independently.

## Patterns Deliberately Not Used

- No distributed lock as the stock authority: the relational conditional update already has a durable serialization point.
- No exactly-once execution claim: outbox publishing and Kafka delivery are at-least-once; inbox/unique constraints make effects idempotent.
- No class-per-state initially: a transition table is easier to review for the small finite lifecycle. Refactor only if state-specific behavior becomes substantial.
