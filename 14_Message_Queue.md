# Q. MESSAGE QUEUE DESIGN

## Broker Comparison

| Dimension | Kafka | RabbitMQ | AWS SQS | Redis Streams |
|-----------|-------|----------|---------|---------------|
| Throughput | Very high (millions/sec) | High (100K/sec) | High (managed) | High |
| Message ordering | Per-partition ordering | Per-queue ordering | Best-effort (FIFO queues) | Per-stream |
| Durability | Excellent (replication) | Good | Excellent (managed) | Good (AOF) |
| Replay | Yes (offset-based) | No (consumed = gone) | No | Yes (consumer groups) |
| Consumer scalability | Excellent (consumer groups) | Good | Good | Good |
| Complexity | High | Medium | Low | Low |
| Retention | Configurable (days/weeks) | Until consumed | 14 days max | Configurable |
| Exactly-once | With transactions | No | No | No |
| Schema registry | Yes (Confluent) | No | No | No |

## Decision: Apache Kafka

**Chosen for SALESTORM because:**

1. **Replay capability**: If Order Service is down for 30 seconds, Kafka retains
   the PaymentSucceeded message. When Order Service recovers, it replays from
   the last committed offset. RabbitMQ would have lost the message.

2. **Throughput**: Flash-sale generates 500K events/sec. Kafka handles this
   with horizontal partition scaling. RabbitMQ would require complex clustering.

3. **Ordering**: Partitioning by customer_id ensures all events for a customer
   are processed in order. Critical for: PaymentSucceeded → OrderCreated → OrderShipped.

4. **Durability**: Replication factor 3, min.insync.replicas=2 ensures no message
   loss even if one broker fails.

5. **Consumer groups**: Multiple services (Order, Notification, Analytics) can
   independently consume the same PaymentSucceeded event without coordination.

**Trade-off accepted**: Kafka is operationally complex. Mitigated by using
managed Kafka (AWS MSK) which handles broker management, patching, and scaling.

---

## Kafka Configuration

### Broker Settings

```properties
# Durability
replication.factor=3
min.insync.replicas=2
unclean.leader.election.enable=false

# Performance
num.partitions=12
log.retention.hours=168        # 7 days default
log.retention.bytes=-1         # unlimited

# Producer acks
acks=all                       # wait for all ISR replicas
enable.idempotence=true        # exactly-once producer semantics
max.in.flight.requests.per.connection=5
```

### Producer Settings (per service)

```properties
acks=all
enable.idempotence=true
retries=2147483647
delivery.timeout.ms=120000
linger.ms=5                    # small batching for throughput
batch.size=16384
compression.type=snappy
```

### Consumer Settings (per service)

```properties
enable.auto.commit=false       # manual offset commit after processing
auto.offset.reset=earliest     # on new consumer group, start from beginning
max.poll.records=100           # process 100 messages per poll
session.timeout.ms=30000
heartbeat.interval.ms=10000
isolation.level=read_committed # only read committed messages (for transactions)
```

---

## Topic Design

### payment.succeeded (most critical)

```
Topic: payment.succeeded
Partitions: 24
Replication factor: 3
Retention: 30 days
Partition key: customer_id (hash)
Message format: JSON (Avro in production with schema registry)

Consumer groups:
  - order-service-group       (creates orders)
  - notification-service-group (sends payment confirmation email)
  - analytics-service-group   (records conversion metrics)

Each consumer group maintains its own offset.
Order Service failure does not affect Notification Service consumption.
```

### reservation.expired

```
Topic: reservation.expired
Partitions: 6
Retention: 7 days
Partition key: product_id (to group by product for analytics)

Consumer groups:
  - notification-service-group
  - analytics-service-group
```

---

## Retry Queue Design

```
Primary topic:     payment.succeeded
  ↓ (consumer fails)
Retry topic 1:     payment.succeeded.retry-1  (delay: 30s)
  ↓ (still fails)
Retry topic 2:     payment.succeeded.retry-2  (delay: 5min)
  ↓ (still fails)
Retry topic 3:     payment.succeeded.retry-3  (delay: 30min)
  ↓ (still fails)
Dead-letter topic: payment.succeeded.dlq      (manual review)
```

Retry delay is implemented using a scheduled consumer that reads from the retry
topic and republishes to the primary topic after the delay period.

---

## Message Ordering Guarantee

**Kafka guarantees ordering within a partition, not across partitions.**

For SALESTORM, we need:
- All events for customer C processed in order (ReservationCreated → PaymentSucceeded → OrderCreated)
- Partition key = customer_id ensures all events for customer C go to the same partition
- Same partition = same consumer instance = ordered processing

**What if a partition is rebalanced?**
- Consumer commits offset after each successful processing
- On rebalance, new consumer starts from last committed offset
- Idempotency prevents duplicate processing

---

## Consumer Group Scaling

```
Topic: payment.succeeded (24 partitions)

Order Service consumer group:
  - 24 partitions → up to 24 consumer instances
  - Each instance handles ~1/24 of the load
  - Adding more instances beyond 24 has no effect (idle consumers)
  - Scale partitions to scale consumers

Flash-sale scaling:
  - Pre-scale to 24 consumer instances before sale starts
  - HPA scales based on consumer lag metric
```

---

## Outbox → Kafka Flow

```
Payment Service:
  BEGIN TRANSACTION
    UPDATE payment SET status='SUCCEEDED'
    INSERT INTO outbox_event (event_type='PaymentSucceeded', status='PENDING')
  COMMIT

Outbox Publisher Worker (polls every 100ms):
  SELECT * FROM outbox_event WHERE status='PENDING' FOR UPDATE SKIP LOCKED LIMIT 100
  For each event:
    kafka_producer.send(topic, key, value)
    UPDATE outbox_event SET status='PUBLISHED'
    COMMIT

Kafka:
  Stores message durably (RF=3)
  Consumer groups consume independently
```

**Why not publish directly from Payment Service?**
If Payment Service publishes to Kafka directly (without Outbox), there is a window
between the DB commit and the Kafka publish where a crash loses the event.
The Outbox pattern eliminates this window: the event is durable in PostgreSQL
the moment the transaction commits.
