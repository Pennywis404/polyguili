"""
Persistance JSON — remplace SQLite.
Sauvegarde atomique de l'etat du bot dans un fichier JSON.
"""
import asyncio
import json
import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.core.models import Opportunity, PaperTrade, PortfolioState

logger = logging.getLogger(__name__)

STATE_VERSION = 1


def save_state(
    path: str,
    portfolio: PortfolioState,
    trades: dict[str, PaperTrade],
    opportunities: list,
) -> None:
    """Sauvegarde atomique de l'etat dans un fichier JSON."""
    state = {
        "version": STATE_VERSION,
        "saved_at": datetime.utcnow().isoformat(),
        "portfolio": portfolio.to_dict(),
        "trades": {tid: t.to_dict() for tid, t in trades.items()},
        "opportunities": [
            o.to_dict() if hasattr(o, "to_dict") else o
            for o in list(opportunities)[-100:]  # Garder les 100 dernieres
        ],
    }

    filepath = Path(path)
    filepath.parent.mkdir(parents=True, exist_ok=True)

    # Ecriture atomique : ecrire dans un fichier temporaire puis renommer
    fd, tmp_path = tempfile.mkstemp(dir=filepath.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(state, f, indent=2, default=str)
        os.replace(tmp_path, filepath)
        logger.debug("State saved to %s", path)
    except Exception:
        # Nettoyer le fichier temporaire en cas d'erreur
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def load_state(
    path: str,
    default_capital: float = 10000.0,
) -> tuple[PortfolioState, dict[str, PaperTrade], list[Opportunity]]:
    """Charge l'etat depuis un fichier JSON. Retourne les valeurs par defaut si le fichier n'existe pas."""
    filepath = Path(path)

    if not filepath.exists():
        logger.info("No state file found at %s, starting fresh", path)
        return PortfolioState(initial_capital=default_capital, current_capital=default_capital), {}, []

    try:
        with open(filepath) as f:
            data = json.load(f)

        portfolio = PortfolioState.from_dict(data["portfolio"])

        trades: dict[str, PaperTrade] = {}
        for tid, tdata in data.get("trades", {}).items():
            try:
                trades[tid] = PaperTrade.from_dict(tdata)
            except Exception as e:
                logger.warning("Failed to load trade %s: %s", tid, e)

        opportunities: list[Opportunity] = []
        for odata in data.get("opportunities", []):
            try:
                opportunities.append(Opportunity.from_dict(odata))
            except Exception as e:
                logger.warning("Failed to load opportunity: %s", e)

        logger.info(
            "State loaded: capital=$%.2f, %d trades, %d opportunities",
            portfolio.current_capital,
            len(trades),
            len(opportunities),
        )
        return portfolio, trades, opportunities

    except (json.JSONDecodeError, KeyError, TypeError) as e:
        logger.error("Corrupted state file %s: %s — starting fresh", path, e)
        return PortfolioState(initial_capital=default_capital, current_capital=default_capital), {}, []


async def auto_save_loop(
    path: str,
    portfolio: PortfolioState,
    trades: dict[str, PaperTrade],
    opportunities: list,
    interval: int = 60,
) -> None:
    """Tache asyncio qui sauvegarde l'etat periodiquement."""
    logger.info("Auto-save loop started (every %ds to %s)", interval, path)
    while True:
        await asyncio.sleep(interval)
        try:
            save_state(path, portfolio, trades, opportunities)
        except Exception as e:
            logger.error("Auto-save failed: %s", e)
