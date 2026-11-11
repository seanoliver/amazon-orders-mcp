"""Unit tests for client.py's non-interactive IO adapter."""

import pytest

from amazon_orders_mcp.client import NonInteractiveAuthRequired, NonInteractiveIO


class TestNonInteractiveIO:
    def test_prompt_raises(self):
        io = NonInteractiveIO()
        with pytest.raises(NonInteractiveAuthRequired) as exc_info:
            io.prompt("Enter CAPTCHA: ")
        # Error message should mention the prompt and how to recover
        msg = str(exc_info.value)
        assert "Enter CAPTCHA" in msg
        assert "cookie_capture.py" in msg

    def test_echo_does_not_raise(self):
        # echo should log, not raise — otherwise any informational message
        # from amazon-orders would crash the server.
        io = NonInteractiveIO()
        io.echo("informational message")  # should be a no-op side effect


class TestInstallRequestTimeout:
    def test_injects_disable_csd_and_timeout(self):
        from unittest.mock import MagicMock

        from amazon_orders_mcp.client import _install_request_timeout

        fake_session = MagicMock()
        mock_request = MagicMock()
        fake_session.session.request = mock_request

        _install_request_timeout(fake_session, timeout=12.0)
        wrapped_request = fake_session.session.request

        wrapped_request(
            "GET", "https://www.amazon.com/your-orders/orders?timeFilter=last30"
        )
        assert mock_request.called
        args, kwargs = mock_request.call_args
        assert kwargs["timeout"] == 12.0
        assert "disableCsd=no-js" in args[1]
        assert "timeFilter=last30" in args[1]
