# F. SYSTEM CONTEXT DIAGRAM

## Actors and External Systems

| Actor / System | Role |
|----------------|------|
| Customer (Web/Mobile) | Browses, reserves, pays, tracks |
| Admin | Manages products, sales, inventory |
| Seller | Lists products, manages deals |
| Payment Gateway | Processes charges and refunds |
| Shipment Provider | Handles physical delivery |
| Notification Provider | Sends email/SMS/push |
| Observability Platform | Receives metrics, logs, traces |
| CDN | Serves static assets, caches catalogue |

## System Context Diagram

```mermaid
graph TB
    subgraph Customers["Customers"]
        WEB["Web Browser\n(React/Next.js)"]
        MOB["Mobile App\n(iOS / Android)"]
    end

    subgraph Admins["Internal Users"]
        ADMIN["Admin Dashboard"]
        SELLER["Seller Portal"]
    end

    subgraph PLATFORM["SALESTORM Platform"]
        CORE["Platform Core\n(All Microservices)"]
    end

    subgraph External["External Services"]
        CDN["CDN\n(CloudFront / Akamai)\nStatic assets + catalogue cache"]
        PG["Payment Gateway\n(Stripe / Razorpay)\nCharge + Refund + Webhook"]
        SP["Shipment Provider\n(FedEx / Delhivery)\nCreate shipment + Tracking webhook"]
        NP["Notification Provider\n(SES / Twilio / FCM)\nEmail + SMS + Push"]
        OBS["Observability\n(Datadog / Grafana)\nMetrics + Logs + Traces"]
    end

    WEB -->|"HTTPS REST\nProduct browse, BUY NOW,\nCheckout, Track order"| CDN
    MOB -->|"HTTPS REST\nSame as Web"| CDN
    CDN -->|"Cache miss → forward"| CORE

    ADMIN -->|"HTTPS Admin API\nManage products, sales, inventory"| CORE
    SELLER -->|"HTTPS Seller API\nList products, set deals"| CORE

    CORE -->|"Charge / Refund API\n(synchronous call)"| PG
    PG -->|"Webhook: payment_succeeded\npayment_failed\n(async callback)"| CORE

    CORE -->|"Create shipment\n(async after order confirmed)"| SP
    SP -->|"Webhook: shipped\nout_for_delivery\ndelivered"| CORE

    CORE -->|"Send email/SMS/push\n(async, fire-and-forget)"| NP

    CORE -->|"Metrics, structured logs,\ndistributed traces"| OBS
```

## Interaction Explanations

### Customer ↔ CDN ↔ Platform
- CDN serves static assets (JS bundles, images) from edge — zero latency.
- CDN caches product catalogue pages with 60-second TTL.
- Dynamic requests (BUY NOW, reserve, pay, order status) always bypass CDN cache
  and reach the platform directly.
- CDN enforces HTTPS; HTTP requests are redirected.

### Admin / Seller ↔ Platform
- Admin and Seller portals bypass CDN and hit the API Gateway directly.
- Elevated JWT roles (ADMIN, SELLER) are required.
- These portals are not on the critical flash-sale path.

### Platform ↔ Payment Gateway
- Payment initiation is a synchronous HTTPS call to the gateway.
- The gateway processes the charge and returns an immediate status.
- For async confirmation (3D Secure, bank redirect), the gateway sends a webhook.
- Webhooks are verified using HMAC signature before processing.

### Platform ↔ Shipment Provider
- Shipment creation is triggered asynchronously after order confirmation.
- The provider sends webhooks for each delivery milestone.
- Webhooks update the SHIPMENT table and trigger customer notifications.

### Platform ↔ Notification Provider
- All notifications are sent asynchronously via Kafka consumer.
- The Notification Service calls the provider's API (SES for email, Twilio for SMS,
  FCM for push).
- Failures are retried with exponential backoff; after 5 retries, moved to DLQ.

### Platform ↔ Observability
- Every service emits structured JSON logs with trace_id, request_id, customer_id.
- Prometheus metrics scraped every 15 seconds.
- OpenTelemetry traces exported to Jaeger/Tempo.
- Alerts fire on: error rate > 1%, P99 latency > 500ms, inventory mismatch detected.
