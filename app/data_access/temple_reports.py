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


STATUSES = ("open", "resolved", "rejected")


def _row(item: "TempleReport") -> dict[str, Any]:
    return {"id": item.id, "temple": item.temple, "field": item.field, "note": item.note,
            "status": item.status, "created_at": item.created_at}


def list_open(limit: int = 50) -> list[dict[str, Any]]:
    with _session() as session:
        rows = session.execute(
            select(TempleReport).where(TempleReport.status == "open")
            .order_by(TempleReport.id.desc()).limit(max(1, min(int(limit), 200)))
        ).scalars().all()
    return [_row(r) for r in rows]


def list_reports(status: str = "", limit: int = 100) -> list[dict[str, Any]]:
    """按状态列出（空字符串＝全部）。"""
    statement = select(TempleReport).order_by(TempleReport.id.desc()).limit(max(1, min(int(limit), 500)))
    if status:
        if status not in STATUSES:
            raise ValueError(f"status must be one of {STATUSES}")
        statement = statement.where(TempleReport.status == status)
    with _session() as session:
        return [_row(r) for r in session.execute(statement).scalars().all()]


def set_status(report_id: int, status: str) -> dict[str, Any] | None:
    """标记处理结果：resolved（已改数据）/ rejected（核查后无问题）。"""
    if status not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}")
    with _session() as session:
        row = session.get(TempleReport, int(report_id))
        if row is None:
            return None
        row.status = status
        session.commit()
        return _row(row)


def counts() -> dict[str, int]:
    """按状态与寺庙聚合，供运营看板上看「哪座被报得最多」。"""
    with _session() as session:
        rows = session.execute(select(TempleReport)).scalars().all()
    by_status = {status: 0 for status in STATUSES}
    by_temple: dict[str, int] = {}
    for row in rows:
        by_status[row.status] = by_status.get(row.status, 0) + 1
        if row.status == "open":
            by_temple[row.temple] = by_temple.get(row.temple, 0) + 1
    return {"total": len(rows), **{f"status_{k}": v for k, v in by_status.items()},
            "by_temple": dict(sorted(by_temple.items(), key=lambda x: -x[1]))}


def clear_all() -> None:
    with _session() as session:
        session.query(TempleReport).delete()
        session.commit()


def reset_for_tests() -> None:
    global _Factory
    _Factory = None
