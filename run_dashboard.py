"""
Convenience launcher for the Piploci Streamlit Dashboard.
Usage: python run_dashboard.py
"""

import sys
import subprocess

if __name__ == "__main__":
    subprocess.run([sys.executable, "-m", "streamlit", "run", "bot/dashboard/app.py"])
