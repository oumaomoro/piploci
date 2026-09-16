"""
Piploci Tunnel Launcher
Starts Cloudflare Quick Tunnels for both the FastAPI backend (port 8000)
and the Streamlit dashboard (port 8501), then prints the public URLs.
Run: python run_tunnels.py
"""

import subprocess
import threading
import re
import sys
import time

TUNNEL_REGEX = re.compile(r"https://[a-z0-9\-]+\.trycloudflare\.com")

def start_tunnel(port: int, label: str, results: dict):
    """Starts a cloudflared quick tunnel and captures the public URL."""
    cmd = ["cloudflared", "tunnel", "--url", f"http://localhost:{port}"]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    for line in proc.stdout:
        line = line.strip()
        match = TUNNEL_REGEX.search(line)
        if match:
            url = match.group(0)
            results[label] = url
            print(f"\n{'='*60}")
            print(f"  ✅  {label} TUNNEL LIVE")
            print(f"  🌐  {url}")
            print(f"{'='*60}\n")
            sys.stdout.flush()
        # Keep streaming so tunnel stays alive
    proc.wait()


if __name__ == "__main__":
    results = {}

    print("\n🚀  Starting Piploci Cloudflare Tunnels...\n")

    api_thread = threading.Thread(
        target=start_tunnel, args=(8000, "FastAPI Backend", results), daemon=True
    )
    dash_thread = threading.Thread(
        target=start_tunnel, args=(8501, "Streamlit Dashboard", results), daemon=True
    )

    api_thread.start()
    time.sleep(1)   # slight stagger so logs don't interleave
    dash_thread.start()

    # Wait until both URLs are found (up to 30s)
    deadline = time.time() + 30
    while time.time() < deadline:
        if "FastAPI Backend" in results and "Streamlit Dashboard" in results:
            break
        time.sleep(0.5)

    if results:
        print("\n📋  SUMMARY — Share these with your phone browser:\n")
        for label, url in results.items():
            print(f"  {label:25s}: {url}")
        print()
        if "FastAPI Backend" in results:
            api_url = results["FastAPI Backend"] + "/api/v1"
            print("  📌  Add to Streamlit Cloud Secrets (Settings → Secrets):")
            print(f'      API_BASE = "{api_url}"')
            print()
        print("  ℹ️   Tunnels will stay alive as long as this script runs.\n")
    else:
        print("\n⚠️  Could not detect tunnel URLs within 30s — check output above.\n")

    # Keep main thread alive so daemon tunnel threads keep running
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        print("\n🔴  Tunnels stopped.")
