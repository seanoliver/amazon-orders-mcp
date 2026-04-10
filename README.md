# Amazon Orders MCP

A [Model Context Protocol](https://modelcontextprotocol.io) server that exposes
Amazon.com personal order history and payment transactions to MCP-compatible
clients like [Claude Code](https://claude.com/claude-code).

Under the hood it wraps the excellent
[`amazon-orders`](https://github.com/alexdlaird/amazon-orders) Python library,
adding:

- A system-keyring-backed credential store (email, password, TOTP secret).
- Cookie persistence isolated to `~/.amazon-orders-mcp/`.
- A non-interactive IO adapter that fails fast on captcha prompts instead of
  hanging the server.
- Serialization of amazon-orders entities to plain JSON (the upstream library
  does not expose `to_dict()`).
- A `match_transactions_by_amount` helper for cross-referencing external
  bank/credit-card transactions (e.g. from Monarch Money) against Amazon
  orders by date and amount.

## Why

Amazon does not offer a public API for personal order history. The only way
to get structured data is to scrape the logged-in user's own pages. This MCP
server makes that data available to LLM tools in a clean, programmatic way
so you can match bank transactions against real order contents, categorize
spending, audit returns, etc.

## Features

| Tool | Description |
| --- | --- |
| `check_auth_status` | Check whether credentials and cookies are stored |
| `setup_authentication` | Get setup instructions |
| `get_order_history` | Fetch orders by year or time filter |
| `get_order` | Fetch full details for a specific order number |
| `get_transactions` | Fetch the Amazon payments/transactions feed by date range |
| `match_transactions_by_amount` | Cross-reference external txns against Amazon by date + amount |

## Requirements

- Python 3.11 or 3.12 (3.13 not yet supported by the upstream library)
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- An Amazon.com account (US only — international Amazon sites are not supported)
- 2FA recommended, with access to the TOTP secret key for automation

## Installation

Clone and install dependencies with uv:

```bash
git clone https://github.com/seanoliver/amazon-orders-mcp.git
cd amazon-orders-mcp
uv sync
```

## One-time setup — cookie capture

**Why this is necessary:** Amazon's JavaScript WAF blocks `requests`-based
logins with challenge pages the `amazon-orders` library cannot solve. Even
with correct credentials and a TOTP secret, `session.login()` typically
fails with `A JavaScript-based authentication challenge page has been found`.

The reliable workaround — used by this server — is to capture cookies from
a real Chromium browser after you sign in normally, then hand them to
`amazon-orders`. The library checks for the `x-main` cookie and short-circuits
its login flow when one is present.

### Step-by-step

```bash
uv run python cookie_capture.py
```

A Chromium window will open. Sign in to Amazon normally — email, password,
and any 2FA code (SMS or authenticator app — both work fine since you're
doing it interactively).

As soon as the `x-main` cookie is set, the script:

1. Navigates to your order history page to warm up the session.
2. Extracts all `*.amazon.com` cookies (including httpOnly ones).
3. Writes them in the flat `{name: value}` format `amazon-orders` expects to
   `~/.amazon-orders-mcp/cookies.json` with `0600` permissions.
4. Runs a smoke test by fetching the last 30 days of transactions.

### Cookie lifetime

Cookies persist until Amazon expires them — typically several weeks. When
the server starts returning auth errors, just re-run `cookie_capture.py`.

### Alternative (not recommended): credential-based login

`login_setup.py` is provided as a secondary path for environments where
the JavaScript WAF challenge doesn't fire. In practice this is rare.

```bash
uv run python login_setup.py
```

If you go this route, credentials are stored in the system keyring under
`com.mcp.amazon-orders-mcp`.

## Register with Claude Code

Add the server to your Claude Code MCP configuration. For `~/.claude.json` or
the equivalent MCP settings file:

```json
{
  "mcpServers": {
    "amazon-orders": {
      "command": "uv",
      "args": [
        "--directory",
        "/absolute/path/to/amazon-orders-mcp",
        "run",
        "amazon-orders-mcp"
      ]
    }
  }
}
```

Then restart Claude Code.

## Usage examples

Inside a Claude Code session:

```
Use get_transactions for the last 90 days and summarize the categories of
spending.
```

```
I have 5 bank transactions I can't identify. Use match_transactions_by_amount
with this JSON: [{"date": "2026-03-04", "amount": -35.01}, ...]
```

```
Fetch full details for Amazon order 112-1234567-1234567.
```

## Notes and caveats

- **US Amazon.com only.** International sites (.co.uk, .de, etc.) are not
  supported by the underlying library.
- **DOM scraping.** Amazon periodically changes its HTML. If tools start
  returning `Check if Amazon changed the HTML` errors, upgrade the
  `amazon-orders` dependency or wait for a fix upstream.
- **Captcha handling.** The server refuses to prompt on captcha challenges —
  it raises `NonInteractiveAuthRequired`. If that happens, re-run
  `login_setup.py` interactively to solve the captcha and refresh cookies.
- **Rate limiting.** Amazon may throttle you if you fetch many orders with
  `full_details=True` in quick succession. There's no hard rate limit in the
  library; be conservative.
- **Transaction sign convention.** `amazon-orders` returns charges as
  negative `grand_total` and refunds as positive. `match_transactions_by_amount`
  assumes the external query uses the same convention.

## Development

Run formatters and tests:

```bash
uv run black src
uv run isort src
uv run mypy src
uv run pytest
```

## License

MIT. See [LICENSE](LICENSE).

## Acknowledgements

- [`amazon-orders`](https://github.com/alexdlaird/amazon-orders) by Alex Laird —
  the library that does all the real work.
- [`monarch-mcp-server`](https://github.com/robcerda/monarch-mcp-server) by
  Rob Cerda — template for the MCP scaffolding and keyring pattern.
