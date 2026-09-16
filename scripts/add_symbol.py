"""
scripts/add_symbol.py
Database Migration & Multi-Asset Seeding Helper.
Seeds new low-correlation pairs (e.g., EURUSD, GBPUSD) with unique Magic Numbers,
spread guards, session windows, and dynamic compounding tiering parameters
without manual SQL execution.
"""

import argparse
import logging
import sys
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

# Ensure parent directory is on sys.path
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from database import (
    SessionLocal,
    StrategyConfigModel,
    init_database,
    log_system_event,
    log_trading_log,
)
from config import ALLOWED_MAGIC_NUMBERS

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("AddSymbolScript")


DEFAULT_LOW_CORRELATION_PAIRS: List[Dict[str, Any]] = [
    {
        "symbol": "EURUSD",
        "magic": 100203,
        "max_spread": 15.0,
        "session_window": "09:00 - 17:30 EAT",
        "risk_percent": 1.0,
        "lot_type": "dynamic_atr",
        "scaling_tier_active": True,
        "tier1_threshold": 15.0,
        "tier2_threshold": 30.0,
    },
    {
        "symbol": "GBPUSD",
        "magic": 100204,
        "max_spread": 18.0,
        "session_window": "09:00 - 17:30 EAT",
        "risk_percent": 1.0,
        "lot_type": "dynamic_atr",
        "scaling_tier_active": True,
        "tier1_threshold": 15.0,
        "tier2_threshold": 30.0,
    },
]


def add_or_update_symbol(
    symbol: str,
    magic: int,
    max_spread: float = 15.0,
    session_window: str = "09:00 - 17:30 EAT",
    risk_percent: float = 1.0,
    lot_type: str = "dynamic_atr",
    active: bool = True,
    scaling_tier_active: bool = True,
    tier1_threshold: float = 15.0,
    tier2_threshold: float = 30.0,
) -> Dict[str, Any]:
    """
    Inserts or updates a symbol configuration in strategy_configs table.
    Enforces Magic Number uniqueness and validates parameters.
    """
    symbol = symbol.strip().upper()
    if not symbol:
        raise ValueError("Symbol cannot be empty.")

    if magic <= 0:
        raise ValueError("Magic Number must be a positive integer.")

    if not (0.1 <= risk_percent <= 5.0):
        raise ValueError("Risk percent must be between 0.1 and 5.0%.")

    if max_spread <= 0:
        raise ValueError("Max spread must be positive.")

    init_database()

    with SessionLocal() as db:
        # Check Magic Number collision with other symbols
        magic_conflict = db.query(StrategyConfigModel).filter(
            StrategyConfigModel.magic == magic,
            StrategyConfigModel.symbol != symbol,
        ).first()
        if magic_conflict:
            raise ValueError(
                f"Magic Number {magic} is already registered to symbol '{magic_conflict.symbol}'. "
                f"Magic numbers must be strictly unique."
            )

        existing = db.query(StrategyConfigModel).filter_by(symbol=symbol).first()
        if existing:
            existing.magic = magic
            existing.max_spread = max_spread
            existing.session_window = session_window
            existing.risk_percent = risk_percent
            existing.lot_type = lot_type
            existing.active = active
            existing.scaling_tier_active = scaling_tier_active
            existing.tier1_threshold = tier1_threshold
            existing.tier2_threshold = tier2_threshold
            existing.updated_at = datetime.now(timezone.utc)
            action = "UPDATED"
            config_data = existing.to_dict()
        else:
            new_cfg = StrategyConfigModel(
                symbol=symbol,
                magic=magic,
                max_spread=max_spread,
                session_window=session_window,
                risk_percent=risk_percent,
                lot_type=lot_type,
                active=active,
                scaling_tier_active=scaling_tier_active,
                tier1_threshold=tier1_threshold,
                tier2_threshold=tier2_threshold,
                updated_at=datetime.now(timezone.utc),
            )
            db.add(new_cfg)
            action = "INSERTED"
            db.flush()
            config_data = new_cfg.to_dict()

        db.commit()

        # Dynamically register magic number into allowed magic list in runtime
        if magic not in ALLOWED_MAGIC_NUMBERS:
            ALLOWED_MAGIC_NUMBERS.append(magic)

        msg = f"Symbol {symbol} {action} (Magic: {magic}, Spread: {max_spread}, Risk: {risk_percent}%, Tiering: {scaling_tier_active})"
        logger.info(msg)
        log_system_event("DatabaseMigration", msg)
        log_trading_log(symbol=symbol, message=msg, level="INFO")

        return {
            "status": "SUCCESS",
            "action": action,
            "symbol": symbol,
            "config": config_data,
        }


def seed_default_pairs() -> List[Dict[str, Any]]:
    """Seeds recommended low-correlation asset pairs (EURUSD, GBPUSD)."""
    results = []
    for pair in DEFAULT_LOW_CORRELATION_PAIRS:
        res = add_or_update_symbol(**pair)
        results.append(res)
    return results


def list_current_symbols() -> List[Dict[str, Any]]:
    """Lists all configured strategy symbols in the database."""
    init_database()
    with SessionLocal() as db:
        configs = db.query(StrategyConfigModel).all()
        return [c.to_dict() for c in configs]


def main():
    parser = argparse.ArgumentParser(
        description="Piploci Multi-Asset Database Migration & Seeding Helper",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--symbol", type=str, help="Asset symbol (e.g. EURUSD)")
    parser.add_argument("--magic", type=int, help="Unique Magic Number (e.g. 100203)")
    parser.add_argument("--spread", type=float, default=15.0, help="Maximum allowed spread points/pips")
    parser.add_argument("--session", type=str, default="09:00 - 17:30 EAT", help="Trading session window")
    parser.add_argument("--risk", type=float, default=1.0, help="Baseline risk percent (0.1 - 5.0)")
    parser.add_argument("--lot-type", type=str, default="dynamic_atr", help="Lot calculation model")
    parser.add_argument("--tier1", type=float, default=15.0, help="Tier 1 profit threshold %")
    parser.add_argument("--tier2", type=float, default=30.0, help="Tier 2 profit threshold %")
    parser.add_argument("--defaults", action="store_true", help="Seed default low-correlation pairs (EURUSD, GBPUSD)")
    parser.add_argument("--list", action="store_true", help="List all currently configured symbols")

    args = parser.parse_args()

    if args.list:
        symbols = list_current_symbols()
        print("\n=== Current Configured Assets ===")
        for s in symbols:
            print(f"• {s['symbol']:8s} | Magic: {s['magic']} | Risk: {s['risk_percent']}% | MaxSpread: {s['max_spread']} | Session: {s['session_window']}")
        return

    if args.symbol and args.magic:
        res = add_or_update_symbol(
            symbol=args.symbol,
            magic=args.magic,
            max_spread=args.spread,
            session_window=args.session,
            risk_percent=args.risk,
            lot_type=args.lot_type,
            tier1_threshold=args.tier1,
            tier2_threshold=args.tier2,
        )
        print(f"\n[OK] {res['action']}: {res['symbol']} (Magic: {res['config']['magic']})")
    else:
        # Default action: seed default low-correlation pairs
        print("\nSeeding default low-correlation pairs (EURUSD, GBPUSD)...")
        results = seed_default_pairs()
        for r in results:
            print(f"[OK] {r['action']}: {r['symbol']} (Magic: {r['config']['magic']})")

    # Display final table
    symbols = list_current_symbols()
    print("\n=== All Active Configured Assets ===")
    for s in symbols:
        active_str = "ACTIVE" if s.get("active") else "DISABLED"
        tier_str = f"Tiers: {s.get('tier1_threshold')}%, {s.get('tier2_threshold')}%" if s.get("scaling_tier_active") else "Tiers: OFF"
        print(f"• {s['symbol']:8s} | Magic: {s['magic']} | {active_str:8s} | Risk: {s['risk_percent']:.1f}% | {tier_str} | Spread: {s['max_spread']}")


if __name__ == "__main__":
    main()
