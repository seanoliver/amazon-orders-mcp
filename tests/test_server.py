"""Unit tests for server.py's pure-logic helpers.

These tests avoid hitting the real amazon-orders library by patching
`build_session`, `ensure_authenticated`, and the lazily imported
`AmazonTransactions` symbol at its real module path.
"""

import asyncio
import json
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from amazon_orders_mcp import server
from amazon_orders_mcp.client import NonInteractiveAuthRequired
from amazon_orders_mcp.server import (
    TransactionQuery,
    _blocking_match_transactions_by_amount,
    _fetch_transactions_for_range,
    _run_blocking,
)


def _make_txn(completed_date, grand_total, **extra):
    """Build a fake transaction namespace the serializer is happy with."""
    defaults = {
        "payment_method": None,
        "is_refund": False,
        "order_number": None,
        "order_details_link": None,
        "seller": None,
    }
    defaults.update(extra)
    return SimpleNamespace(
        completed_date=completed_date, grand_total=grand_total, **defaults
    )


@pytest.fixture
def mock_amazon_transactions():
    """Patch build_session + ensure_authenticated + AmazonTransactions.

    Yields the mock AmazonTransactions *instance* so tests can set
    .get_transactions.return_value = [...] directly.
    """
    import amazonorders.transactions as at_mod

    mock_class = MagicMock()
    with (
        patch.object(server, "build_session"),
        patch.object(server, "ensure_authenticated"),
        patch.object(at_mod, "AmazonTransactions", mock_class),
    ):
        yield mock_class.return_value


class TestFetchTransactionsForRange:
    def test_days_mode_passes_through(self, mock_amazon_transactions):
        sentinel = [_make_txn(date(2026, 3, 1), -10.0)]
        mock_amazon_transactions.get_transactions.return_value = sentinel
        result = _fetch_transactions_for_range(start_date=None, end_date=None, days=30)
        assert result == sentinel
        mock_amazon_transactions.get_transactions.assert_called_once_with(days=30)

    def test_future_start_returns_empty(self, mock_amazon_transactions):
        result = _fetch_transactions_for_range(
            start_date="2099-01-01", end_date="2099-12-31", days=None
        )
        assert result == []
        mock_amazon_transactions.get_transactions.assert_not_called()

    def test_reversed_range_returns_empty(self, mock_amazon_transactions):
        result = _fetch_transactions_for_range(
            start_date="2026-03-01", end_date="2026-01-01", days=None
        )
        assert result == []
        mock_amazon_transactions.get_transactions.assert_not_called()

    def test_past_range_filters_results(self, mock_amazon_transactions):
        # Library returns a mix of dates; helper should filter to the range.
        mock_amazon_transactions.get_transactions.return_value = [
            _make_txn(date(2026, 1, 15), -5.00),  # in range
            _make_txn(date(2025, 12, 31), -3.00),  # before start
            _make_txn(date(2026, 2, 1), -8.00),  # after end
            _make_txn(date(2026, 1, 20), -7.00),  # in range
            _make_txn(None, -1.00),  # no date → skipped
        ]
        result = _fetch_transactions_for_range(
            start_date="2026-01-01", end_date="2026-01-31", days=None
        )
        assert len(result) == 2
        assert {t.grand_total for t in result} == {-5.00, -7.00}

    def test_no_inputs_defaults_to_365_days(self, mock_amazon_transactions):
        mock_amazon_transactions.get_transactions.return_value = []
        _fetch_transactions_for_range(start_date=None, end_date=None, days=None)
        mock_amazon_transactions.get_transactions.assert_called_once_with(days=365)


class TestMatchTransactionsByAmount:
    def test_empty_queries(self):
        result = _blocking_match_transactions_by_amount([], tolerance=0.01)
        assert json.loads(result) == []

    def test_single_exact_match(self):
        queries = [
            TransactionQuery.model_validate(
                {"date": "2026-03-04", "amount": -35.01, "id": "q1"}
            )
        ]
        fake_txns = [_make_txn(date(2026, 3, 4), -35.01, order_number="ORD-1")]
        with patch.object(
            server, "_fetch_transactions_for_range", return_value=fake_txns
        ):
            result = json.loads(
                _blocking_match_transactions_by_amount(queries, tolerance=0.01)
            )
        assert len(result) == 1
        assert result[0]["match_count"] == 1
        assert result[0]["matches"][0]["order_number"] == "ORD-1"
        assert result[0]["matches"][0]["date_offset_days"] == 0
        # Query should round-trip with the caller's id
        assert result[0]["query"]["id"] == "q1"

    def test_window_days_allows_date_slop(self):
        queries = [
            TransactionQuery.model_validate(
                {"date": "2026-03-04", "amount": -35.01, "window_days": 3}
            )
        ]
        # Transaction 2 days later — should still match
        fake_txns = [_make_txn(date(2026, 3, 6), -35.01, order_number="ORD-2")]
        with patch.object(
            server, "_fetch_transactions_for_range", return_value=fake_txns
        ):
            result = json.loads(
                _blocking_match_transactions_by_amount(queries, tolerance=0.01)
            )
        assert result[0]["match_count"] == 1
        assert result[0]["matches"][0]["date_offset_days"] == 2

    def test_outside_window_no_match(self):
        queries = [
            TransactionQuery.model_validate(
                {"date": "2026-03-04", "amount": -35.01, "window_days": 1}
            )
        ]
        # 5 days away — outside window
        fake_txns = [_make_txn(date(2026, 3, 9), -35.01)]
        with patch.object(
            server, "_fetch_transactions_for_range", return_value=fake_txns
        ):
            result = json.loads(
                _blocking_match_transactions_by_amount(queries, tolerance=0.01)
            )
        assert result[0]["match_count"] == 0

    def test_tolerance_amount_comparison(self):
        queries = [
            TransactionQuery.model_validate({"date": "2026-03-04", "amount": -35.00})
        ]
        # Off by $0.005 — within $0.01 tolerance
        fake_txns = [
            _make_txn(date(2026, 3, 4), -35.005, order_number="ORD-3"),
            _make_txn(date(2026, 3, 4), -36.00),  # off by $1 — no match
        ]
        with patch.object(
            server, "_fetch_transactions_for_range", return_value=fake_txns
        ):
            result = json.loads(
                _blocking_match_transactions_by_amount(queries, tolerance=0.01)
            )
        assert result[0]["match_count"] == 1
        assert result[0]["matches"][0]["order_number"] == "ORD-3"

    def test_extras_round_trip(self):
        queries = [
            TransactionQuery.model_validate(
                {
                    "date": "2026-03-04",
                    "amount": -35.01,
                    "memo": "hardware store",
                    "account": "monarch-checking",
                }
            )
        ]
        with patch.object(server, "_fetch_transactions_for_range", return_value=[]):
            result = json.loads(
                _blocking_match_transactions_by_amount(queries, tolerance=0.01)
            )
        q = result[0]["query"]
        assert q["memo"] == "hardware store"
        assert q["account"] == "monarch-checking"

    def test_grand_total_none_skipped(self):
        queries = [
            TransactionQuery.model_validate({"date": "2026-03-04", "amount": -35.01})
        ]
        fake_txns = [_make_txn(date(2026, 3, 4), None)]  # no grand_total
        with patch.object(
            server, "_fetch_transactions_for_range", return_value=fake_txns
        ):
            result = json.loads(
                _blocking_match_transactions_by_amount(queries, tolerance=0.01)
            )
        assert result[0]["match_count"] == 0


class TestRunBlocking:
    def test_success_passthrough(self):
        def blocking():
            return "hello"

        result = asyncio.run(_run_blocking(blocking, timeout=1.0, tool_name="test"))
        assert result == "hello"

    def test_timeout_returns_error_payload(self):
        def blocking():
            import time

            time.sleep(2)
            return "never"

        result = asyncio.run(
            _run_blocking(blocking, timeout=0.05, tool_name="slow_tool")
        )
        payload = json.loads(result)
        assert "error" in payload
        assert "timed out" in payload["error"]
        assert payload["tool"] == "slow_tool"
        assert payload["timeout_seconds"] == 0.05

    def test_non_interactive_auth_required(self):
        def blocking():
            raise NonInteractiveAuthRequired("need captcha")

        result = asyncio.run(_run_blocking(blocking, timeout=1.0, tool_name="t"))
        payload = json.loads(result)
        assert payload["action_required"] == "run_cookie_capture"
        assert "need captcha" in payload["error"]

    def test_amazon_auth_error(self):
        # Import the real exception type so the isinstance check fires.
        from amazonorders.exception import AmazonOrdersAuthError

        def blocking():
            raise AmazonOrdersAuthError("session expired")

        result = asyncio.run(_run_blocking(blocking, timeout=1.0, tool_name="t"))
        payload = json.loads(result)
        assert payload["action_required"] == "run_cookie_capture"
        assert "cookie_capture.py" in payload["error"]
        assert payload["exception_type"] == "AmazonOrdersAuthError"
        assert payload["underlying_error"] == "session expired"

    def test_generic_exception(self):
        def blocking():
            raise RuntimeError("boom")

        result = asyncio.run(_run_blocking(blocking, timeout=1.0, tool_name="t"))
        payload = json.loads(result)
        assert "boom" in payload["error"]
        assert payload["exception_type"] == "RuntimeError"
