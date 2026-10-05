# AE. WINNING ARCHITECTURE SUMMARY

Memorize these ten decisions for the jury:

1. **One stock authority:** PostgreSQL primary owns sellable inventory; cache and replicas never authorize stock.
2. **Atomic allocation:** conditional update requires `available_quantity >= requested_quantity`; one affected row means reserved, zero means sold out.
3. **One reservation transaction:** stock counters, reservation, idempotency result, and outbox intent commit or roll back together.
4. **Safe retries:** keys are scoped to customer and operation and bound to a request hash; duplicates replay the original result.
5. **Time-bounded holds:** expiry/release is a conditional state transition plus stock restoration in one transaction; repeated workers are harmless.
6. **No double charge:** stable merchant/provider idempotency reference; ambiguous timeout means reconcile, never blindly charge again.
7. **Recover payment-to-order:** payment success and outbox commit together; Kafka retries; order inbox and unique reservation/payment constraints create one order.
8. **Realistic delivery semantics:** events are at-least-once; outbox/inbox, deduplication, and unique constraints make business effects idempotent, not globally exactly once.
9. **Scale around the hot key:** CDN/WAF/waiting room absorb reads and smooth admission; stateless services/consumers scale horizontally, while a product's stock remains on one authoritative writer.
10. **Prove and observe:** track lock wait, inventory reconciliation, payment unknown age, orphan payments, event lag, and DLQs; load/chaos test before claiming capacity.

**One-sentence defense:** “We protect the scarce resource with one atomic database decision, then make every retry and downstream side effect durable and idempotent.”
