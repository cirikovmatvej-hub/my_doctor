"""
SQLite-backed FSM storage — survives bot restarts (deploys), unlike
aiogram's default MemoryStorage, whose own docstring warns "you will lose
all data when your bot restarts". Verified live: a deploy landing mid-
consultation wiped the in-progress chat history, and the model then
answered as if nothing had been said yet ("вы не упоминали никаких
симптомов") — every active multi-step flow (AI consultation, tracker setup,
family-member form, diary entry) is exposed to this, not just consultation.

Reuses the same SQLite file and connection helper as database/db.py (same
busy_timeout handling for concurrent access from both the bot and the
FastAPI backend) — this is just one more table in the same database, not a
new piece of infrastructure like Redis would be.
"""
import json
from typing import Any

from aiogram.fsm.state import State
from aiogram.fsm.storage.base import BaseStorage, StorageKey

from database.db import _connect


def _key_str(key: StorageKey) -> str:
    return ":".join(str(p) for p in (
        key.bot_id, key.chat_id, key.user_id,
        key.thread_id, key.business_connection_id, key.destiny,
    ))


class SQLiteStorage(BaseStorage):
    async def init(self) -> None:
        async with _connect() as db:
            await db.execute(
                "CREATE TABLE IF NOT EXISTS fsm_storage ("
                "key TEXT PRIMARY KEY, state TEXT, data TEXT NOT NULL DEFAULT '{}')"
            )
            await db.commit()

    async def set_state(self, key: StorageKey, state: Any = None) -> None:
        state_str = state.state if isinstance(state, State) else state
        async with _connect() as db:
            await db.execute(
                "INSERT INTO fsm_storage (key, state, data) VALUES (?, ?, '{}') "
                "ON CONFLICT(key) DO UPDATE SET state=excluded.state",
                (_key_str(key), state_str),
            )
            await db.commit()

    async def get_state(self, key: StorageKey) -> str | None:
        async with _connect() as db:
            async with db.execute(
                "SELECT state FROM fsm_storage WHERE key=?", (_key_str(key),)
            ) as cur:
                row = await cur.fetchone()
        return row[0] if row else None

    async def set_data(self, key: StorageKey, data: dict[str, Any]) -> None:
        key_str = _key_str(key)
        async with _connect() as db:
            await db.execute(
                "INSERT INTO fsm_storage (key, state, data) VALUES (?, NULL, ?) "
                "ON CONFLICT(key) DO UPDATE SET data=excluded.data",
                (key_str, json.dumps(data, ensure_ascii=False)),
            )
            if not data:
                # Mirrors a state.clear() row (state=NULL, data='{}') so the
                # table doesn't grow forever with dead entries. A row that
                # still has a state keeps its (now-empty) data instead.
                await db.execute(
                    "DELETE FROM fsm_storage WHERE key=? AND state IS NULL", (key_str,)
                )
            await db.commit()

    async def get_data(self, key: StorageKey) -> dict[str, Any]:
        async with _connect() as db:
            async with db.execute(
                "SELECT data FROM fsm_storage WHERE key=?", (_key_str(key),)
            ) as cur:
                row = await cur.fetchone()
        return json.loads(row[0]) if row and row[0] else {}

    async def update_data(self, key: StorageKey, data: dict[str, Any]) -> dict[str, Any]:
        # Overrides BaseStorage's default get→merge→set (three independent
        # calls, no locking) which can lose an update when two updates for
        # the same chat race (e.g. a double-tap firing two callbacks close
        # together). BEGIN IMMEDIATE takes the write lock up front so a
        # concurrent update_data on the same key serializes instead of
        # clobbering this one.
        key_str = _key_str(key)
        async with _connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            async with db.execute(
                "SELECT data FROM fsm_storage WHERE key=?", (key_str,)
            ) as cur:
                row = await cur.fetchone()
            current = json.loads(row[0]) if row and row[0] else {}
            current.update(data)
            await db.execute(
                "INSERT INTO fsm_storage (key, state, data) VALUES (?, NULL, ?) "
                "ON CONFLICT(key) DO UPDATE SET data=excluded.data",
                (key_str, json.dumps(current, ensure_ascii=False)),
            )
            await db.commit()
        return current

    async def close(self) -> None:
        pass  # no persistent connection held open — each call opens/closes its own
