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
