# Code Review — 2026-04-10

Initial code review of the repo treated as a single PR. Captures every finding as a tracked action item so we can work through them one by one.

Legend: `[ ]` not started · `[~]` in progress · `[x]` done · `[-]` won't fix (with reason)

---

## Critical

- [ ] **1. Add a real test suite.** `tests/` is empty and not tracked, but `pyproject.toml` declares `pytest` and `README.md` tells users to run it. Minimum viable coverage:
  - `serialize.py` — all six functions against `SimpleNamespace` stubs.
  - `_fetch_transactions_for_range` — monkeypatch `AmazonTransactions`, verify date-range filter math.
  - `_blocking_match_transactions_by_amount` — verify window + tolerance matching.
  - `_run_blocking` — verify all four exception branches produce the expected JSON shape.
  - `NonInteractiveIO.prompt` — verify it raises `NonInteractiveAuthRequired`.
  - None of these require a real Amazon account.

- [x] **2. Validate input in `match_transactions_by_amount`.** Added `TransactionQuery` pydantic `BaseModel` with `extra="allow"` (so caller metadata round-trips). Validation happens synchronously in the async wrapper before dispatching to the thread, so `ValidationError` produces a clean `{error, validation_errors}` payload instead of being mangled by `_run_blocking`'s generic handler. Added `window_days` bounds (`0 ≤ n ≤ 30`). Smoke-tested against: good input, extra fields, missing `amount`, bad date string, out-of-range window.

- [ ] **3. Guard `_fetch_transactions_for_range` against future `start_date`.** `server.py:290` — if `start_date` is in the future, `days_back = (today - start).days + 1` becomes negative and the upstream library call will error or misbehave. Add `if start > date.today(): return []` (or raise a clear error).

- [ ] **4. Handle the user closing the browser in `cookie_capture.py`.** `cookie_capture.py:72-84` polls `context.cookies()` in a while loop. Closing Chromium mid-flow raises a Playwright error and crashes with an ugly stack trace. Wrap the poll in `try/except` for `PlaywrightError` and print a clean "browser closed — cancelled" message.

- [x] **5. Fix lint/format failures (would fail CI).** Ran `black` + `isort`; `cookie_capture.py` and `server.py` reformatted. All 7 files pass `--check`.

- [x] **6. Fix mypy errors.** Added `[[tool.mypy.overrides]] module = "amazonorders.*"` block to `pyproject.toml` (clears 5 `import-untyped`). Wrapped the two `amazon_transactions.get_transactions(...)` returns in `_fetch_transactions_for_range` with `cast(List[Any], ...)`. `mypy src` reports zero errors.

- [x] **7. Remove or use unused dependencies/imports.**
  - [x] `server.py:16` — dropped unused `Awaitable` from typing import.
  - [x] `server.py:47` — deleted unused `TIMEOUT_CHEAP` constant.
  - [x] `pyproject.toml:27` — `pydantic>=2.0.0` now imported and used by `TransactionQuery` (item 2).

---

## Code Quality

- [ ] **8. `load_dotenv()` at module-import time is unpredictable.** `server.py:39` loads `.env` from CWD — for an `mcp run`-launched server, CWD is wherever Claude Code was started. Either call with an explicit path (`Path(__file__).parent.parent.parent / ".env"`) or drop it entirely (env-var fallback in `load_credentials()` works without `python-dotenv`).

- [ ] **9. Lazy imports inside blocking functions lack explanation.** `server.py:184, 236, 278` — `from amazonorders.orders import AmazonOrders` etc. are imported lazily. Presumably to keep MCP tool discovery fast and avoid BeautifulSoup/amazon-orders at server startup. Either add a one-line comment saying so, or hoist them to module level.

- [ ] **10. `match_transactions_by_amount` matching loop is O(Q × W × T_day).** `server.py:375-398` iterates `range(-window_days, window_days + 1)` for every query. Fine for small queries; for 100+, restructure as a single O(T) bucketing pass with dict lookups.

- [ ] **11. `serialize_transaction` inconsistent date handling.** `serialize.py:108-124` — `completed_date` goes through `_d()` but `payment_method`, `seller` etc. use raw `getattr`. Not a bug; add a comment noting which fields are date-ish, or normalize.

- [ ] **12. `secure_session.py:47` silently swallows `OSError` on chmod.** Acceptable for cross-platform (Windows has no POSIX chmod) but should log at debug level.

- [ ] **13. `secure_session.py:77` `except Exception` on keyring load is too broad.** Catch `keyring.errors.KeyringError` instead so real bugs (e.g. `ImportError`) surface.

- [ ] **14. `_install_request_timeout` safety net.** `client.py:42-64` monkey-patches `inner_session.request`. Add `assert isinstance(inner_session, requests.Session)` as a safety net in case upstream restructures.

- [ ] **15. `check_auth_status` is sync but hits the keyring.** `server.py:147-176` — `load_credentials()` calls keyring, which on macOS Keychain can prompt the user. On a headless run that would hang. Route through `_run_blocking` with `TIMEOUT_CHEAP` (ties to item 7).

- [ ] **16. Emoji in MCP tool responses.** `server.py:121-144` and `check_auth_status` use emoji. Fine for Claude Code, but some MCP clients render them poorly. Low priority.

---

## Security

- [ ] **17. `cookie_capture.py:117` write-then-chmod race.** Tiny window where another process on the same UID could read the cookie file before chmod applies. Create with restricted perms from the start: `os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)` then `os.fdopen`.

- [ ] **18. Error payloads include raw exception messages.** `server.py:109` — `_error(f"{tool_name} failed: {e}", ...)`. `amazon-orders` exceptions are unlikely to contain secrets today, but if anything upstream ever included a cookie value in an error string, it'd land in the MCP response. Consider logging the full exception server-side and only exposing `type(e).__name__` to the client.

- [ ] **19. `login_setup.py` saves credentials before validating them.** `login_setup.py:78-83` persists to keyring *before* `ensure_authenticated` succeeds. Comment says "so that if login blows up we still have them stored" — but a typo in the password should NOT be persisted. Move the `save_credentials(credentials)` call to AFTER `ensure_authenticated(session)` succeeds.

---

## Performance

- [ ] **20. Session is reconstructed on every tool call.** Each `_blocking_*` rebuilds `AmazonSession` via `build_session()` — re-reads cookie jar, re-installs request timeout. Fine for personal use; for higher traffic, cache as a module-level singleton behind a `threading.Lock`.

---

## Documentation

- [ ] **21. Python version mismatch between README and black config.** `README.md:42` says "Python 3.11 or 3.12" but `pyproject.toml:52` has `target-version = ['py312']` for black. Either widen black (`['py311', 'py312']`) or narrow `requires-python` to `>=3.12`.

- [ ] **22. `get_order_history` docstring claims "current year" default.** `server.py:216-223` says "Default: current year if neither `year` nor `time_filter` is supplied" but the code passes both as `None` to the library. Verify the library's actual default and update docstring (or wire an explicit default).

- [ ] **23. Missing bug journal entries.** Per `~/.claude/CLAUDE.md`, non-trivial bug fixes should have `docs/bugs/*.md` entries. The two bug-fix commits in history have none:
  - `01383a7 fix: prevent MCP server from hanging on stuck Amazon requests`
  - `d95f068 feat: surface clear "re-run cookie_capture.py" message on stale cookies`

---

## Follow-ups (separate PRs, not part of this cleanup)

- [ ] **F1.** GitHub Actions CI running `black --check`, `isort --check`, `mypy`, `pytest` on PRs.
- [ ] **F2.** Replace `load_dotenv()` + env-var fallback entirely with keyring-only. Removes a dep and one config path.
- [ ] **F3.** Upstream a `py.typed` marker contribution to `amazonorders` — would eliminate the mypy override from item 6.
- [ ] **F4.** Add a `refresh_cookies` MCP tool that shells out to `cookie_capture.py`, so users can refresh from inside Claude Code without dropping to a terminal.
- [ ] **F5.** Add `CHANGELOG.md`.

---

## Progress Log

- **2026-04-10**: Initial review completed. 23 items + 5 follow-ups logged.
