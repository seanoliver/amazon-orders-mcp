#!/usr/bin/env python3
"""
Interactive CLI to authenticate with Amazon and store credentials for the
Amazon Orders MCP server.

This script:
  1. Prompts for Amazon email, password, and optional TOTP secret key.
  2. Stores them in the system keyring.
  3. Builds an AmazonSession and runs a real login — handling any captcha
     or device-selection prompts interactively in your terminal.
  4. On success, the session's cookies are persisted to
     ~/.amazon-orders-mcp/cookies.json for future MCP server use.

Run from the repo root:
    uv run python login_setup.py
"""

import getpass
import sys
from pathlib import Path

# Add the src directory so we can import our package without installing
src_path = Path(__file__).parent / "src"
sys.path.insert(0, str(src_path))

from amazon_orders_mcp.client import build_session, ensure_authenticated  # noqa: E402
from amazon_orders_mcp.secure_session import (  # noqa: E402
    COOKIE_JAR_PATH,
    AmazonCredentials,
    delete_credentials,
    ensure_data_dir,
    save_credentials,
)


def main() -> None:
    print("\n🛒 Amazon Orders MCP — One-Time Setup")
    print("=" * 45)
    print("This will store your Amazon credentials in the system keyring")
    print("and authenticate a session for the MCP server to use.\n")

    ensure_data_dir()

    # Clear any existing stored credentials so this is a clean re-setup.
    try:
        delete_credentials()
        print("🗑️  Cleared any existing keyring entries")
    except Exception as e:
        print(f"⚠️  Could not clear existing credentials: {e}")

    print("\n📧 Amazon credentials")
    email = input("Amazon email: ").strip()
    if not email:
        print("❌ Email is required. Exiting.")
        return

    password = getpass.getpass("Amazon password: ")
    if not password:
        print("❌ Password is required. Exiting.")
        return

    print("\n🔐 Two-factor authentication (recommended)")
    print("If you have 2FA enabled on Amazon, you can optionally provide the")
    print("TOTP *secret key* (not a live 6-digit code). This lets the MCP server")
    print("handle future 2FA challenges automatically.")
    print("\nTo get the secret key:")
    print("  1. Go to Amazon → Account → Login & security → 2FA settings")
    print("  2. Disable and re-enable your authenticator app to see the secret")
    print("  3. Copy the 'Secret Key' string shown next to the QR code")
    print("\nLeave blank to skip (you'll be prompted for 2FA codes interactively).")
    otp_secret = getpass.getpass("TOTP secret key (optional): ").strip() or None

    credentials = AmazonCredentials(
        email=email, password=password, otp_secret_key=otp_secret
    )

    # Save to keyring FIRST so that if login blows up we still have them stored.
    try:
        save_credentials(credentials)
        print("✅ Credentials saved to keyring")
    except Exception as e:
        print(f"❌ Failed to save credentials: {e}")
        return

    print("\n🔄 Logging in to Amazon...")
    print("(This may take a moment. If Amazon shows a captcha, solve it in")
    print(" the terminal prompt when asked.)\n")

    try:
        session = build_session(credentials=credentials, interactive=True)
        ensure_authenticated(session)
    except Exception as e:
        print(f"\n❌ Login failed: {e}")
        print("\nYour credentials were saved to the keyring, but the session")
        print("is not established. You can re-run this script to try again.")
        return

    # Quick smoke test — fetch the last 30 days of transactions
    print("\n🧪 Testing connection by fetching last 30 days of transactions...")
    try:
        from amazonorders.transactions import AmazonTransactions

        txns = AmazonTransactions(session).get_transactions(days=30)
        print(f"✅ Retrieved {len(txns)} transactions from the last 30 days")
    except Exception as e:
        print(f"⚠️  Transaction fetch failed: {e}")
        print("Login may still be OK — the server will retry on demand.")

    print(f"\n✅ Cookies saved to: {COOKIE_JAR_PATH}")
    print("\n🎉 Setup complete!")
    print("\nYou can now use these tools in Claude Code:")
    print("   • get_order_history - List orders")
    print("   • get_order - Single order details")
    print("   • get_transactions - Payments feed")
    print("   • match_transactions_by_amount - Cross-reference bank txns")
    print("\n💡 Session cookies persist until Amazon expires them.")


if __name__ == "__main__":
    main()
