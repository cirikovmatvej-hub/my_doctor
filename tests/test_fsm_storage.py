"""
Regression tests for database/fsm_storage.py — the SQLite-backed FSM storage
that replaced aiogram's MemoryStorage (which loses all state on every
process restart, i.e. every deploy — verified live as the cause of a
mid-consultation context loss). No pytest-asyncio dependency: each test just
drives its own asyncio.run(), matching this suite's synchronous style.
"""
import asyncio

import database.db as db
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.base import StorageKey
from database.fsm_storage import SQLiteStorage


class _States(StatesGroup):
    active = State()


def _make_storage(tmp_path, name="fsm_test.db"):
    db.DATABASE_PATH = str(tmp_path / name)
    return SQLiteStorage()


def test_fresh_key_has_no_state_and_empty_data(tmp_path):
    storage = _make_storage(tmp_path)
    key = StorageKey(bot_id=1, chat_id=100, user_id=200)

    async def run():
        await storage.init()
        assert await storage.get_state(key) is None
        assert await storage.get_data(key) == {}

    asyncio.run(run())


def test_set_state_accepts_a_real_state_object(tmp_path):
    storage = _make_storage(tmp_path)
    key = StorageKey(bot_id=1, chat_id=100, user_id=200)

    async def run():
        await storage.init()
        await storage.set_state(key, _States.active)
        assert await storage.get_state(key) == "_States:active"
        await storage.set_state(key, None)
        assert await storage.get_state(key) is None

    asyncio.run(run())


def test_data_round_trips_including_nested_lists(tmp_path):
    """messages (list[dict]) is exactly what handlers/consultation.py stores
    for the AI conversation history — the thing that was silently lost."""
    storage = _make_storage(tmp_path)
    key = StorageKey(bot_id=1, chat_id=100, user_id=200)
    data = {
        "messages": [{"role": "user", "content": "болит голова"}],
        "question_count": 1,
        "session_id": None,
    }

    async def run():
        await storage.init()
        await storage.set_data(key, data)
        assert await storage.get_data(key) == data

    asyncio.run(run())


def test_setting_state_does_not_clobber_data_and_vice_versa(tmp_path):
    storage = _make_storage(tmp_path)
    key = StorageKey(bot_id=1, chat_id=100, user_id=200)

    async def run():
        await storage.init()
        await storage.set_state(key, _States.active)
        await storage.set_data(key, {"question_count": 2})
        assert await storage.get_state(key) == "_States:active"
        assert await storage.get_data(key) == {"question_count": 2}

    asyncio.run(run())


def test_update_data_merges_like_dict_update(tmp_path):
    storage = _make_storage(tmp_path)
    key = StorageKey(bot_id=1, chat_id=100, user_id=200)

    async def run():
        await storage.init()
        await storage.set_data(key, {"messages": [], "question_count": 2})
        merged = await storage.update_data(key, {"question_count": 3})
        assert merged == {"messages": [], "question_count": 3}

    asyncio.run(run())


def test_different_keys_are_isolated(tmp_path):
    storage = _make_storage(tmp_path)
    key1 = StorageKey(bot_id=1, chat_id=100, user_id=200)
    key2 = StorageKey(bot_id=1, chat_id=999, user_id=999)

    async def run():
        await storage.init()
        await storage.set_data(key1, {"question_count": 5})
        await storage.set_state(key1, _States.active)
        assert await storage.get_data(key2) == {}
        assert await storage.get_state(key2) is None

    asyncio.run(run())


def test_clearing_data_with_no_state_drops_the_row(tmp_path):
    """state.clear() calls set_state(key, None) then set_data(key, {}) — the
    row should be deleted rather than left behind forever, otherwise
    fsm_storage grows without bound over the life of the bot."""
    storage = _make_storage(tmp_path)
    key = StorageKey(bot_id=1, chat_id=100, user_id=200)

    async def run():
        await storage.init()
        await storage.set_state(key, _States.active)
        await storage.set_data(key, {"question_count": 1})
        await storage.set_state(key, None)
        await storage.set_data(key, {})

        async with db._connect() as conn:
            async with conn.execute(
                "SELECT COUNT(*) FROM fsm_storage WHERE key=?", (
                    ":".join(str(p) for p in (key.bot_id, key.chat_id, key.user_id, key.thread_id, key.business_connection_id, key.destiny)),
                )
            ) as cur:
                row = await cur.fetchone()
        assert row[0] == 0

    asyncio.run(run())


def test_clearing_data_while_state_still_active_keeps_the_row(tmp_path):
    """Emptying data without clearing state (a valid mid-flow reset) must not
    delete the row — the active state still needs to persist."""
    storage = _make_storage(tmp_path)
    key = StorageKey(bot_id=1, chat_id=100, user_id=200)

    async def run():
        await storage.init()
        await storage.set_state(key, _States.active)
        await storage.set_data(key, {"question_count": 1})
        await storage.set_data(key, {})
        assert await storage.get_state(key) == "_States:active"
        assert await storage.get_data(key) == {}

    asyncio.run(run())


def test_update_data_is_atomic_under_concurrent_calls(tmp_path):
    """Regression for the lost-update race in BaseStorage's default
    get->merge->set: two concurrent update_data() calls on the same key must
    both land, not clobber each other."""
    storage = _make_storage(tmp_path)
    key = StorageKey(bot_id=1, chat_id=100, user_id=200)

    async def run():
        await storage.init()
        await storage.set_data(key, {})
        await asyncio.gather(
            storage.update_data(key, {"a": 1}),
            storage.update_data(key, {"b": 2}),
        )
        final = await storage.get_data(key)
        assert final == {"a": 1, "b": 2}

    asyncio.run(run())


def test_data_survives_a_simulated_process_restart(tmp_path):
    """The entire point of this module: a fresh SQLiteStorage instance
    (standing in for the process restarting on deploy) pointed at the same
    DB file must see data an earlier instance wrote."""
    key = StorageKey(bot_id=1, chat_id=100, user_id=200)
    db_path = str(tmp_path / "fsm_restart.db")

    async def run():
        db.DATABASE_PATH = db_path
        storage1 = SQLiteStorage()
        await storage1.init()
        await storage1.set_state(key, _States.active)
        await storage1.set_data(key, {"messages": [{"role": "user", "content": "тест"}]})

        storage2 = SQLiteStorage()  # simulates the restarted process
        await storage2.init()
        assert await storage2.get_state(key) == "_States:active"
        assert await storage2.get_data(key) == {"messages": [{"role": "user", "content": "тест"}]}

    asyncio.run(run())
