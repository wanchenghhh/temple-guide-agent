"""Private SQLite workspace for speculative node writes.

Tools retain read-your-writes and generated IDs without locking the live DB.
Only changed rows are applied after guards succeed. Concurrent changes to those
rows (including generated-ID collisions) fail closed instead of overwriting data.
Audit writers use their own engine and never enter this workspace.
"""

import threading
import uuid
from contextlib import contextmanager

from sqlalchemy import event, inspect
from app.data_access.session import ScopedSession

from app import db


from app.data_access.staging import (
    BusinessCommitFailure,
    workspace_rows as _rows,
    _apply,
    prepare_workspace,
    staged_row,
)

# A staging window spans one wrapped node: snapshot -> (LLM/tool work) -> apply.
# A background writer (the memory summary worker) that commits the same profile
# row inside that window makes the optimistic apply fail closed, which the user
# sees as a failed turn. The two sides therefore hand off through one condition:
#   * staging waits only for an in-flight background commit (milliseconds);
#   * a background commit waits for staging windows to close (seconds) and may
#     time out, in which case its own retry policy takes over.
_STAGING_DEPTH = 0
_BACKGROUND_WRITERS = 0
_STAGING_CV = threading.Condition()


def _enter_staging(timeout: float = 5.0) -> None:
    global _STAGING_DEPTH
    import time as _time

    with _STAGING_CV:
        if _STAGING_DEPTH == 0 and _BACKGROUND_WRITERS > 0:
            deadline = _time.monotonic() + max(0.0, timeout)
            while _BACKGROUND_WRITERS > 0:
                left = deadline - _time.monotonic()
                if left <= 0:
                    break
                _STAGING_CV.wait(min(left, 0.01))
        _STAGING_DEPTH += 1


def _leave_staging() -> None:
    global _STAGING_DEPTH
    with _STAGING_CV:
        _STAGING_DEPTH = max(0, _STAGING_DEPTH - 1)
        _STAGING_CV.notify_all()


def staging_active() -> int:
    with _STAGING_CV:
        return _STAGING_DEPTH


def wait_until_no_staging(timeout: float = 2.0) -> bool:
    """Block a background writer until no node staging window is open.

    Returns False on timeout: the caller then proceeds and may be dropped or
    retried by its own existing retry policy (never user-visible).
    """
    import time as _time

    deadline = _time.monotonic() + max(0.0, float(timeout))
    with _STAGING_CV:
        while _STAGING_DEPTH > 0:
            left = deadline - _time.monotonic()
            if left <= 0:
                return False
            _STAGING_CV.wait(min(left, 0.05))
    return True


@contextmanager
def background_write_window(timeout: float = 15.0):
    """Exclusive-with-staging window for a background profile writer.

    Holding it prevents a concurrently opened staging window from publishing a
    stale snapshot of the same rows. If staging does not close in time, the
    writer proceeds anyway (it commits its own fresh read, and the affected
    staging turn fails closed exactly as before).
    """
    global _BACKGROUND_WRITERS
    import time as _time

    deadline = _time.monotonic() + max(0.0, float(timeout))
    with _STAGING_CV:
        while _STAGING_DEPTH > 0:
            left = deadline - _time.monotonic()
            if left <= 0:
                break
            _STAGING_CV.wait(min(left, 0.05))
        # Registered while still holding the lock, so no staging window can
        # slip between the wait and the registration.
        _BACKGROUND_WRITERS += 1
    try:
        yield
    finally:
        with _STAGING_CV:
            _BACKGROUND_WRITERS = max(0, _BACKGROUND_WRITERS - 1)
            _STAGING_CV.notify_all()


def _track_changes(session, flush_context, instances):
    """只记录**本次会写**的行，不再整库前后各扫一遍。

    上一版在节点开始和结束各把业务库全表读进内存做 diff：
    本地 495 个用户时，一次对话因此慢了 14 秒。用户越多越慢，上线必炸。
    现在改成：在 flush 前，把要改的行的「原值」从暂存库读出来（此时还没写回），
    flush 后再读一次「新值」——开销只跟改动行数有关。
    """
    tracked = session.info.setdefault("staged_changes", {})
    engine_tables = session.info.setdefault("staged_tables", set())
    targets = list(session.new) + list(session.dirty) + list(session.deleted)
    for obj in targets:
        table = getattr(obj, "__table__", None)
        if table is None or table.name not in engine_tables:
            continue
        key = tuple(getattr(obj, column.key, None) for column in table.primary_key)
        if any(value is None for value in key):
            continue          # 主键尚未分配：等下一次 flush
        slot = (table.name, key)
        if slot in tracked:
            continue
        old = staged_row(session, table, key)
        tracked[slot] = (table, key, old)


def _collect_changes(session):
    """flush 之后把「新值」读回来，组成 (table, key, old, new) 列表。"""
    tracked = session.info.get("staged_changes") or {}
    changes = []
    for table, key, old in tracked.values():
        new = staged_row(session, table, key)
        if old != new:
            changes.append((table, key, old, new))
    tracked.clear()
    return changes


def _assign_insert_ids(session, flush_context, instances):
    # SQLite's snapshot-local MAX(id)+1 races independent inserts (including
    # background summaries). Allocate IDs before flush so returned IDs and
    # references stay valid when published. Keep integers exactly representable
    # by JSON/JavaScript consumers; the commit conflict check remains authoritative.
    for row in session.new:
        mapper = inspect(row).mapper
        column = mapper.local_table.autoincrement_column
        if column is not None and getattr(row, column.key) is None:
            setattr(row, column.key, (uuid.uuid4().int >> 76) or 1)


@contextmanager
def stage_business_writes():
    """Nest within the request's workspace; publish only at its outer boundary."""
    if db._memory_session.get() is not None:
        yield
        return

    if db.ENGINE.dialect.name == "postgresql":
        phase = "setup"
        try:
            with db.memory_transaction():
                phase = "body"
                yield
                phase = "finalization"
        except Exception as exc:
            if phase == "body":
                raise
            raise BusinessCommitFailure(f"business staging {phase} failed") from exc
        return

    # The window must cover the snapshot as well: a background commit that lands
    # between prepare_workspace() and registration would still make this apply
    # fail closed.
    _enter_staging()
    engine = None
    try:
        engine, tables = prepare_workspace()
        hooks = []
        table_names = {table.name for table in tables}
        with ScopedSession(engine, autoflush=False) as session:
            session.info["staged_tables"] = table_names
            # 先分配自增 id，再记录原值（否则新行没有主键，改不到）
            event.listen(session, "before_flush", _assign_insert_ids)
            event.listen(session, "before_flush", _track_changes)
            token = db._memory_session.set(session)
            htoken = db._after_commit.set(hooks)
            try:
                yield
                try:
                    session.flush()
                    changes = _collect_changes(session)
                except Exception as exc:
                    raise BusinessCommitFailure("business staging finalization failed") from exc
            finally:
                db._after_commit.reset(htoken)
                db._memory_session.reset(token)
        try:
            _apply(changes)
        except Exception as exc:
            raise BusinessCommitFailure("business commit failed") from exc
        for fn in hooks:
            try:
                fn()
            except Exception:
                db.logging.getLogger("app.db").warning("after-commit hook failed", exc_info=False)
    finally:
        _leave_staging()
        if engine is not None:
            engine.dispose()
