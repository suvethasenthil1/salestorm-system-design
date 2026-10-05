# O. REST API SPECIFICATION

## Conventions

- Base URL: `https://api.salestorm.com/api/v1`
- Authentication: `Authorization: Bearer {jwt_token}` (except login/register)
- Idempotency: `Idempotency-Key: {uuid}` required on all POST/PUT mutations
- Content-Type: `application/json`
- Errors follow RFC 7807 Problem Details format

## Error Response Format

```json
{
  "type": "https://api.salestorm.com/errors/insufficient-stock",
  "title": "Insufficient Stock",
  "status": 409,
  "detail": "No available units for product prod-123",
  "trace_id": "abc-123-xyz"
}
```

---

## Authentication APIs

### POST /auth/register
Register a new customer.

**Request:**
```json
{
  "email": "user@example.com",
  "password": "SecurePass123!",
  "full_name": "Jane Doe",
  "phone": "+1234567890"
}
```
**Response 201:**
```json
{ "customer_id": "uuid", "email": "user@example.com" }
```
**Errors:** 409 EMAIL_ALREADY_EXISTS, 422 VALIDATION_ERROR

---

### POST /auth/login
Authenticate and receive tokens.

**Request:**
```json
{ "email": "user@example.com", "password": "SecurePass123!" }
```
**Response 200:**
```json
{
  "access_token": "eyJ...",
  "refresh_token": "eyJ...",
  "expires_in": 900
}
```
**Errors:** 401 INVALID_CREDENTIALS, 429 RATE_LIMITED

---

### POST /auth/refresh
Refresh access token.

**Request:** `{ "refresh_token": "eyJ..." }`
**Response 200:** `{ "access_token": "eyJ...", "expires_in": 900 }`

---

## Product APIs

### GET /products
Browse product catalogue.

**Query params:** `category_id`, `page` (default 1), `limit` (default 20), `sort` (price_asc/price_desc/newest)
**Auth:** Optional
**Response 200:**
```json
{
  "items": [
    {
      "product_id": "uuid",
      "name": "Flash Sale Laptop",
      "base_price": 999.99,
      "sale_price": 699.99,
      "available_quantity": 47,
      "is_on_sale": true,
      "sale_ends_at": "2026-01-15T18:00:00Z"
    }
  ],
  "total": 150,
  "page": 1,
  "limit": 20
}
```
**Note:** `available_quantity` is approximate (from Redis cache, TTL 5s). Not used for reservation decisions.

---

### GET /products/{productId}
Get product details.

**Auth:** Optional
**Response 200:**
```json
{
  "product_id": "uuid",
  "name": "Flash Sale Laptop",
  "description": "...",
  "base_price": 999.99,
  "sale_price": 699.99,
  "available_quantity": 47,
  "category": { "category_id": "uuid", "name": "Electronics" },
  "is_on_sale": true,
  "sale_ends_at": "2026-01-15T18:00:00Z"
}
```
**Errors:** 404 PRODUCT_NOT_FOUND

---

## Cart APIs

### POST /cart/items
Add item to cart.

**Auth:** Required
**Idempotency-Key:** Required
**Request:** `{ "product_id": "uuid", "quantity": 1 }`
**Response 201:** `{ "cart_id": "uuid", "item_count": 3 }`
**Errors:** 404 PRODUCT_NOT_FOUND, 422 VALIDATION_ERROR

---

### GET /cart
Get current cart.

**Auth:** Required
**Response 200:**
```json
{
  "cart_id": "uuid",
  "items": [
    { "product_id": "uuid", "name": "...", "quantity": 1, "unit_price": 699.99 }
  ],
  "subtotal": 699.99
}
```

---

### DELETE /cart/items/{productId}
Remove item from cart.

**Auth:** Required
**Response 204:** No content

---

## Reservation APIs

### POST /reservations
**THE MOST CRITICAL ENDPOINT.**
Atomically reserve inventory for a product.

**Auth:** Required
**Idempotency-Key:** Required
**Request:**
```json
{
  "product_id": "uuid",
  "quantity": 1,
  "sale_id": "uuid"
}
```
**Response 201:**
```json
{
  "reservation_id": "uuid",
  "product_id": "uuid",
  "quantity": 1,
  "status": "RESERVED",
  "expires_at": "2026-01-15T18:10:00Z",
  "expires_in_seconds": 600
}
```
**Errors:**
- 409 INSUFFICIENT_STOCK — no units available
- 409 DUPLICATE_RESERVATION — customer already has active reservation
- 404 PRODUCT_NOT_FOUND
- 404 SALE_NOT_ACTIVE
- 429 RATE_LIMITED

**Idempotency:** Same Idempotency-Key returns original 201 response.

---

### GET /reservations/{reservationId}
Get reservation status.

**Auth:** Required (must be reservation owner)
**Response 200:**
```json
{
  "reservation_id": "uuid",
  "status": "RESERVED",
  "expires_at": "2026-01-15T18:10:00Z",
  "expires_in_seconds": 543
}
```
**Errors:** 404 NOT_FOUND, 403 FORBIDDEN

---

## Checkout APIs

### POST /checkout
Validate reservation and calculate final price.

**Auth:** Required
**Idempotency-Key:** Required
**Request:**
```json
{
  "reservation_id": "uuid",
  "coupon_code": "FLASH20",
  "shipping_address": {
    "line1": "123 Main St",
    "city": "New York",
    "state": "NY",
    "zip": "10001",
    "country": "US"
  }
}
```
**Response 200:**
```json
{
  "checkout_id": "uuid",
  "reservation_id": "uuid",
  "subtotal": 699.99,
  "discount": 139.99,
  "total": 560.00,
  "currency": "USD",
  "expires_at": "2026-01-15T18:10:00Z"
}
```
**Errors:** 409 RESERVATION_EXPIRED, 404 RESERVATION_NOT_FOUND, 422 INVALID_COUPON

---

## Payment APIs

### POST /payments
Initiate payment for a reservation.

**Auth:** Required
**Idempotency-Key:** Required
**Request:**
```json
{
  "reservation_id": "uuid",
  "amount": 560.00,
  "currency": "USD",
  "payment_method": {
    "type": "card",
    "token": "tok_visa_4242"
  }
}
```
**Response 201:**
```json
{
  "payment_id": "uuid",
  "status": "PROCESSING",
  "amount": 560.00,
  "currency": "USD"
}
```
**Errors:**
- 409 ALREADY_PAID
- 409 RESERVATION_EXPIRED
- 402 PAYMENT_FAILED (with reason)
- 503 PAYMENT_SERVICE_UNAVAILABLE

---

### GET /payments/{paymentId}
Get payment status.

**Auth:** Required
**Response 200:**
```json
{
  "payment_id": "uuid",
  "status": "SUCCEEDED",
  "amount": 560.00,
  "gateway_txn_id": "ch_3abc123"
}
```

---

### POST /payments/{paymentId}/webhook
Internal endpoint for payment gateway webhooks.

**Auth:** HMAC signature verification (not JWT)
**Request:** Gateway-specific payload
**Response 200:** `{ "received": true }`

---

## Order APIs

### GET /orders
List customer orders.

**Auth:** Required
**Query params:** `status`, `page`, `limit`
**Response 200:** `{ "items": [...], "total": 5 }`

---

### GET /orders/{orderId}
Get order details.

**Auth:** Required (must be order owner)
**Response 200:**
```json
{
  "order_id": "uuid",
  "status": "SHIPPED",
  "total_amount": 560.00,
  "items": [
    { "product_id": "uuid", "name": "...", "quantity": 1, "unit_price": 560.00 }
  ],
  "shipment": {
    "tracking_number": "FX123456789",
    "provider": "FedEx",
    "estimated_delivery": "2026-01-18"
  },
  "created_at": "2026-01-15T17:30:00Z"
}
```
**Errors:** 404 NOT_FOUND, 403 FORBIDDEN

---

### POST /orders/{orderId}/cancel
Cancel an order.

**Auth:** Required
**Idempotency-Key:** Required
**Request:** `{ "reason": "Changed my mind" }`
**Response 200:** `{ "order_id": "uuid", "status": "CANCELLED" }`
**Errors:** 409 CANNOT_CANCEL (order already shipped), 404 NOT_FOUND

---

## Delivery Tracking APIs

### GET /orders/{orderId}/tracking
Get delivery tracking information.

**Auth:** Required
**Response 200:**
```json
{
  "tracking_number": "FX123456789",
  "provider": "FedEx",
  "status": "OUT_FOR_DELIVERY",
  "estimated_delivery": "2026-01-18",
  "events": [
    { "timestamp": "2026-01-17T09:00:00Z", "location": "New York Hub", "description": "Package in transit" }
  ]
}
```

---

## Admin APIs

### POST /admin/sales
Create a flash sale. **Auth:** ADMIN role required.

### PUT /admin/inventory/{productId}
Update inventory. **Auth:** ADMIN/SELLER role required.

### GET /admin/reservations
List all reservations with filters. **Auth:** ADMIN role required.

---

## HTTP Status Code Reference

| Code | Meaning |
|------|---------|
| 200 | Success |
| 201 | Created |
| 204 | No Content |
| 400 | Bad Request (malformed) |
| 401 | Unauthorized (no/invalid token) |
| 403 | Forbidden (insufficient role) |
| 404 | Not Found |
| 409 | Conflict (business rule violation) |
| 422 | Unprocessable Entity (validation error) |
| 429 | Too Many Requests (rate limited) |
| 500 | Internal Server Error |
| 503 | Service Unavailable |
