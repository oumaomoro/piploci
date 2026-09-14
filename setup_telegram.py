"""
setup_telegram.py — Piploci Telegram Chat ID Auto-Configuration
---------------------------------------------------------------
Run this ONCE after sending /start (or any message) to @piploci_bot on Telegram.
It will:
  1. Poll the Telegram Bot API for incoming messages.
  2. Extract the sender's numerical chat ID.
  3. Inject TELEGRAM_CHAT_ID into your .env file.
  4. Send a test alert to confirm delivery.

Usage:
    python setup_telegram.py
"""

import json
import os
import re
import sys
import urllib.request
import urllib.parse
import urllib.error

BOT_TOKEN = "8637700646:AAEFXQepnyw8h1WaC5Bu-yJ-xnrvSAbMU6Q"
ENV_FILE = os.path.join(os.path.dirname(__file__), ".env")


def get_updates():
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.URLError as e:
        print(f"[ERROR] Network error: {e}")
        sys.exit(1)


def send_message(chat_id: int, text: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": text, "parse_mode": "HTML"}).encode()
    try:
        with urllib.request.urlopen(url, data=data, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.URLError as e:
        print(f"[ERROR] Could not send message: {e}")


def patch_env(chat_id: int):
    """Read .env and replace TELEGRAM_CHAT_ID= with the detected value."""
    if not os.path.exists(ENV_FILE):
        print(f"[ERROR] .env not found at {ENV_FILE}")
        sys.exit(1)

    with open(ENV_FILE, "r", encoding="utf-8") as f:
        content = f.read()

    pattern = r"^(TELEGRAM_CHAT_ID=).*$"
    replacement = f"TELEGRAM_CHAT_ID={chat_id}"
    new_content, count = re.subn(pattern, replacement, content, flags=re.MULTILINE)

    if count == 0:
        # Key doesn't exist yet, append it
        new_content += f"\nTELEGRAM_CHAT_ID={chat_id}\n"

    with open(ENV_FILE, "w", encoding="utf-8") as f:
        f.write(new_content)

    print(f"[OK] .env updated: TELEGRAM_CHAT_ID={chat_id}")


def main():
    print("=" * 60)
    print("  Piploci — Telegram Auto-Configuration")
    print("=" * 60)
    print(f"\n[INFO] Using bot token: {BOT_TOKEN[:20]}...")
    print("[INFO] Polling Telegram for recent messages...\n")

    result = get_updates()

    if not result.get("ok"):
        print(f"[ERROR] Telegram API returned error: {result}")
        sys.exit(1)

    updates = result.get("result", [])

    if not updates:
        print("[WARNING] No messages found.")
        print("\n  ➡  Please open Telegram and send any message (e.g. /start) to @piploci_bot, then run this script again.\n")
        sys.exit(0)

    # Get the most recent message's chat ID
    latest = updates[-1]
    msg = latest.get("message") or latest.get("channel_post") or {}
    chat = msg.get("chat", {})
    chat_id = chat.get("id")
    username = chat.get("username") or chat.get("first_name") or "Unknown"

    if not chat_id:
        print("[ERROR] Could not extract chat ID from updates. Raw response:")
        print(json.dumps(updates[-1], indent=2))
        sys.exit(1)

    print(f"[FOUND] Chat ID: {chat_id}  (User: @{username})")

    # Patch .env
    patch_env(chat_id)

    # Send confirmation alert
    print("\n[INFO] Sending test alert to Telegram...")
    res = send_message(
        chat_id,
        "🎯 <b>Piploci Alert Engine — ACTIVE</b>\n\n"
        "✅ Telegram integration confirmed.\n"
        "You will now receive:\n"
        "  • 🚀 Trade fill notifications\n"
        "  • 🚨 Circuit breaker alerts\n"
        "  • 📊 Daily profit summaries\n\n"
        "<i>Powered by @piploci_bot</i>"
    )

    if res and res.get("ok"):
        print("[OK] Test alert delivered successfully!")
    else:
        print(f"[WARNING] Alert may not have delivered. Response: {res}")

    print("\n" + "=" * 60)
    print(f"  Setup complete! Chat ID {chat_id} saved to .env")
    print("  Restart the bot engine for changes to take effect.")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
