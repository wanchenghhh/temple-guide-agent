"""资料纠错报告：用户说「这条资料不对」时存下来，供运营处理。

只存必要字段：哪座寺、哪个字段、用户描述（截断）、时间。
不存用户 id（不需要追溯个人），只存一个不可逆的短哈希用于去重。
"""
from __future__ import annotations

import hashlib
import time
from typing import Any

from sqlalchemy import Column, Float, Integer, String, Text, select
from sqlalchemy.orm import sessionmaker

from app.audit_db import AUDIT_ENGINE, ensure_audit_table
from app.db import Base


class TempleReport(Base):
    __tablename__ = "temple_data_reports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(Float, nullable=False, default=time.time)
    temple = Column(String(64), nullable=False, default="")
    field = Column(String(32), nullable=False, default="")
    note = Column(Text, nullable=False, default="")
    dedupe = Column(String(32), nullable=False, default="", index=True)
    status = Column(String(16), nullable=False, default="open")


_Factory = None


def _session():
    global _Factory
    if _Factory is None:
        ensure_audit_table(TempleReport.__table__)
        _Factory = sessionmaker(bind=AUDIT_ENGINE, expire_on_commit=False)
    return _Factory()


def _dedupe(temple: str, field: str, note: str) -> str:
    raw = f"{temple}|{field}|{note}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:32]


def add(temple: str, field: str, note: str) -> dict[str, Any]:
    """重复提交同一条不再累加（避免刷屏）。"""
    key = _dedupe(temple, field, note)
    with _session() as session:
        existing = session.execute(
            select(TempleReport).where(TempleReport.dedupe == key)).scalars().first()
        if existing is not None:
            return {"id": existing.id, "duplicate": True}
        row = TempleReport(temple=str(temple)[:64], field=str(field)[:32],
                           note=str(note)[:500], dedupe=key)
        session.add(row)
        session.commit()
        return {"id": row.id, "duplicate": False}


def list_open(limit: int = 50) -> list[dict[str, Any]]:
    with _session() as session:
        rows = session.execute(
            select(TempleReport).where(TempleReport.status == "open")
            .order_by(TempleReport.id.desc()).limit(max(1, min(int(limit), 200)))
        ).scalars().all()
    return [{"id": r.id, "temple": r.temple, "field": r.field, "note": r.note,
             "created_at": r.created_at} for r in rows]


def clear_all() -> None:
    with _session() as session:
        session.query(TempleReport).delete()
        session.commit()


def reset_for_tests() -> None:
    global _Factory
    _Factory = None
