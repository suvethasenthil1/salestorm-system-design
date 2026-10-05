# G. HIGH-LEVEL ARCHITECTURE

## Service Catalogue

| Service | Responsibility | Owns |
|---------|---------------|------|
| CDN | Static assets, catalogue cache | — |
| WAF | Security filtering, rate limiting | — |
| Load Balancer | L7 routing, health checks | — |
| API Gateway | Auth, routing, rate limit, tracing | — |
| Auth Service | JWT issuance, token validation | CUSTOMER |
| Product Service | Product/category CRUD | PRODUCT, CATEGORY |
| Search Service | Full-text search | Elasticsearch index |
| Cart Service | Cart management | CART, CART_ITEM |
| Sale Service | Flash-sale config | SALE, DEAL |
| Inventory Service | Atomic stock control | INVENTORY |
| Reservation Service | Reservation lifecycle | INVENTORY_RESERVATION |
| Checkout Service | Orchestration, pricing | — (stateless) |
| Payment Service | Payment lifecycle | PAYMENT |
| Order Service | Order lifecycle | ORDER, ORDER_ITEM |
| Shipment Service | Shipment tracking | SHIPMENT |
| Notification Service | Email/SMS/push | NOTIFICATION |

## Service Detail

### CDN
- Serves JS, CSS, images from edge nodes globally.
- Caches: product catalogue (TTL 60s), sale landing pages (TTL 30s).
- Does NOT cache: inventory counts, reservation responses, payment responses.
- Terminates TLS at edge.

### WAF
- Blocks: SQL injection, XSS, CSRF, malformed requests.
- Rate limits: 100 req/sec per IP (configurable), 10 BUY NOW/min per user.
- Bot detection: CAPTCHA challenge on suspicious patterns (rapid-fire requests).
- DDoS mitigation: SYN flood protection, connection rate limiting.

### Load Balancer (L7)
- Routes to API Gateway instances (round-robin).
- Health check every 5 seconds; removes unhealthy instances in 10 seconds.
- Sticky sessions NOT used — all services are stateless.
- SSL termination if not done at CDN.

### API Gateway
- Single entry point for all client requests.
- JWT validation (introspects token; checks Redis blacklist for revoked tokens).
- Rate limiting per user (sliding window, stored in Redis).
- Request routing to downstream services.
- Injects X-Request-ID and X-Trace-ID headers.
- Enforces request timeout (30s default).
- Returns 429 on rate limit, 401 on invalid token, 503 on downstream unavailability.

### Auth Service
- Issues JWT access tokens (15-min TTL, RS256 signed).
- Issues refresh tokens (7-day TTL, stored in DB).
- Token revocation: adds jti to Redis blacklist (TTL = remaining token lifetime).
- Passwords hashed with bcrypt (cost factor 12).
- Scaling: stateless, scale horizontally.
- Failure: API Gateway falls back to local JWT signature verification (no revocation check).

### Product Service
- CRUD for products and categories (admin/seller only for writes).
- Reads served from PostgreSQL read replica.
- Publishes ProductUpdated event to Kafka on any change.
- Scaling: read-heavy, scale read replicas.
- Failure: returns stale CDN-cached data for reads; writes fail with 503.

### Search Service
- Elasticsearch-backed full-text search.
- Synced from Product Service via ProductUpdated Kafka events.
- Does NOT own authoritative product data.
- Failure: returns empty results with degraded-mode flag; does not block purchase flow.

### Cart Service
- Cart stored in Redis (TTL 24h) for performance.
- Persisted to PostgreSQL for logged-in users on checkout.
- Soft availability check only — does NOT reserve stock.
- Scaling: stateless, Redis handles state.
- Failure: cart reads fail gracefully; customer can still proceed to BUY NOW.

### Sale Service
- Manages flash-sale configuration (start/end time, discount percentage).
- Validates whether a product is currently on sale.
- Publishes SaleStarted, SaleEnded events.
- Scaling: read-heavy, cache sale config in Redis (TTL 30s).

### Inventory Service
- THE most critical service in the system.
- Owns the INVENTORY table (source of truth for stock).
- Exposes: check availability, reserve (atomic decrement), release, confirm.
- Uses Redis Lua script as fast-rejection gate.
- Uses SQL atomic UPDATE as durable correctness guarantee.
- Never trusts cache for reservation decisions — SQL is always the final authority.
- Scaling: stateless service; DB is the bottleneck, mitigated by Redis gate.
- Failure: if Redis is down, falls back to SQL-only path (slower but correct).

### Reservation Service
- Manages reservation lifecycle (RESERVED → PAYMENT_PENDING → CONFIRMED → SOLD).
- Coordinates with Inventory Service for atomic stock changes.
- Runs expiry worker (scans expired reservations every 30s).
- Publishes ReservationCreated, ReservationExpired, ReservationReleased events.
- Enforces: one active reservation per customer per product.
- Scaling: stateless; DB handles state.

### Checkout Service
- Thin orchestration layer — owns no persistent state.
- Validates reservation is still active.
- Applies coupons (calls Coupon Service).
- Calculates final price.
- Initiates payment (calls Payment Service).
- Scaling: fully stateless, scale horizontally.
- Failure: returns error; reservation remains active for retry.

### Payment Service
- Manages payment lifecycle.
- Calls external Payment Gateway synchronously.
- Receives webhooks from gateway for async confirmation.
- Idempotency enforced via IDEMPOTENCY_RECORD table.
- Publishes PaymentSucceeded, PaymentFailed events to Kafka.
- Uses Outbox pattern: writes payment record + outbox event in one transaction.
- Scaling: stateless; DB handles state.
- Failure: circuit breaker on gateway; reconciliation worker for unresolved payments.

### Order Service
- Consumes PaymentSucceeded events from Kafka.
- Creates ORDER and ORDER_ITEM records.
- Manages order state machine.
- Publishes OrderCreated, OrderConfirmed, OrderShipped, OrderDelivered events.
- Idempotent consumption: checks for existing order with same payment_id before creating.
- Scaling: stateless; Kafka consumer group scales with partitions.
- Failure: Kafka retry ensures order is eventually created even if service is down 30s.

### Shipment Service
- Consumes OrderConfirmed events.
- Calls external Shipment Provider to create shipment.
- Receives delivery webhooks.
- Publishes ShipmentCreated, ShipmentDelivered events.
- Scaling: stateless.

### Notification Service
- Consumes events from all services.
- Sends email/SMS/push via provider APIs.
- At-least-once delivery; idempotent send (tracks notification_id).
- Failure: retry with backoff; DLQ after 5 failures.
- Scaling: Kafka consumer group, scale with partitions.

---

## HLD Diagram

```mermaid
graph TB
    subgraph Edge["Edge Layer"]
        CDN["CDN"]
        WAF["WAF"]
        LB["Load Balancer"]
    end

    subgraph Gateway["Gateway Layer"]
        APIGW["API Gateway\n(Rate Limit + JWT + Routing)"]
    end

    subgraph Services["Core Services"]
        AUTH["Auth Service"]
        PROD["Product Service"]
        SEARCH["Search Service"]
        CART["Cart Service"]
        SALE["Sale Service"]
        INV["Inventory Service"]
        RES["Reservation Service"]
        CHK["Checkout Service"]
        PAY["Payment Service"]
        ORD["Order Service"]
        SHIP["Shipment Service"]
        NOTIF["Notification Service"]
    end

    subgraph Data["Data Layer"]
        PG_P["PostgreSQL Primary"]
        PG_R["PostgreSQL Replica"]
        REDIS["Redis Cluster"]
        ES["Elasticsearch"]
    end

    subgraph Async["Async Layer"]
        KAFKA["Kafka Cluster"]
        W_EXP["Reservation Expiry Worker"]
        W_REC["Payment Reconciliation Worker"]
        W_OUT["Outbox Publisher Worker"]
    end

    subgraph Ext["External"]
        PAYGW["Payment Gateway"]
        SHIPPROV["Shipment Provider"]
        NOTIFPROV["Notification Provider"]
    end

    CDN --> WAF --> LB --> APIGW

    APIGW --> AUTH
    APIGW --> PROD
    APIGW --> SEARCH
    APIGW --> CART
    APIGW --> SALE
    APIGW --> RES
    APIGW --> CHK
    APIGW --> PAY
    APIGW --> ORD

    RES --> INV
    CHK --> RES
    CHK --> PAY
    PAY --> PAYGW
    PAYGW -->|webhook| PAY

    INV --> PG_P
    INV --> REDIS
    RES --> PG_P
    PAY --> PG_P
    ORD --> PG_P
    PROD --> PG_R
    CART --> REDIS
    SALE --> REDIS

    PAY --> KAFKA
    RES --> KAFKA
    ORD --> KAFKA
    SHIP --> KAFKA

    KAFKA --> ORD
    KAFKA --> SHIP
    KAFKA --> NOTIF

    NOTIF --> NOTIFPROV
    SHIP --> SHIPPROV

    W_EXP --> RES
    W_REC --> PAY
    W_OUT --> KAFKA

    PROD --> ES
    SEARCH --> ES
```

---

## Container Diagram

```mermaid
graph TB
    subgraph K8S["Kubernetes Cluster"]
        subgraph API_Pods["API Service Pods (HPA enabled)"]
            C_AUTH["auth-service\nGo · Port 8001\nReplicas: 2-10"]
            C_PROD["product-service\nGo · Port 8002\nReplicas: 2-8"]
            C_CART["cart-service\nGo · Port 8003\nReplicas: 2-8"]
            C_INV["inventory-service\nGo · Port 8004\nReplicas: 3-20"]
            C_RES["reservation-service\nGo · Port 8005\nReplicas: 3-20"]
            C_CHK["checkout-service\nGo · Port 8006\nReplicas: 2-10"]
            C_PAY["payment-service\nGo · Port 8007\nReplicas: 2-10"]
            C_ORD["order-service\nGo · Port 8008\nReplicas: 2-10"]
            C_SHIP["shipment-service\nGo · Port 8009\nReplicas: 2-6"]
            C_NOTIF["notification-service\nGo · Port 8010\nReplicas: 2-6"]
        end

        subgraph Worker_Pods["Worker Pods"]
            W_EXP["reservation-expiry-worker\nReplicas: 2 (active-passive)"]
            W_REC["payment-reconciliation-worker\nReplicas: 1"]
            W_OUT["outbox-publisher-worker\nReplicas: 2"]
        end
    end

    subgraph Data_Infra["Data Infrastructure"]
        PG["PostgreSQL 15\nPrimary + 2 Replicas\nRDS Multi-AZ"]
        REDIS["Redis 7 Cluster\n3 shards × 2 replicas\nElastiCache"]
        KAFKA["Kafka 3.x\n3 Brokers · RF=3\nMSK"]
        ES["Elasticsearch 8\n3 Nodes"]
    end

    C_INV -->|"SQL writes"| PG
    C_INV -->|"DECR/Lua"| REDIS
    C_RES -->|"SQL writes"| PG
    C_PAY -->|"SQL writes"| PG
    C_ORD -->|"SQL writes"| PG
    C_PROD -->|"SQL reads"| PG
    C_CART -->|"GET/SET/TTL"| REDIS
    C_AUTH -->|"Token blacklist"| REDIS

    C_PAY -->|"produce events"| KAFKA
    C_RES -->|"produce events"| KAFKA
    C_ORD -->|"produce + consume"| KAFKA
    C_NOTIF -->|"consume events"| KAFKA
    C_SHIP -->|"produce + consume"| KAFKA

    C_PROD -->|"index documents"| ES
```

---

## Deployment Diagram

```mermaid
graph TB
    subgraph Region_Primary["AWS us-east-1 (Primary)"]
        subgraph AZ1["Availability Zone 1"]
            K8S_1["K8s Node Pool\nAPI Services"]
            PG_PRIMARY["PostgreSQL Primary\n(RDS)"]
            REDIS_S1["Redis Shard 1\n(ElastiCache)"]
            KAFKA_B1["Kafka Broker 1\n(MSK)"]
        end
        subgraph AZ2["Availability Zone 2"]
            K8S_2["K8s Node Pool\nAPI Services"]
            PG_R1["PostgreSQL Replica 1"]
            REDIS_S2["Redis Shard 2"]
            KAFKA_B2["Kafka Broker 2"]
        end
        subgraph AZ3["Availability Zone 3"]
            K8S_3["K8s Node Pool\nWorkers"]
            PG_R2["PostgreSQL Replica 2"]
            REDIS_S3["Redis Shard 3"]
            KAFKA_B3["Kafka Broker 3"]
        end
    end

    subgraph Region_DR["AWS us-west-2 (DR / Read)"]
        PG_DR["PostgreSQL Standby\n(async replication)"]
        REDIS_DR["Redis Read Replica"]
    end

    subgraph Global_Edge["Global Edge"]
        CF["CloudFront\nEdge Locations\n(200+ PoPs)"]
        WAF_EDGE["AWS WAF\n(attached to CloudFront)"]
    end

    CF --> WAF_EDGE
    WAF_EDGE --> K8S_1
    WAF_EDGE --> K8S_2

    PG_PRIMARY -->|"sync replication"| PG_R1
    PG_PRIMARY -->|"sync replication"| PG_R2
    PG_PRIMARY -->|"async replication"| PG_DR

    KAFKA_B1 --- KAFKA_B2
    KAFKA_B2 --- KAFKA_B3
```
