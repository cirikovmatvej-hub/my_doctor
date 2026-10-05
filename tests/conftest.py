"""Shared fixtures. Tests point the DB layer at a throwaway file by assigning
database.db.DATABASE_PATH directly; restore it afterwards so one test's path
can never leak into the next."""
import pytest

import database.db as db


@pytest.fixture(autouse=True)
def _restore_database_path():
    original = db.DATABASE_PATH
    yield
    db.DATABASE_PATH = original
