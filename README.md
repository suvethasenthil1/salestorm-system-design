# SALESTORM: Flash-Sale System Design

Design-first architecture blueprint for **SALESTORM – SYSCRAFTERS 2026**. It explores how an e-commerce platform can handle 10,000 concurrent purchase attempts for 100 units without overselling, duplicate reservations, duplicate charges, or losing successful payments when downstream services fail.

This repository is an architecture and hackathon deliverable, not a production-ready commerce application.

## Recommended Architecture

- **PostgreSQL is the inventory authority.** A conditional atomic update reserves stock only when enough quantity remains; the application checks the affected-row count. Reservation state, idempotency result, and outbox event commit in the same transaction.
- **Redis is an optimization, not an inventory authority.** It supports catalog caching and rate limiting; cached stock never authorizes a reservation.
- **Payment retries use stable idempotency references.** Ambiguous gateway timeouts are reconciled instead of blindly charged again.
- **Kafka carries durable asynchronous events.** Transactional outbox/inbox patterns and unique constraints make at-least-once delivery safe for business effects; the design does not claim global exactly-once execution.
- **Reservation expiry, order creation, fulfilment, and notifications are recoverable workflows** with retries, deduplication, and reconciliation.

## Start Here

1. [Blueprint index](00_INDEX.md) for the complete chapter map.
2. [Executive summary](01_Executive_Summary.md) for the problem and guarantees.
3. [Concurrency and inventory](05_Concurrency_Inventory.md) for the stock invariant.
4. [Final architecture](26_Final_Architecture.md) for the recommended end-to-end design.
5. [Pitch and jury defense](27_Pitch_and_Defense.md) for presentation preparation.
6. [Deliverables checklist](29_Deliverables_Checklist.md) for submission coverage and the AI usage note.

## Run the Small Simulation

Requires Python 3.10 or later; no third-party packages are needed.

```powershell
python .\25_Simulation.py
```

The simulation models 10,000 buy attempts against 100 units, including duplicate requests, payment outcomes, expiry, and duplicate order-event delivery. Its lock represents the atomic inventory database operation; it validates model invariants, not production database throughput or failover behavior.

## Scope and Limitations

The documents provide requirements, context/HLD, API and database designs, concurrency and lifecycle handling, reliability trade-offs, diagrams, and jury materials. Mermaid diagrams can be rendered in a compatible Markdown viewer or Mermaid Live Editor. Production use still requires provider-specific validation, capacity/load testing, security review, and failure-injection testing.