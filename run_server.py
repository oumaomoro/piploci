"""
Convenience launcher for the Piploci FastAPI Server and WebSocket bridge.
Usage: python run_server.py
"""

import uvicorn

if __name__ == "__main__":
    uvicorn.run("bot.api.app:app", host="0.0.0.0", port=8000, reload=True)
