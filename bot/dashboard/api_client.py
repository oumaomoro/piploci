"""
HTTP API Client for the Streamlit Monitoring Dashboard.
Manages JWT credentials, endpoint resolution, and resilient network calls.
"""

import os
import requests
import streamlit as st
from typing import Dict, Any, Optional
from config import API_PORT

LOCAL_API_PORT = API_PORT
_LOCAL_DEFAULT = f"http://127.0.0.1:{LOCAL_API_PORT}/api/v1"
_CLOUDFLARE_DEFAULT = "https://double-charts-lime-intent.trycloudflare.com/api/v1"


def get_api_base() -> str:
    """Resolves API base: prefers localhost when running locally, falls back to secrets/tunnel on cloud."""
    if "api_base_override" in st.session_state and st.session_state["api_base_override"]:
        return st.session_state["api_base_override"].rstrip("/")

    # 1. First priority for local development: check if the active API port is open locally
    import socket
    for host in ("127.0.0.1", "localhost"):
        try:
            socket.create_connection((host, LOCAL_API_PORT), timeout=0.15).close()
            return f"http://{host}:{LOCAL_API_PORT}/api/v1"
        except OSError:
            pass

    # 2. On Streamlit Cloud: check secrets
    try:
        if hasattr(st, "secrets") and "API_BASE" in st.secrets:
            secret_base = st.secrets["API_BASE"].rstrip("/")
            try:
                probe = requests.get(f"{secret_base}/status", timeout=1.5)
                if probe.ok:
                    return secret_base
            except requests.RequestException:
                pass
    except Exception:
        pass

    # 3. Check environment variable
    env_base = os.getenv("API_BASE")
    if env_base:
        return env_base.rstrip("/")

    # 4. Fallback to active Cloudflare tunnel
    return _CLOUDFLARE_DEFAULT


def get_token() -> Optional[str]:
    """Retrieves or refreshes admin bearer token."""
    if "jwt_token" in st.session_state and st.session_state["jwt_token"]:
        return st.session_state["jwt_token"]

    api_base = get_api_base()
    try:
        res = requests.post(
            f"{api_base}/auth/login-json",
            json={"username": "admin", "password": "AdminPass@2026"},
            timeout=2.5,
        )
        if res.status_code == 200:
            token = res.json().get("access_token")
            st.session_state["jwt_token"] = token
            return token
    except Exception:
        pass
    return None


def query_api(endpoint: str, method: str = "GET", payload: Optional[Dict[str, Any]] = None, timeout: float = 3.0) -> Optional[Any]:
    """Executes authenticated HTTP request to backend API."""
    api_base = get_api_base()
    url = f"{api_base}{endpoint}"
    token = get_token()
    headers = {"Authorization": f"Bearer {token}"} if token else {}

    try:
        if method == "GET":
            resp = requests.get(url, headers=headers, timeout=timeout)
        elif method == "POST":
            resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
        else:
            return None

        if resp.status_code == 200:
            return resp.json()
        elif resp.status_code == 401:
            st.session_state["jwt_token"] = None
    except Exception:
        pass
    return None


def fetch_telemetry(timeout: float = 3.5) -> Optional[Dict[str, Any]]:
    """
    Fetches the consolidated system telemetry bundle in a single fast round-trip.
    Falls back gracefully if the server is starting up or unreachable.
    """
    res = query_api("/telemetry", method="GET", timeout=timeout)
    if isinstance(res, dict) and "status" in res:
        return res
    return None


def send_command(endpoint: str, payload: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """Executes a command (like emergency stop or config update) and returns response dict."""
    return query_api(endpoint, method="POST", payload=payload or {}, timeout=5.0)
