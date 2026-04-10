"""Amazon Orders MCP Server — main server implementation.

Exposes Amazon.com personal order history and payment transactions as MCP tools
by wrapping the `amazon-orders` Python library.

All tools that perform network I/O are `async def` and dispatch their blocking
work to a worker thread via `asyncio.to_thread()`. Each tool is additionally
wrapped in `asyncio.wait_for()` with a wall-clock timeout, so a single stuck
Amazon request can never freeze the MCP server's event loop.
"""

import asyncio
import json
import logging
from datetime import date, timedelta
from typing import Any, Callable, Dict, List, Optional, cast

from amazonorders.exception import AmazonOrdersAuthError
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from amazon_orders_mcp.client import (
    NonInteractiveAuthRequired,
    build_session,
    ensure_authenticated,
)
from amazon_orders_mcp.secure_session import cookie_jar_exists, load_credentials
from amazon_orders_mcp.serialize import (
    serialize_order,
    serialize_orders,
    serialize_transaction,
    serialize_transactions,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

mcp = FastMCP("Amazon Orders MCP Server")

# Wall-clock timeouts per tool (seconds). These are an upper bound — actual
# requests are also capped at DEFAULT_HTTP_TIMEOUT (see client.py). These
# hard timeouts ensure the MCP event loop stays responsive even if something
# goes wrong at a lower layer.
TIMEOUT_SINGLE_CALL = 60.0  # one Amazon page load
TIMEOUT_PAGED_CALL = 300.0  # multi-page fetches (order history, transactions)


def _json(data: Any) -> str:
    """JSON-serialize a payload for MCP return values."""
    return json.dumps(data, indent=2, default=str)


def _error(message: str, **extra: Any) -> str:
    payload: Dict[str, Any] = {"error": message}
    payload.update(extra)
    return _json(payload)


async def _run_blocking(
    fn: Callable[..., Any],
    *args: Any,
    timeout: float,
    tool_name: str,
    **kwargs: Any,
) -> str:
    """Run a blocking function on a worker thread with a wall-clock timeout.

    The blocking function is dispatched via `asyncio.to_thread()` so it does
    not freeze the MCP server event loop. `asyncio.wait_for` enforces a hard
    upper bound — if the thread doesn't complete in time, we return an error
    JSON payload (the thread may continue running in the background, but it
    will eventually unblock when the HTTP timeout in client.py fires).
    """
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(fn, *args, **kwargs),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        logger.warning(f"{tool_name} timed out after {timeout}s")
        return _error(
            f"{tool_name} timed out after {timeout} seconds. Amazon may be "
            "rate-limiting or a connection is stuck. Wait a bit and try again.",
            tool=tool_name,
            timeout_seconds=timeout,
        )
    except NonInteractiveAuthRequired as e:
        return _error(str(e), action_required="run_cookie_capture")
    except AmazonOrdersAuthError as e:
        # This covers both AmazonOrdersAuthError (WAF challenge / bad session)
        # and its subclass AmazonOrdersAuthRedirectError (Amazon redirected
        # us to the sign-in page). In either case, the cookies are stale.
        logger.warning(f"{tool_name} hit auth error: {e}")
        return _error(
            "Amazon session has expired. Re-run `uv run python cookie_capture.py` "
            "in the amazon-orders-mcp repo to capture fresh cookies, then retry.",
            action_required="run_cookie_capture",
            underlying_error=str(e),
            exception_type=type(e).__name__,
            tool=tool_name,
        )
    except Exception as e:
        logger.exception(f"{tool_name} failed")
        return _error(f"{tool_name} failed: {e}", exception_type=type(e).__name__)


# ---------------------------------------------------------------------------
# Auth / status tools
# ---------------------------------------------------------------------------


@mcp.tool()
def setup_authentication() -> str:
    """Get instructions for setting up Amazon authentication."""
    return """🛒 Amazon Orders MCP — One-Time Setup

Amazon blocks the Python `requests` library's sign-in flow with a JavaScript
WAF challenge, so this server authenticates by capturing cookies from a real
Chromium browser session instead.

1️⃣  Open Terminal in the server directory and run:
    uv run python cookie_capture.py

2️⃣  A Chromium window will open to the Amazon sign-in page.
    Enter your email, password, and any 2FA code as usual.

3️⃣  The script auto-detects when you're signed in, extracts the cookies,
    and writes them to ~/.amazon-orders-mcp/cookies.json.

4️⃣  After that, use these tools from Claude:
    • get_order_history - List orders (by year or time filter)
    • get_order - Full details for a single order
    • get_transactions - Amazon payments/transactions feed
    • match_transactions_by_amount - Cross-reference bank txns with Amazon

✅ Cookies persist until Amazon expires them (typically weeks)
✅ No credentials are stored — cookie jar only
🔁 When cookies expire, just re-run cookie_capture.py"""


@mcp.tool()
def check_auth_status() -> str:
    """Check if cookies are stored and usable.

    This tool does not hit Amazon — it only checks local file presence and
    queries the keyring. Safe to call at any time.
    """
    has_cookies = cookie_jar_exists()
    creds = load_credentials()
    has_creds = creds is not None

    status_lines = []

    if has_cookies:
        status_lines.append("✅ Cookie jar exists at ~/.amazon-orders-mcp/cookies.json")
        status_lines.append(
            "   Try `get_order_history(time_filter='last30')` to verify they still work."
        )
    else:
        status_lines.append("❌ No cookie jar found")
        status_lines.append(
            "   Run `uv run python cookie_capture.py` to capture a session."
        )

    if has_creds:
        status_lines.append(
            "\nℹ️  Credentials also found in keyring (optional fallback)"
        )

    return "\n".join(status_lines)


# ---------------------------------------------------------------------------
# Order tools — each dispatches the blocking work to a worker thread
# ---------------------------------------------------------------------------


def _blocking_get_order_history(
    year: Optional[int],
    time_filter: Optional[str],
    full_details: bool,
    start_index: Optional[int],
) -> str:
    from amazonorders.orders import AmazonOrders

    session = build_session()
    ensure_authenticated(session)
    amazon_orders = AmazonOrders(session)

    orders = amazon_orders.get_order_history(
        year=year,
        start_index=start_index,
        full_details=full_details,
        time_filter=time_filter,
    )
    return _json(serialize_orders(orders))


@mcp.tool()
async def get_order_history(
    year: Optional[int] = None,
    time_filter: Optional[str] = None,
    full_details: bool = False,
    start_index: Optional[int] = None,
) -> str:
    """Fetch Amazon order history.

    Args:
        year: Calendar year to fetch (e.g. 2026). Default: current year if
            neither `year` nor `time_filter` is supplied.
        time_filter: Alternative to `year`. One of: "last30", "months-3",
            "year-YYYY". Cannot be combined with `year`.
        full_details: If True, fetch each order's full detail page (slower).
        start_index: Paging offset into results.

    Returns:
        JSON array of serialized Order objects.
    """
    return await _run_blocking(
        _blocking_get_order_history,
        year,
        time_filter,
        full_details,
        start_index,
        timeout=TIMEOUT_PAGED_CALL,
        tool_name="get_order_history",
    )


def _blocking_get_order(order_id: str) -> str:
    from amazonorders.orders import AmazonOrders

    session = build_session()
    ensure_authenticated(session)
    amazon_orders = AmazonOrders(session)

    order = amazon_orders.get_order(order_id)
    return _json(serialize_order(order))


@mcp.tool()
async def get_order(order_id: str) -> str:
    """Fetch full details for a single Amazon order.

    Args:
        order_id: Amazon order number (e.g. "112-1234567-1234567").

    Returns:
        JSON object with serialized Order data (always full details).
    """
    return await _run_blocking(
        _blocking_get_order,
        order_id,
        timeout=TIMEOUT_SINGLE_CALL,
        tool_name="get_order",
    )


# ---------------------------------------------------------------------------
# Transaction tools
# ---------------------------------------------------------------------------


def _fetch_transactions_for_range(
    start_date: Optional[str], end_date: Optional[str], days: Optional[int]
) -> List[Any]:
    """Helper: fetch transactions for a date range by computing days-back.

    The amazon-orders library only accepts `days` back from today. We compute
    the right `days` value and filter the results client-side.
    """
    from amazonorders.transactions import AmazonTransactions

    session = build_session()
    ensure_authenticated(session)
    amazon_transactions = AmazonTransactions(session)

    if days is not None:
        return cast(List[Any], amazon_transactions.get_transactions(days=days))

    if start_date:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date) if end_date else date.today()
        days_back = (date.today() - start).days + 1
        all_txns = amazon_transactions.get_transactions(days=days_back)
        filtered = [
            t for t in all_txns if t.completed_date and start <= t.completed_date <= end
        ]
        return filtered

    return cast(List[Any], amazon_transactions.get_transactions(days=365))


def _blocking_get_transactions(
    days: Optional[int],
    start_date: Optional[str],
    end_date: Optional[str],
) -> str:
    txns = _fetch_transactions_for_range(start_date, end_date, days)
    return _json(serialize_transactions(txns))


@mcp.tool()
async def get_transactions(
    days: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> str:
    """Fetch Amazon payment transactions (the cpe/yourpayments/transactions feed).

    Provide EITHER `days` (back from today) OR `start_date`+`end_date` (YYYY-MM-DD).
    If neither is supplied, defaults to the last 365 days.

    Note: charges appear as NEGATIVE grand_total, refunds as POSITIVE.

    Returns:
        JSON array of serialized Transaction objects.
    """
    return await _run_blocking(
        _blocking_get_transactions,
        days,
        start_date,
        end_date,
        timeout=TIMEOUT_PAGED_CALL,
        tool_name="get_transactions",
    )


def _blocking_match_transactions_by_amount(
    queries: List[Dict[str, Any]],
    tolerance: float,
) -> str:
    if not queries:
        return _json([])

    parsed_queries = []
    earliest = date.today()
    latest = date.today()
    for q in queries:
        q_date = date.fromisoformat(q["date"])
        window = int(q.get("window_days", 3))
        amount = float(q["amount"])
        parsed_queries.append(
            {
                "id": q.get("id"),
                "date": q_date,
                "amount": amount,
                "window_days": window,
                "raw": q,
            }
        )
        earliest = min(earliest, q_date - timedelta(days=window))
        latest = max(latest, q_date + timedelta(days=window))

    txns = _fetch_transactions_for_range(
        start_date=earliest.isoformat(),
        end_date=latest.isoformat(),
        days=None,
    )

    by_date: Dict[date, List[Any]] = {}
    for t in txns:
        if t.completed_date is not None:
            by_date.setdefault(t.completed_date, []).append(t)

    results = []
    for q in parsed_queries:
        matches = []
        target_amount = q["amount"]
        for offset in range(-q["window_days"], q["window_days"] + 1):
            check_date = q["date"] + timedelta(days=offset)
            for t in by_date.get(check_date, []):
                if t.grand_total is None:
                    continue
                if abs(t.grand_total - target_amount) <= tolerance:
                    matches.append(
                        {
                            "date_offset_days": offset,
                            **serialize_transaction(t),
                        }
                    )

        results.append(
            {
                "query": q["raw"],
                "match_count": len(matches),
                "matches": matches,
            }
        )

    return _json(results)


@mcp.tool()
async def match_transactions_by_amount(
    queries: List[Dict[str, Any]],
    tolerance: float = 0.01,
) -> str:
    """Cross-reference external transactions (e.g. bank/credit card) against Amazon.

    Convenience tool for the Monarch-review workflow: given a list of
    {date, amount} pairs, find Amazon transactions that plausibly match.

    Args:
        queries: List of dicts with keys:
            - `date` (str YYYY-MM-DD): external transaction date
            - `amount` (float): external amount as it appears on the bank
              statement — negative for purchases, positive for refunds
            - `id` (str, optional): your own identifier to round-trip
            - `window_days` (int, optional, default 3): how many days of
              slop to allow around the date when matching
        tolerance: Dollar tolerance for amount matches. Default $0.01.

    Returns:
        JSON array of {query, match_count, matches} objects.
    """
    return await _run_blocking(
        _blocking_match_transactions_by_amount,
        queries,
        tolerance,
        timeout=TIMEOUT_PAGED_CALL,
        tool_name="match_transactions_by_amount",
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Main entry point for the server."""
    logger.info("Starting Amazon Orders MCP Server...")
    try:
        mcp.run()
    except Exception as e:
        logger.error(f"Failed to run server: {e}")
        raise


# Export for `mcp run`
app = mcp


if __name__ == "__main__":
    main()
