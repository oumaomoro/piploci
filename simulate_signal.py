"""
Live Signal & API Verification Script
Simulates a full execution cycle against the running FastAPI server.
"""
import json
import requests

BASE = "http://127.0.0.1:8000"

print("=" * 56)
print("  PIPLOCI - LIVE API VERIFICATION & SIGNAL SIMULATION")
print("=" * 56)

print("\n[1] Authenticating as admin...")
r = requests.post(
    f"{BASE}/api/v1/auth/login-json",
    json={"username": "admin", "password": "AdminPass@2026"},
)
assert r.status_code == 200, f"Auth failed: {r.text}"
token = r.json()["access_token"]
print(f"    Token acquired: {token[:50]}...")
headers = {"Authorization": f"Bearer {token}"}

print("\n[2] System Health Status:")
r = requests.get(f"{BASE}/api/v1/status")
s = r.json()
print(f"    state             : {s.get('status')}")
print(f"    terminal_connected: {s.get('terminal_connected')}")
bal = s.get("balance", 0)
eq = s.get("equity", 0)
dd = s.get("current_drawdown", 0)
ddl = s.get("daily_drawdown_limit", 0)
print(f"    balance           : ${bal:.2f}")
print(f"    equity            : ${eq:.2f}")
print(f"    daily_drawdown    : ${dd:.2f} / ${ddl:.2f}")
print(f"    circuit_breaker   : {s.get('circuit_breaker_active')}")

print("\n[3] DB-Backed Strategy Configs (Supabase/SQLite):")
r = requests.get(f"{BASE}/api/v1/configs")
for c in r.json():
    print(f"    {c['symbol']}: active={c['active']} | magic={c['magic_number']} | max_spread={c['max_spread']}")

print("\n[4] Live Market Signals:")
r = requests.get(f"{BASE}/api/v1/signals")
for sym, data in r.json().items():
    sig = data.get("signal", {})
    sig_str = sig if isinstance(sig, str) else str(sig)
    print(f"    {sym}: signal={sig_str} | blackout={data.get('news_blackout')} | session={data.get('session_active')}")

print("\n[5] JWT-Protected Control Toggle:")
r = requests.post(f"{BASE}/api/v1/control/toggle", json={"symbol": "XAUUSD", "active": False}, headers=headers)
print(f"    PAUSE  -> HTTP {r.status_code} | {r.json().get('message', r.text)}")
assert r.status_code == 200
r = requests.post(f"{BASE}/api/v1/control/toggle", json={"symbol": "XAUUSD", "active": True}, headers=headers)
print(f"    RESUME -> HTTP {r.status_code} | {r.json().get('message', r.text)}")
assert r.status_code == 200

print("\n[6] Unauthenticated Rejection Check:")
r = requests.post(f"{BASE}/api/v1/control/emergency-stop")
print(f"    No-token emergency-stop -> HTTP {r.status_code} (EXPECTED 401)")
assert r.status_code == 401

print("\n[7] Auth Emergency Stop + Resume Cycle:")
r = requests.post(f"{BASE}/api/v1/control/emergency-stop", headers=headers)
print(f"    Stop   -> HTTP {r.status_code} | state={r.json().get('status')}")
assert r.status_code == 200 and r.json().get("status") == "HALTED"
r = requests.post(f"{BASE}/api/v1/control/resume", headers=headers)
print(f"    Resume -> HTTP {r.status_code} | state={r.json().get('status')}")
assert r.status_code == 200 and r.json().get("status") == "RUNNING"

print("\n[8] Open Bot Positions:")
r = requests.get(f"{BASE}/api/v1/positions")
positions = r.json()
if positions:
    for p in positions:
        print(f"    #{p['ticket']} {p['symbol']} {p['type']} {p['volume']}L @ {p['price_open']}")
else:
    print("    No open bot positions (MT5 offline / no active trades)")

print()
print("=" * 56)
print("  ALL CHECKS PASSED - SYSTEM FULLY OPERATIONAL")
print("=" * 56)
