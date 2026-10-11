"""
Chien de garde de la boucle asyncio (diagnostic, activé par LOOP_WATCHDOG=1).

Une tâche met à jour un battement toutes les 250 ms ; un thread vérifie ce battement : si la boucle est restée
bloquée plus de `LOOP_WATCHDOG_S` secondes (appel synchrone trop long, verrou SQLite…), il écrit dans le journal
la pile de tous les threads. Sert à trouver ce qui fige le simulateur, les agents et les WebSockets.
"""

from __future__ import annotations

import asyncio
import faulthandler
import logging
import sys
import threading
import time

logger = logging.getLogger("hackcure.watchdog")
_beat = time.monotonic()
_reported: set[int] = set()
_open_tx: dict[int, tuple[float, str]] = {}  # connexion → (début de la transaction d'écriture, pile d'appel)


def track_transactions(engine) -> None:
    """Mémorise qui a ouvert chaque transaction (BEGIN) : permet de voir quelle transaction garde le verrou SQLite."""
    import traceback

    from sqlalchemy import event

    @event.listens_for(engine, "begin")
    def _begin(conn):
        frames = [f"{f.filename.split('dashboard')[-1]}:{f.lineno} {f.name}" for f in traceback.extract_stack()[:-1] if "app" in f.filename and "watchdog" not in f.filename]
        _open_tx[id(conn)] = (time.monotonic(), " < ".join(frames[-5:]))

    @event.listens_for(engine, "commit")
    @event.listens_for(engine, "rollback")
    def _end(conn):
        _open_tx.pop(id(conn), None)
        _reported.discard(id(conn))


async def _heartbeat() -> None:
    global _beat
    while True:
        _beat = time.monotonic()
        await asyncio.sleep(0.25)


def _watch(threshold: float) -> None:
    last_report = 0.0
    while True:
        time.sleep(0.5)
        lag = time.monotonic() - _beat
        for key, (started, where) in list(_open_tx.items()):  # une transaction d'écriture ne doit durer que quelques millisecondes
            if time.monotonic() - started > 1.0 and key not in _reported:
                _reported.add(key)
                logger.warning("Transaction ouverte depuis %.1f s (verrou SQLite possible) : %s", time.monotonic() - started, where)
        if lag > threshold and time.monotonic() - last_report > 5.0:
            last_report = time.monotonic()
            logger.warning("Boucle asyncio bloquée depuis %.1f s — pile des threads :", lag)
            now = time.monotonic()
            for started, where in list(_open_tx.values()):
                if now - started > 0.5:
                    logger.warning("  transaction ouverte depuis %.1f s : %s", now - started, where)
            faulthandler.dump_traceback(file=sys.stderr, all_threads=True)


async def start(threshold: float = 1.5) -> list[asyncio.Task]:
    from .db import engine

    track_transactions(engine)
    threading.Thread(target=_watch, args=(threshold,), name="loop-watchdog", daemon=True).start()
    return [asyncio.create_task(_heartbeat(), name="loop-heartbeat")]
