# Piploci

High-performance, fault-tolerant algorithmic trading system in Python connecting **MetaTrader 5 (MT5)**, **TradingView Technical Analysis** (`tradingview-ta`), and **Economic News Calendars** (Parse APIs) to execute trades on **XAUUSD (Gold)** and **USDJPY**, backed by a **FastAPI** middleware and a **Streamlit** monitoring dashboard.

---

## 1. System Architecture

```
+-----------------------------------------------------------------------+
|                        STREAMLIT DASHBOARD                            |
|      (Live Equity, Asset Toggles, Drawdown Gauge, Emergency Stop)     |
+-----------------------------------+-----------------------------------+
                                    | REST API / WebSockets
                                    v
+-----------------------------------+-----------------------------------+
|                           FASTAPI SERVER                              |
|   - JWT Auth       - System Controller      - SQLite Database Bridge  |
+-----------------------------------+-----------------------------------+
                                    | Async Background Loop
                                    v
+-----------------------------------+-----------------------------------+
|                        PYTHON TRADING ENGINE                          |
|                                                                       |
|  +--------------------+   +-------------------+   +----------------+  |
|  | Parse News Filter  |   | TradingView TA    |   | Risk Engine    |  |
|  | (Blackout Shield)  |   | (H1 + M15 Align)  |   | (Dynamic ATR)  |  |
|  +---------+----------+   +---------+---------+   +-------+--------+  |
|            |                        |                     |           |
|            +-------------------+----+---------------------+           |
|                                |                                      |
|                                v                                      |
|                   [ MT5 Execution Module ]                            |
|                   (Magic: 100201/100202)                              |
+--------------------------------+--------------------------------------+
                                 |
                                 v
+--------------------------------+--------------------------------------+
|                    METATRADER 5 TERMINAL / VPS                        |
+-----------------------------------------------------------------------+
```

---

## 2. Key Features

1. **Strict Magic Number Isolation:**
   - `100201`: **XAUUSD (Gold)**
   - `100202`: **USDJPY**
   - Manual positions (`magic = 0`) and other bots are strictly ignored and never modified or closed by the engine.
2. **Dynamic ATR Risk Engine:**
   - Lot size = `(Balance x Risk%) / (SL Distance x Tick Value)`
   - XAUUSD: SL = 1.5x ATR(14), TP = 3.5x ATR(14)
   - USDJPY: SL = 1.2x ATR(14), TP = 3.0x ATR(14)
3. **Daily Floating Drawdown Circuit Breaker:**
   - Monitors `starting_daily_balance - current_equity`.
   - At >= $4.50 USD drawdown: closes all bot positions and halts trading for 24 hours.
4. **Candle Reversal Rejection Ratio:**
   - Wick >= 55% of candle range for Gold; >= 45% for USDJPY.
5. **Multi-Timeframe Trend Consensus (TradingView TA):**
   - XAUUSD: STRONG_BUY/STRONG_SELL on M15 AND BUY/STRONG_BUY (or SELL/STRONG_SELL) on H1.
   - USDJPY: BUY/STRONG_BUY on both M15 and H1.
6. **Economic News Shield (Parse API):**
   - Pauses entries 30 minutes before and after high-impact USD/JPY news releases.
7. **Session Windows (EAT - UTC+3):**
   - XAUUSD: 15:30-19:30 EAT (London/NY Overlap).
   - USDJPY: 03:00-07:00 EAT (Tokyo Open) and 15:30-19:30 EAT (NY Overlap).
8. **Auto-Reconnection Heartbeat:**
   - Detects MT5 disconnects and reconnects gracefully with continuous terminal health polling.
9. **Streamlit Monitoring Dashboard:**
   - High-contrast terminal aesthetic: live equity, floating PnL, $4.50 drawdown gauge, asset status cards, active orders table, and Emergency Stop control.
   - Auto-refreshes every 5 seconds.

---

## 3. Installation & Setup

1. Navigate to the project directory:
   ```bash
   cd "Bot"
   ```
2. Create and activate a virtual environment:
   ```bash
   python -m venv venv
   .\venv\Scripts\Activate.ps1
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Configure environment variables:
   ```bash
   copy .env.example .env
   ```

---

## 4. Running the Backend & Trading Engine

```bash
python -m uvicorn server:app --host 0.0.0.0 --port 8000
```

- **API Docs:** `http://127.0.0.1:8000/docs`
- **Status:** `http://127.0.0.1:8000/api/v1/status`
- **WebSocket Feed:** `ws://127.0.0.1:8000/api/v1/ws/live-feed`

---

## 5. Running the Dashboard

```bash
python -m streamlit run dashboard.py --server.port 8501
```

- **Dashboard:** `http://localhost:8501`

---

## 6. Running Automated Tests

```bash
pytest test_modules.py -v
```

---

## 7. Project Structure

```
Bot/
├── config.py                 # System parameters, symbol configs, ATR multipliers & magic numbers
├── database.py               # SQLite ORM models, session manager & auto-seeding
├── news_filter.py            # Economic news shield & 30-min blackout buffers
├── tradingview_ta_module.py  # Multi-timeframe trend alignment analyzer
├── bot_engine.py             # MT5 execution core, ATR lot sizing & circuit breaker
├── server.py                 # FastAPI REST API & WebSocket broadcast bridge
├── dashboard.py              # Streamlit monitoring & control dashboard
├── test_modules.py           # Automated pytest validation suite
├── requirements.txt          # Python package dependencies
├── .env.example              # Environment variables template
└── README.md                 # System documentation & usage guide
```
