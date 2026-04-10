"""
Amazon session factory and non-interactive IO adapter.

This server authenticates via cookies captured from a real browser session
(see `cookie_capture.py`). Credentials are optional — they are only needed
if you want to attempt a fresh `session.login()`, which in practice is
blocked by Amazon's JavaScript WAF challenges for requests-based sessions.

The cookie-only path is the supported happy path.
"""

import logging
from typing import Any, Optional

from amazonorders.conf import AmazonOrdersConfig
from amazonorders.session import AmazonSession, IODefault

from amazon_orders_mcp.secure_session import (
    COOKIE_JAR_PATH,
    OUTPUT_DIR,
    AmazonCredentials,
    cookie_jar_exists,
    ensure_data_dir,
    load_credentials,
)

logger = logging.getLogger(__name__)

# Placeholder credentials used when we don't have real ones stored.
# AmazonSession's constructor requires non-empty username/password even if
# they're never actually used (because the cookie jar short-circuits login).
_PLACEHOLDER_EMAIL = "[email protected]"
_PLACEHOLDER_PASSWORD = "unused-cookie-auth"


class NonInteractiveAuthRequired(RuntimeError):
    """Raised when amazon-orders needs a human for captcha/device selection."""

    pass


class NonInteractiveIO(IODefault):
    """IODefault subclass that refuses to prompt — fails fast instead."""

    def prompt(self, message: str, type: Optional[type] = None, **kwargs: Any) -> Any:
        raise NonInteractiveAuthRequired(
            f"Amazon requires interactive input ({message!r}). "
            "Cookies may be expired — run `uv run python cookie_capture.py` "
            "to capture a fresh session."
        )

    def echo(self, message: str, **kwargs: Any) -> None:
        logger.info(message)


def build_config() -> AmazonOrdersConfig:
    """Build an AmazonOrdersConfig that isolates cookies + output in our data dir."""
    ensure_data_dir()
    return AmazonOrdersConfig(
        data={
            "cookie_jar_path": str(COOKIE_JAR_PATH),
            "output_dir": str(OUTPUT_DIR),
        }
    )


def build_session(
    credentials: Optional[AmazonCredentials] = None,
    interactive: bool = False,
) -> AmazonSession:
    """
    Construct an AmazonSession.

    If a cookie jar already exists at the configured path, `AmazonSession.__init__`
    loads it automatically and a subsequent `login()` call short-circuits based
    on the `x-main` cookie. In that case, credentials are not actually used.

    If no cookie jar exists, credentials become load-bearing but the login is
    likely to hit Amazon's JavaScript WAF challenge — see cookie_capture.py
    for the supported path.

    Args:
        credentials: Override loaded credentials. Leave None to load from keyring.
        interactive: If True, use `IODefault` which prompts stdin on challenges.
            For use by CLI scripts only; the server uses non-interactive mode.
    """
    creds = credentials or load_credentials()

    if creds is None:
        if not cookie_jar_exists():
            raise RuntimeError(
                "No Amazon cookies found. Run `uv run python cookie_capture.py` "
                "to capture a session from your browser."
            )
        # Cookie-only auth — use placeholders to satisfy the constructor.
        creds = AmazonCredentials(
            email=_PLACEHOLDER_EMAIL,
            password=_PLACEHOLDER_PASSWORD,
        )
        logger.info("Using cookie-only authentication (no stored credentials)")

    io: IODefault = IODefault() if interactive else NonInteractiveIO()

    return AmazonSession(
        username=creds.email,
        password=creds.password,
        otp_secret_key=creds.otp_secret_key,
        config=build_config(),
        io=io,
    )


def ensure_authenticated(session: AmazonSession) -> None:
    """
    Make sure the session is logged in, reusing the cookie jar if possible.

    `amazon-orders`'s `login()` method checks `auth_cookies_stored()` first,
    which looks for the `x-main` cookie. If present, it sets `is_authenticated`
    and short-circuits without hitting the sign-in form. This is the path we
    rely on — we never actually submit credentials.
    """
    if not session.is_authenticated:
        session.login()
    if not session.is_authenticated:
        raise RuntimeError(
            "Amazon authentication failed. Cookies may be stale — "
            "run `uv run python cookie_capture.py` to refresh."
        )
