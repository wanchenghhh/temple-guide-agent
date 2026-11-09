"""staging 的开销必须跟「改动行数」有关，而不是跟「库有多大」有关。

历史事故：节点开始和结束各把业务库全表读一遍做 diff，本地 495 个用户时
一次对话从 4 秒涨到 18 秒。这里用「大量无关行」把那个回归钉住：
库里有 3000 行无关数据时，按行读取的次数不应随之增长。
"""

import sqlite3

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.pool import StaticPool

from app import business_stage, data_access, db
from app.agent.memory.episodic import EpisodicEvent
from app.data_access.session import ScopedSession

OWNER = "bulk-user"


def _staged_engine(rows: int):
    """造一个含 rows 行无关数据的暂存库（模拟用户很多时的业务库）。"""
    private = sqlite3.connect(":memory:", check_same_thread=False)
    engine = create_engine("sqlite://", creator=lambda: private, poolclass=StaticPool)
    db.Base.metadata.create_all(bind=engine)
    with engine.begin() as connection:
        for index in range(rows):
            connection.execute(
                EpisodicEvent.__table__.insert().values(
                    id=index + 1, user_id=OWNER, kind="chat",
                    summary="unrelated", tags_json="[]", payload_json="{}"))
    return engine


def _session(engine):
    """和线上一致：变更跟踪挂在 before_flush 上，而不是手动调用。"""
    session = ScopedSession(engine, autoflush=False).__enter__()
    session.info["staged_tables"] = {EpisodicEvent.__table__.name}
    event.listen(session, "before_flush", business_stage._assign_insert_ids)
    event.listen(session, "before_flush", business_stage._track_changes)
    return session


def test_row_lookups_scale_with_changes_not_db_size(monkeypatch):
    """0 行 vs 3000 行无关数据：改动 1 行时按主键读取的次数一样。"""
    lookups = []
    real = business_stage.staged_row

    def counting(session, table, key):
        lookups.append(1)
        return real(session, table, key)

    monkeypatch.setattr(business_stage, "staged_row", counting)

    per_size = []
    with data_access.user_scope(OWNER):
        for bulk in (0, 3000):
            lookups.clear()
            engine = _staged_engine(bulk)
            session = _session(engine)
            session.add(EpisodicEvent(id=999001, user_id=OWNER, kind="chat",
                                      summary="new", tags_json="[]", payload_json="{}"))
            session.flush()
            changes = business_stage._collect_changes(session)
            assert len(changes) == 1
            per_size.append(len(lookups))
            session.close()
            engine.dispose()

    assert per_size[1] == per_size[0], f"库变大后读取次数变了：{per_size}"
    assert per_size[0] <= 4, f"单行改动不该产生多次读取：{per_size}"


def test_modification_records_before_and_after():
    """乐观校验靠 old/new 对比，两者都必须准确。"""
    engine = _staged_engine(10)
    with data_access.user_scope(OWNER):
        session = _session(engine)
        # 改的是「已存在」的行（id=1 由准备数据写入），这才是 update 而不是 insert
        row = session.get(EpisodicEvent, 1)
        row.summary = "changed"
        session.flush()
        changes = business_stage._collect_changes(session)
        session.close()
    engine.dispose()

    assert changes, "改动必须被记录"
    _, key, old, new = changes[0]
    assert key == (1,)
    assert old["summary"] == "unrelated" and new["summary"] == "changed"


def test_unchanged_rows_are_not_published():
    """只是读过的行不该进入变更列表，否则每轮都会覆盖别人刚写的数据。"""
    engine = _staged_engine(5)
    with data_access.user_scope(OWNER):
        session = _session(engine)
        session.get(EpisodicEvent, 1)      # 只读
        session.flush()
        assert business_stage._collect_changes(session) == []
        session.close()
    engine.dispose()


def test_deleted_rows_are_recorded_as_removal():
    engine = _staged_engine(3)
    with data_access.user_scope(OWNER):
        session = _session(engine)
        session.delete(session.get(EpisodicEvent, 1))
        session.flush()
        changes = business_stage._collect_changes(session)
        session.close()
    engine.dispose()

    assert len(changes) == 1
    _, key, old, new = changes[0]
    assert key == (1,) and old is not None and new is None


def test_tables_outside_the_business_set_are_ignored():
    """审计表走独立引擎，不能被业务事务顺带提交。"""
    engine = _staged_engine(2)
    with data_access.user_scope(OWNER):
        session = ScopedSession(engine, autoflush=False).__enter__()
        session.info["staged_tables"] = {"only_this_table"}
        event.listen(session, "before_flush", business_stage._track_changes)
        session.add(EpisodicEvent(id=999003, user_id=OWNER, kind="chat",
                                  summary="x", tags_json="[]", payload_json="{}"))
        session.flush()
        assert business_stage._collect_changes(session) == []
        session.close()
    engine.dispose()
