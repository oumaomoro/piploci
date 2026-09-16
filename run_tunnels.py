"""
Piploci Automated Tunnel Manager
Starts Cloudflare Quick Tunnels for both the FastAPI backend (port 8000)
and the Streamlit dashboard (port 8501), saves active URLs, updates
Streamlit configuration, and syncs with GitHub for continuous mobile availability.
"""

import subprocess
import threading
import re
import sys
import os
import time
import json
from pathlib import Path

TUNNEL_REGEX = re.compile(r"https://[a-z0-9\-]+\.trycloudflare\.com")
WORKSPACE_DIR = Path(__file__).resolve().parent

def kill_existing_tunnels():
    """Terminates any previously running cloudflared instances to avoid port/tunnel conflicts."""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/IM", "cloudflared.exe"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            subprocess.run(["pkill", "-f", "cloudflared"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass

def start_tunnel(port: int, label: str, results: dict):
    """Starts a cloudflared quick tunnel and captures the public URL."""
    cmd = ["cloudflared", "tunnel", "--url", f"http://localhost:{port}"]
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except Exception as e:
        print(f"❌ Failed to launch cloudflared for {label}: {e}")
        return

    for line in iter(proc.stdout.readline, ''):
        line = line.strip()
        match = TUNNEL_REGEX.search(line)
        if match and label not in results:
            url = match.group(0)
            results[label] = url
            print(f"  ✅  {label:20s} -> {url}")
            sys.stdout.flush()
    proc.wait()

def update_system_configs(results: dict):
    """Updates secrets.toml and api_client.py with the active Cloudflare tunnel URLs."""
    api_tunnel = results.get("FastAPI Backend")
    dash_tunnel = results.get("Streamlit Dashboard")
    if not api_tunnel:
        return

    api_url = f"{api_tunnel.rstrip('/')}/api/v1"

    # 1. Write tunnel_urls.txt and tunnel_urls.json
    try:
        txt_path = WORKSPACE_DIR / "tunnel_urls.txt"
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(f"DASHBOARD_URL={dash_tunnel}\n")
            f.write(f"API_URL={api_tunnel}\n")
            f.write(f"API_BASE={api_url}\n")
            f.write(f"UPDATED_AT={time.strftime('%Y-%m-%d %H:%M:%S')}\n")

        json_path = WORKSPACE_DIR / "tunnel_urls.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump({
                "dashboard": dash_tunnel,
                "api": api_tunnel,
                "api_base": api_url,
                "updated_at": time.strftime('%Y-%m-%d %H:%M:%S')
            }, f, indent=2)
    except Exception as e:
        print(f"⚠️ Could not write tunnel URL files: {e}")

    # 2. Update .streamlit/secrets.toml
    try:
        streamlit_dir = WORKSPACE_DIR / ".streamlit"
        streamlit_dir.mkdir(exist_ok=True)
        secrets_file = streamlit_dir / "secrets.toml"
        secrets_content = f'API_BASE = "{api_url}"\n'
        with open(secrets_file, "w", encoding="utf-8") as f:
            f.write(secrets_content)
        print("  📝 Updated .streamlit/secrets.toml")
    except Exception as e:
        print(f"⚠️ Could not update secrets.toml: {e}")

    # 3. Update bot/dashboard/api_client.py default fallback
    try:
        client_path = WORKSPACE_DIR / "bot" / "dashboard" / "api_client.py"
        if client_path.exists():
            content = client_path.read_text(encoding="utf-8")
            pattern = re.compile(r'_CLOUDFLARE_DEFAULT\s*=\s*"[^"]*"')
            new_line = f'_CLOUDFLARE_DEFAULT = "{api_url}"'
            if pattern.search(content):
                new_content = pattern.sub(new_line, content)
                client_path.write_text(new_content, encoding="utf-8")
                print("  📝 Updated bot/dashboard/api_client.py fallback URL")

                # Push to Git so Streamlit Cloud pulls the updated endpoint
                subprocess.run(
                    ["git", "add", "bot/dashboard/api_client.py"],
                    cwd=str(WORKSPACE_DIR),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                res = subprocess.run(
                    ["git", "commit", "-m", "fix: update active Cloudflare tunnel URL for remote dashboard access"],
                    cwd=str(WORKSPACE_DIR),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                if "nothing to commit" not in res.stdout:
                    push_res = subprocess.run(
                        ["git", "push"],
                        cwd=str(WORKSPACE_DIR),
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                    )
                    if push_res.returncode == 0:
                        print("  🚀 Pushed updated tunnel URL to GitHub (Streamlit Cloud synced!)")
    except Exception as e:
        print(f"⚠️ Could not sync with git: {e}")


if __name__ == "__main__":
    print("\n" + "="*70)
    print("      PIPLOCI 24/7 AVAILABILITY & CLOUDFLARE TUNNEL MANAGER      ")
    print("="*70)

    print("\n[1/3] Terminating stale tunnel sessions...")
    kill_existing_tunnels()
    time.sleep(1)

    print("[2/3] Launching live tunnels for Backend (8000) and Dashboard (8501)...")
    results = {}

    api_thread = threading.Thread(
        target=start_tunnel, args=(8000, "FastAPI Backend", results), daemon=True
    )
    dash_thread = threading.Thread(
        target=start_tunnel, args=(8501, "Streamlit Dashboard", results), daemon=True
    )

    api_thread.start()
    time.sleep(0.5)
    dash_thread.start()

    # Wait until both URLs are acquired (up to 30s)
    deadline = time.time() + 30
    while time.time() < deadline:
        if "FastAPI Backend" in results and "Streamlit Dashboard" in results:
            break
        time.sleep(0.5)

    if "FastAPI Backend" in results and "Streamlit Dashboard" in results:
        print("\n[3/3] Synchronizing configurations...")
        update_system_configs(results)

        dash_url = results.get("Streamlit Dashboard", "")
        api_url = results.get("FastAPI Backend", "")

        print("\n" + "="*70)
        print("🎉  SYSTEM IS FULLY ACCESSIBLE REMOTELY 24/7:")
        print("="*70)
        print(f"  📊  DASHBOARD (Mobile/Tablet/PC) : {dash_url}")
        print(f"  ⚙️   BACKEND API GATEWAY         : {api_url}")
        print(f"  ☁️   STREAMLIT CLOUD URL         : https://piploci.streamlit.app")
        print("="*70)
        print("\nKeep this process running. Press Ctrl+C at any time to stop tunnels.\n")
    else:
        print("\n⚠️ Could not detect both tunnel URLs within 30s. Check your internet connection.\n")

    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        print("\n🔴 Tunnels stopped.")
        kill_existing_tunnels()
