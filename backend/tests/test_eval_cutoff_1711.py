"""17.11.2026: Bewertungs-Stichtag nach den Fixes setzen (einmalig, nie zurück)."""
import asyncio

from services import boot_migrations as bm, evaluation_cutoff as ec
from tests.phase_fakedb import FakeDB


def _run(db):
    asyncio.run(bm.migrate_evaluation_cutoff_1711(db))
    return asyncio.run(ec.status(db))


def test_moves_earlier_cutoff_forward_once():
    db = FakeDB()
    asyncio.run(ec.set_since(db, "2026-11-15T21:00:00Z", by="migration"))
    st = _run(db)
    assert st["since"] == "2026-11-17T22:15:00+00:00" and st["set_by"] == "claude"
    # Trader stellt danach selbst um -> zweiter Start ändert nichts mehr
    asyncio.run(ec.set_since(db, "2026-11-16T00:00:00Z", by="trader"))
    assert _run(db)["since"] == "2026-11-16T00:00:00+00:00"


def test_keeps_later_cutoff_and_sets_missing():
    db = FakeDB()
    asyncio.run(ec.set_since(db, "2026-11-17T22:30:00Z", by="trader"))
    assert _run(db)["since"] == "2026-11-17T22:30:00+00:00"
    db2 = FakeDB()
    assert _run(db2)["since"] == "2026-11-17T22:15:00+00:00"
