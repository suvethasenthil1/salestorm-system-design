# AF. HACKATHON DELIVERABLE CHECKLIST

| # | Deliverable | Document(s) | Status |
|---:|---|---|---|
| 1 | Requirements and assumptions | [02_Requirements.md](02_Requirements.md) | Covered |
| 2 | System context diagram | [03_System_Context.md](03_System_Context.md) | Covered |
| 3 | HLD architecture | [04_HLD.md](04_HLD.md), [26_Final_Architecture.md](26_Final_Architecture.md) | Covered |
| 4 | Container diagram | [04_HLD.md](04_HLD.md) | Covered |
| 5 | Component diagram | [04_HLD.md](04_HLD.md), [15_LLD.md](15_LLD.md) | Covered |
| 6 | Deployment diagram | [04_HLD.md](04_HLD.md), [26_Final_Architecture.md](26_Final_Architecture.md) | Covered |
| 7 | Database / ER diagram | [11_Database_Design.md](11_Database_Design.md) | Covered |
| 8 | Class diagrams | [15_LLD.md](15_LLD.md) | Covered |
| 9 | Purchase/reservation sequence | [18_Sequence_Diagrams.md](18_Sequence_Diagrams.md) | Covered |
| 10 | Payment sequence | [18_Sequence_Diagrams.md](18_Sequence_Diagrams.md) | Covered |
| 11 | Order sequence | [18_Sequence_Diagrams.md](18_Sequence_Diagrams.md) | Covered |
| 12 | Order/reservation state diagrams | [06_Reservation_Lifecycle.md](06_Reservation_Lifecycle.md), [09_Order_Management.md](09_Order_Management.md) | Covered |
| 13 | SOLID mapping | [16_SOLID.md](16_SOLID.md) | Covered |
| 14 | Design-pattern mapping | [17_Design_Patterns.md](17_Design_Patterns.md) | Covered |
| 15 | API specification | [12_API_Design.md](12_API_Design.md) | Covered |
| 16 | Scalability and reliability | [10_Failure_Recovery.md](10_Failure_Recovery.md), [19_Scalability.md](19_Scalability.md) | Covered |
| 17 | Security and observability | [21_Security.md](21_Security.md), [22_Observability.md](22_Observability.md) | Covered |
| 18 | Architecture decision records | [23_ADR.md](23_ADR.md) | Covered |
| 19 | AI-assisted prototype/simulation evidence | [25_Simulation.py](25_Simulation.py) | Optional; executed successfully |
| 20 | AI usage note | This document | See below |
| 21 | Final presentation and jury defense | [27_Pitch_and_Defense.md](27_Pitch_and_Defense.md) | Covered |

## AI Usage Note

AI assistance was used to organize the design, enumerate failure cases, draft diagrams and trade-off records, and create a small concurrency/idempotency simulation. The simulation is an illustrative model, not benchmark evidence or proof of production correctness. Human review, domain/provider contract validation, real-database load tests, and failure-injection testing remain required.

## Review Before Submission

- Paste Mermaid diagrams into Mermaid Live Editor or the target renderer and fix renderer-specific syntax issues.
- Verify assumptions, availability objectives, retention, payment provider idempotency semantics, and cloud-specific failover behavior with the selected platform.
- Reconcile document cross-references and API/event names after final edits.
- Present the invariant and failure recovery before implementation details; do not claim global exactly-once delivery or 500,000 authoritative inventory writes/sec.
