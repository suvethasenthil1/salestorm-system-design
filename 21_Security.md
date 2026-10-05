# X. SECURITY DESIGN

## Identity, Transport, and Authorization

- Customer authentication uses OIDC/OAuth 2.1 authorization-code flow with PKCE for interactive clients; short-lived access tokens and rotating refresh tokens. Passwords, if locally managed, use a modern adaptive password hash and never reversible encryption.
- Admin/seller identities use MFA, separate privileged roles, and stronger session controls. Authorization is checked server-side for every customer-owned cart, reservation, payment, and order (object-level access control).
- TLS 1.2+ externally and mTLS/service identity internally where supported. Secrets and provider credentials live in a managed secret store with rotation, least-privilege access, and audit logs.
- Gateway validates token issuer/audience/expiry; services still enforce domain authorization. Never trust customer-supplied price, payment status, stock, role, or order ownership.

## API and Data Security

- Validate schemas, types, quantity bounds, sale eligibility, currency, and idempotency-key format before database work. Parameterized SQL and least-privilege DB accounts mitigate injection; migrations use separate credentials.
- Enforce request body limits, timeouts, per-route quotas, and strict CORS/CSRF controls appropriate to client type. Use replay-resistant signed webhooks with timestamp tolerance, signature verification, and unique provider event IDs.
- Use payment-provider tokenization/hosted fields. SALESTORM stores provider tokens and references, not PAN/CVV. Minimize PCI scope; never log card data, access tokens, passwords, or webhook secrets.
- Encrypt databases/backups with managed keys; restrict production access, rotate keys, and test restore procedures. Retain audit records with access controls and defined retention/deletion policy.
- Idempotency keys prevent accidental repeated business actions, not malicious identity spoofing. Bind keys to customer, operation, and request hash; enforce authorization on every replay.

## Flash-Sale Abuse and Bot Controls

1. WAF applies managed exploit rules, IP reputation, bot signals, and volumetric DDoS mitigation.
2. Use account/device/IP velocity limits and per-product attempt quotas; avoid IP-only rules that punish shared networks.
3. Require a short-lived, signed sale admission token after eligibility checks; token is scoped to customer, sale, product, expiry, and nonce. Consume nonce/claim atomically to prevent replay.
4. Use CAPTCHA/challenge selectively based on risk rather than for every customer. Detect account farms and suspicious checkout automation.
5. Use a waiting room/admission controller to smooth bursts and communicate queue position; queue order is not a stock guarantee.
6. Rate-limit login, cart mutation, reservation, payment initiation, and webhook routes separately. Apply stricter limits to expensive operations.
7. Keep reservation and payment limits per customer, including maximum quantity and one active reservation per sale/product when the business rule requires it.

Controls must not claim perfect bot identification. Monitor false positives and provide accessible challenge/appeal behavior.

## Threats and Controls

| Threat | Control |
|---|---|
| Credential stuffing/account takeover | MFA/risk-based auth, credential attack limits, breached-password checks, anomaly alerts |
| Duplicate/replayed requests | Idempotency scope + request hash, sale nonce, timestamped provider webhook signatures |
| IDOR/order data exposure | Object-level authorization and opaque IDs; test cross-customer access |
| SQL injection | Parameterized queries, constrained DB roles, input validation |
| Card-data exposure | Provider tokenization/hosted payment UI, redaction, PCI scope reduction |
| DDoS/bot stock exhaustion | CDN/WAF, waiting room, quotas, admission control, bounded service/DB pools |
| Insider abuse | Least privilege, MFA, just-in-time access, immutable audit trail |

## Incident Readiness

Security alerts cover abnormal login/reservation/payment velocity, signature failures, admin privilege changes, secrets access, and PII export. Have a documented credential-rotation, payment-provider disablement, account/session revocation, and breach-notification process. Security logs carry correlation identifiers, not secrets.
