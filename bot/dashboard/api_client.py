"""
HTTP API Client for the Streamlit Monitoring Dashboard.
Manages JWT credentials, endpoint resolution, and resilient network calls.
"""

import os
import requests
import streamlit as st
from typing import Dict, Any, Optional

_LOCAL_DEFAULT = "http://127.0.0.1:8000/api/v1"
_CLOUDFLARE_DEFAULT = "https://badge-voltage-mia-father.trycloudflare.com/api/v1"


def get_api_base() -> str:
    """Resolves API base from Streamlit session state, secrets, environment, or localhost default."""
    if "api_base_override" in st.session_state and st.session_state["api_base_override"]:
        return st.session_state["api_base_override"].rstrip("/")

    try:
        if hasattr(st, "secrets") and "API_BASE" in st.secrets:
            return st.secrets["API_BASE"].rstrip("/")
    except Exception:
        pass

    env_base = os.getenv("API_BASE")
    if env_base:
        return env_base.rstrip("/")

    # Default to local server if running
    return _LOCAL_DEFAULT


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
