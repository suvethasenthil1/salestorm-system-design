"""Small architecture simulation, not a database or gateway benchmark.

A process lock stands in for one atomic conditional SQL update on the inventory
row. The simulation demonstrates invariants and idempotency under concurrent
calls; it does not model distributed failover, SQL isolation, or real latency.
"""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import random
import threading


@dataclass
class Reservation:
    reservation_id: str
    customer_id: str
    status: str
    expires_at: int


class FlashSaleSimulation:
    def __init__(self, stock: int = 100) -> None:
        self.initial_stock = stock
        self.available = stock
        self.reserved = 0
        self.sold = 0
        self.lock = threading.Lock()
        self.idempotency_results: dict[tuple[str, str], dict[str, object]] = {}
        self.reservations: dict[str, Reservation] = {}
        self.payment_results: dict[str, dict[str, object]] = {}
        self.gateway_charges: dict[str, int] = {}
        self.orders_by_payment: dict[str, str] = {}
        self.processed_order_events: set[str] = set()
        self.next_reservation = 1
        self.duplicate_buy_attempts = 0
        self.unique_sold_out = 0
        self.overselling_count = 0

    def _check_invariants(self) -> None:
        if self.available < 0 or self.reserved < 0 or self.sold < 0:
            self.overselling_count += 1
        if self.available + self.reserved + self.sold != self.initial_stock:
            self.overselling_count += 1

    def reserve(self, customer_id: str, key: str) -> dict[str, object]:
        idempotency_scope = (customer_id, key)
        with self.lock:
            previous = self.idempotency_results.get(idempotency_scope)
            if previous is not None:
                self.duplicate_buy_attempts += 1
                return {**previous, "duplicate": True}

            if self.available < 1:
                result: dict[str, object] = {
                    "reservation_id": None,
                    "status": "SOLD_OUT",
                    "duplicate": False,
                }
                self.unique_sold_out += 1
            else:
                reservation_id = f"res-{self.next_reservation:05d}"
                self.next_reservation += 1
                self.available -= 1
                self.reserved += 1
                self.reservations[reservation_id] = Reservation(
                    reservation_id=reservation_id,
                    customer_id=customer_id,
                    status="ACTIVE",
                    expires_at=10,
                )
                result = {
                    "reservation_id": reservation_id,
                    "status": "RESERVED",
                    "duplicate": False,
                }
            self.idempotency_results[idempotency_scope] = result
            self._check_invariants()
            return result

    def expire_due(self, now: int) -> int:
        released = 0
        with self.lock:
            for reservation in self.reservations.values():
                if reservation.status == "ACTIVE" and reservation.expires_at <= now:
                    reservation.status = "EXPIRED"
                    self.reserved -= 1
                    self.available += 1
                    released += 1
            self._check_invariants()
        return released

    def pay(self, reservation_id: str, succeeds: bool) -> dict[str, object]:
        payment_key = f"payment:{reservation_id}"
        with self.lock:
            previous = self.payment_results.get(payment_key)
            if previous is not None:
                return {**previous, "duplicate": True}

            reservation = self.reservations[reservation_id]
            if reservation.status != "ACTIVE":
                result: dict[str, object] = {
                    "status": "NOT_PAYABLE",
                    "payment_id": payment_key,
                    "duplicate": False,
                }
                self.payment_results[payment_key] = result
                return result

            self.gateway_charges[payment_key] = 1
            if succeeds:
                reservation.status = "SOLD"
                self.reserved -= 1
                self.sold += 1
                result = {
                    "status": "SUCCEEDED",
                    "payment_id": payment_key,
                    "duplicate": False,
                }
            else:
                reservation.status = "PAYMENT_FAILED"
                self.reserved -= 1
                self.available += 1
                result = {
                    "status": "FAILED",
                    "payment_id": payment_key,
                    "duplicate": False,
                }
            self.payment_results[payment_key] = result
            self._check_invariants()
            return result

    def create_order(self, payment_id: str, event_id: str) -> str | None:
        with self.lock:
            if event_id in self.processed_order_events:
                return self.orders_by_payment.get(payment_id)
            self.processed_order_events.add(event_id)
            if self.payment_results.get(payment_id, {}).get("status") != "SUCCEEDED":
                return None
            existing_order = self.orders_by_payment.get(payment_id)
            if existing_order is not None:
                return existing_order
            order_id = f"order-{len(self.orders_by_payment) + 1:05d}"
            self.orders_by_payment[payment_id] = order_id
            return order_id


def run_simulation() -> dict[str, int]:
    stock = 100
    total_requests = 10_000
    duplicate_requests = 200  # 2% of attempts are retries with an identical key.
    unique_customers = total_requests - duplicate_requests
    simulation = FlashSaleSimulation(stock=stock)

    requests = [
        (f"customer-{customer_number:05d}", f"buy-{customer_number:05d}")
        for customer_number in range(unique_customers)
    ]
    requests.extend(requests[:duplicate_requests])
    random.Random(2026).shuffle(requests)

    with ThreadPoolExecutor(max_workers=256) as executor:
        reservation_responses = list(
            executor.map(lambda request: simulation.reserve(*request), requests)
        )

    active_ids = sorted(
        reservation_id
        for reservation_id, reservation in simulation.reservations.items()
        if reservation.status == "ACTIVE"
    )

    # Expire 10 active holds, then run the worker again to prove idempotent release.
    expiry_candidates = active_ids[:10]
    with simulation.lock:
        for reservation_id in expiry_candidates:
            simulation.reservations[reservation_id].expires_at = 1
    expired_reservations = simulation.expire_due(now=2)
    second_expiry_pass = simulation.expire_due(now=2)

    payable_ids = [
        reservation_id
        for reservation_id in active_ids
        if simulation.reservations[reservation_id].status == "ACTIVE"
    ]
    failure_count = round(len(payable_ids) * 0.05)
    failed_ids = set(payable_ids[:failure_count])
    payment_results = {
        reservation_id: simulation.pay(
            reservation_id,
            succeeds=reservation_id not in failed_ids,
        )
        for reservation_id in payable_ids
    }

    # A retry returns the stored payment result and does not call the gateway again.
    duplicate_payment_attempts = 0
    if payable_ids:
        retry_id = payable_ids[0]
        retry_result = simulation.pay(retry_id, succeeds=retry_id not in failed_ids)
        duplicate_payment_attempts = int(bool(retry_result["duplicate"]))

    # Redeliver one successful order event; inbox + unique payment key prevent a second order.
    duplicate_order_events = 0
    duplicate_order_ids = 0
    for reservation_id, result in payment_results.items():
        if result["status"] != "SUCCEEDED":
            continue
        payment_id = str(result["payment_id"])
        event_id = f"payment-succeeded:{payment_id}"
        first_order = simulation.create_order(payment_id, event_id)
        second_order = simulation.create_order(payment_id, event_id)
        duplicate_order_events += int(second_order == first_order)
        duplicate_order_ids += int(
            len([key for key in simulation.orders_by_payment if key == payment_id]) > 1
        )

    successful_payments = sum(
        result["status"] == "SUCCEEDED" for result in payment_results.values()
    )
    failed_payments = sum(
        result["status"] == "FAILED" for result in payment_results.values()
    )
    unique_successful_reservations = len(simulation.reservations)
    duplicate_successful_charges = sum(
        max(0, charge_count - 1) for charge_count in simulation.gateway_charges.values()
    )
    successful_reservation_responses = sum(
        response["status"] == "RESERVED" for response in reservation_responses
    )

    metrics = {
        "total_buy_requests": total_requests,
        "unique_buy_keys": unique_customers,
        "duplicate_buy_attempts": simulation.duplicate_buy_attempts,
        "successful_reservation_responses_including_replays": successful_reservation_responses,
        "unique_reservations_created": unique_successful_reservations,
        "unique_sold_out_keys": simulation.unique_sold_out,
        "expired_reservations": expired_reservations,
        "second_expiry_pass_releases": second_expiry_pass,
        "successful_payments": successful_payments,
        "failed_payments": failed_payments,
        "duplicate_payment_attempts": duplicate_payment_attempts,
        "duplicate_successful_charges": duplicate_successful_charges,
        "orders_created": len(simulation.orders_by_payment),
        "duplicate_order_event_redeliveries": duplicate_order_events,
        "duplicate_order_ids": duplicate_order_ids,
        "final_available_stock": simulation.available,
        "final_reserved_stock": simulation.reserved,
        "final_sold_stock": simulation.sold,
        "overselling_count": simulation.overselling_count,
    }

    assert metrics["unique_reservations_created"] <= stock
    assert metrics["final_available_stock"] >= 0
    assert metrics["final_reserved_stock"] >= 0
    assert metrics["final_sold_stock"] <= stock
    assert metrics["overselling_count"] == 0
    assert metrics["duplicate_successful_charges"] == 0
    assert metrics["duplicate_order_ids"] == 0
    assert metrics["second_expiry_pass_releases"] == 0
    return metrics


if __name__ == "__main__":
    print("SALESTORM flash-sale architecture simulation (not a production benchmark)")
    for metric, value in run_simulation().items():
        print(f"{metric}: {value}")
