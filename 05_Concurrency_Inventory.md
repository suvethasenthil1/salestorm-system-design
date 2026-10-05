# H. CONCURRENCY & INVENTORY

## The Core Problem

```
Product X: available_stock = 100
Concurrent BUY NOW requests: 10,000

Naive system:
  Thread 1 reads available = 100 → decrements → 99
  Thread 2 reads available = 100 → decrements → 99  ← WRONG, should be 98
  ...
  Thread 10000 reads available = 100 → decrements → 99
  Final: available = -9,900  ← CATASTROPHIC OVERSELL
```

The system must guarantee: **successful_reservations ≤ available_inventory**

---

## Approach Comparison

### Approach 1 — Optimistic Locking

```sql
-- Step 1: Read current state
SELECT available_quantity, version FROM inventory WHERE product_id = ?;

-- Step 2: Update only if version unchanged
UPDATE inventory
SET available_quantity = available_quantity - 1,
    version = version + 1
WHERE product_id = ?
  AND version = :read_version
  AND available_quantity > 0;
-- Check affected_rows; if 0, retry
```

| Dimension | Assessment |
|-----------|-----------|
| Performance | Good under low contention; catastrophic under high contention |
| Correctness | Correct if retry logic is implemented |
| Complexity | Medium — retry loop required |
| Failure handling | Retry on version mismatch |
| Scalability | Poor for hot products |
| DB load | Very high — 9,900 retries storm the same row |
| Hot-key problem | Severe — all 10,000 requests hammer the same row repeatedly |

**Verdict: Unsuitable for flash-sale hot products. Retry storm destroys throughput.**

---

### Approach 2 — Pessimistic Locking

```sql
BEGIN;
SELECT available_quantity
FROM inventory
WHERE product_id = ?
FOR UPDATE;  -- acquires exclusive row lock

-- If available_quantity > 0:
UPDATE inventory
SET available_quantity = available_quantity - 1
WHERE product_id = ?;
COMMIT;
```

| Dimension | Assessment |
|-----------|-----------|
| Performance | Serializes ALL requests — throughput = 1 / lock_hold_time |
| Correctness | Correct |
| Complexity | Low |
| Failure handling | Lock timeout causes failure |
| Scalability | Very poor — single row lock = global bottleneck |
| DB load | Extreme — 9,999 requests queue on one lock |
| Hot-key problem | Worst case — entire system serializes on one row |

**Verdict: Correct but catastrophically slow. 10,000 requests serialized = ~10s wait.**

---

### Approach 3 — Atomic Database UPDATE

```sql
UPDATE inventory
SET available_quantity = available_quantity - 1,
    reserved_quantity  = reserved_quantity  + 1,
    updated_at         = NOW()
WHERE product_id = ?
  AND available_quantity > 0;
-- Check affected_rows: 1 = success, 0 = exhausted
```

| Dimension | Assessment |
|-----------|-----------|
| Performance | Better than pessimistic — no explicit lock held between read and write |
| Correctness | Correct — DB engine atomically reads+checks+writes in one step |
| Complexity | Low |
| Failure handling | Check affected_rows; 0 means exhausted |
| Scalability | Moderate — still serializes at DB row level under high concurrency |
| DB load | High — 10,000 concurrent UPDATEs on same row |
| Hot-key problem | Moderate — DB row-level lock contention |

**This is correct and simpler than options 1 and 2, but still puts 10,000 concurrent
writes on the database row. At extreme scale, DB becomes the bottleneck.**

---

### Approach 4 — Redis Atomic Operation

```lua
-- Lua script (executes atomically in Redis — single-threaded per key)
local key = KEYS[1]
local qty = tonumber(ARGV[1])
local current = tonumber(redis.call('GET', key))
if current == nil or current < qty then
  return -1  -- insufficient stock
end
local remaining = redis.call('DECRBY', key, qty)
if remaining < 0 then
  redis.call('INCRBY', key, qty)  -- rollback
  return -1
end
return remaining  -- success, returns new count
```

| Dimension | Assessment |
|-----------|-----------|
| Performance | Excellent — Redis handles ~100K ops/sec per shard |
| Correctness | Correct — Lua script is atomic in Redis |
| Complexity | Medium — Redis + DB sync required |
| Failure handling | Redis crash requires fallback to DB |
| Scalability | Excellent for single product; hot-key on Redis shard |
| DB load | Minimal — DB only written after Redis gate passes |
| Hot-key problem | Redis single-threaded per key — still a bottleneck at extreme scale |

**This is the right fast-rejection gate but insufficient alone — Redis is not durable
enough to be the sole source of truth for inventory.**

---

### Approach 5 — Queue-Based Serialization

All 10,000 requests enqueued. Single consumer processes sequentially.

| Dimension | Assessment |
|-----------|-----------|
| Performance | Throughput limited to consumer processing rate |
| Correctness | Perfect — no concurrency at all |
| Complexity | High — async UX, polling required |
| Failure handling | Queue durability handles crashes |
| Scalability | Consumer can scale but ordering becomes complex |
| DB load | Minimal |
| Hot-key problem | Eliminated |

**Verdict: Correct but poor UX (async response). Suitable as fallback at extreme scale.**

---

## SALESTORM's Chosen Approach: Redis Atomic Gate + SQL Durable Commit

### Why This Combination?

- Redis absorbs 9,900 rejections in < 1ms without touching the database.
- Only ~100 requests pass the Redis gate and hit the database.
- SQL atomic UPDATE is the final, unbreakable correctness guarantee.
- Even if Redis counter drifts (crash, network partition), SQL prevents overselling.
- Redis = performance layer. SQL = correctness layer.

### Phase 1 — Redis Gate (fast path, ~1ms)

```lua
-- inventory-service executes this Lua script atomically
local key    = "inv:" .. KEYS[1]   -- e.g. "inv:product-uuid-123"
local qty    = tonumber(ARGV[1])

local current = tonumber(redis.call('GET', key))
if current == nil or current < qty then
  return {-1, "INSUFFICIENT_STOCK"}
end

local remaining = redis.call('DECRBY', key, qty)
if remaining < 0 then
  redis.call('INCRBY', key, qty)   -- atomic rollback
  return {-1, "INSUFFICIENT_STOCK"}
end

return {remaining, "OK"}
```

If Redis returns -1 → immediately return HTTP 409 (stock exhausted). Zero DB load.

### Phase 2 — SQL Durable Commit (authoritative, ~5-10ms)

```sql
BEGIN;

-- Idempotency check first
SELECT reservation_id FROM inventory_reservation
WHERE idempotency_key = :idempotency_key;
-- If found: ROLLBACK, return existing reservation

-- Duplicate reservation check
SELECT reservation_id FROM inventory_reservation
WHERE customer_id = :customer_id
  AND product_id  = :product_id
  AND status IN ('RESERVED', 'PAYMENT_PENDING');
-- If found: ROLLBACK, return 409 DUPLICATE_RESERVATION

-- Atomic inventory decrement (THE CRITICAL GUARD)
UPDATE inventory
SET available_quantity = available_quantity - :qty,
    reserved_quantity  = reserved_quantity  + :qty,
    updated_at         = NOW()
WHERE product_id = :product_id
  AND available_quantity >= :qty;   -- ← UNBREAKABLE GUARD

-- If affected_rows = 0: ROLLBACK, INCR Redis counter back, return 409
-- If affected_rows = 1: continue

-- Create reservation record
INSERT INTO inventory_reservation (
    reservation_id, product_id, customer_id, quantity,
    status, expires_at, idempotency_key, created_at, updated_at
) VALUES (
    gen_random_uuid(), :product_id, :customer_id, :qty,
    'RESERVED',
    NOW() + INTERVAL '10 minutes',
    :idempotency_key,
    NOW(), NOW()
);

COMMIT;
```

### Where Exactly Is Inventory Consistency Guaranteed?

The guarantee lives in this single SQL statement:

```sql
UPDATE inventory
SET available_quantity = available_quantity - :qty,
    reserved_quantity  = reserved_quantity  + :qty
WHERE product_id = :product_id
  AND available_quantity >= :qty;
```

**Why this is unbreakable:**

PostgreSQL executes this as a single atomic operation. The database engine:
1. Acquires a row-level exclusive lock on the inventory row.
2. Reads the current `available_quantity`.
3. Evaluates `available_quantity >= qty`.
4. If true: writes the new values and releases the lock.
5. If false: no write, releases lock, returns affected_rows = 0.

No two concurrent transactions can both see `available_quantity >= 1` and both
decrement if only 1 unit remains. The second transaction either:
- Waits for the first to commit (READ COMMITTED isolation), then sees the updated value.
- Sees the updated value immediately (if first already committed).

In both cases, the second transaction's WHERE clause evaluates to false and
affected_rows = 0.

**The `affected_rows` check is mandatory:**
```
affected_rows == 1  →  reservation succeeded
affected_rows == 0  →  stock exhausted, ROLLBACK, release Redis counter
```

### Race Condition Analysis

| Scenario | Outcome |
|----------|---------|
| 2 requests, Redis counter = 1, both pass Redis gate | Only 1 SQL UPDATE succeeds (affected_rows=1), other gets 0 |
| Redis crashes mid-operation | SQL is source of truth; Redis rebuilt from SQL on restart |
| SQL UPDATE succeeds, INSERT reservation fails | Transaction rolls back, UPDATE undone, Redis counter restored |
| Duplicate request (same idempotency key) | Idempotency check before Redis gate; returns cached response |
| Redis counter = 5, SQL available = 0 (drift) | SQL UPDATE returns affected_rows=0; Redis counter corrected |
| Network partition between app and Redis | Falls back to SQL-only path (slower but correct) |

### Inventory Invariant Proof

At any point in time:
```
available_quantity + reserved_quantity + sold_quantity = total_quantity (constant)
available_quantity >= 0  (enforced by WHERE available_quantity >= qty)
reserved_quantity  >= 0  (enforced by WHERE reserved_quantity >= qty on release)
sold_quantity      >= 0  (only incremented, never decremented)
```

These invariants are maintained by:
1. All inventory mutations happen inside transactions.
2. Every decrement has a corresponding `>= qty` guard.
3. The UNIQUE constraint on `(customer_id, product_id, status IN ACTIVE)` prevents
   duplicate reservations.

### Retry Behaviour

| Failure | Retry? | Reason |
|---------|--------|--------|
| Redis rejection (stock exhausted) | No | Immediate 409 — no point retrying |
| SQL affected_rows=0 (race condition) | No | Stock truly exhausted |
| SQL transaction deadlock | Yes, once | Transient DB contention |
| SQL connection timeout | Yes, once | Transient network issue |
| Idempotency key match | No retry needed | Return original response |

### Hot-Key Mitigation at Extreme Scale (500K req/sec)

For a single product with 100 units and 500,000 concurrent requests:

1. **Redis key sharding**: Use multiple Redis keys for the same product:
   ```
   inv:product-123:shard-0  (25 units)
   inv:product-123:shard-1  (25 units)
   inv:product-123:shard-2  (25 units)
   inv:product-123:shard-3  (25 units)
   ```
   Client hashes customer_id to a shard. Reduces hot-key load by 4×.

2. **Pre-sale queue**: For extreme flash sales, accept requests into a Kafka queue
   and process sequentially. Customers get a "you're in queue" response.

3. **Token bucket**: Issue purchase tokens to first N customers via a lottery
   before the sale starts. Only token holders can attempt reservation.
