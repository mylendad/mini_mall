"""Юнит-тесты ретенции строк outbox (ADR-0001, п. 8)."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

from app.services.relay import _processed_cleanup_stmt, cleanup_outbox


def _now():
    return datetime(2026, 9, 20, 12, 0, 0, tzinfo=UTC)


def test_cleanup_stmt_targets_only_old_processed_rows():
    cutoff = _now() - timedelta(seconds=86400)
    stmt = _processed_cleanup_stmt(cutoff)
    sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "DELETE FROM index_outbox" in sql
    assert "status = 'processed'" in sql
    assert "processed_at <" in sql
    assert str(cutoff.replace(tzinfo=None)) in sql or str(cutoff) in sql


async def test_cleanup_outbox_executes_delete_with_retention_cutoff():
    db = AsyncMock()
    await cleanup_outbox(db, now=_now(), retention_seconds=86400)

    db.execute.assert_awaited_once()
    stmt = db.execute.call_args.args[0]
    sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "DELETE FROM index_outbox" in sql
    assert _now().isoformat() not in sql
    assert "2026-09-19 12:00:00" in sql  # cutoff UTC на сутки раньше


async def test_cleanup_outbox_disabled_when_retention_non_positive():
    db = AsyncMock()
    await cleanup_outbox(db, now=_now(), retention_seconds=0)
    db.execute.assert_not_awaited()
