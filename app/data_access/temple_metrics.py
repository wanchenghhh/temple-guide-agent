"""寺庙向导指标的存取层（独立审计库；不进入业务事务）。

放在 data_access 里，是因为业务代码不允许直接拿连接/会话：
领域模块只调用这里暴露的两个函数。
"""
from __future__ import annotations

import time
from typing import Any

from sqlalchemy import Column, Float, Integer, String, select
from sqlalchemy.orm import sessionmaker

from app.audit_db import AUDIT_ENGINE, ensure_audit_table
from app.db import Base


class TempleTurn(Base):
    __tablename__ = "temple_turn_metrics"

    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(Float, nullable=False, default=time.time)
    day = Column(String(10), nullable=False, index=True)
    kind = Column(String(32), nullable=False, default="")
    wish = Column(String(16), nullable=False, default="")
    candidates = Column(Integer, nullable=False, default=0)
    citation_ok = Column(Integer, nullable=False, default=1)
    degraded = Column(Integer, nullable=False, default=0)
    refused = Column(Integer, nullable=False, default=0)
    review_items = Column(Integer, nullable=False, default=0)
    latency_ms = Column(Integer, nullable=False, default=0)
    cost_units = Column(Float, nullable=False, default=0.0)


_Factory = None


def _session():
    global _Factory
    if _Factory is None:
        ensure_audit_table(TempleTurn.__table__)
        _Factory = sessionmaker(bind=AUDIT_ENGINE, expire_on_commit=False)
    return _Factory()


def add_turn(*, day: str, kind: str = "", wish: str = "", candidates: int = 0,
             citation_ok: bool = True, degraded: bool = False, refused: bool = False,
             review_items: int = 0, latency_ms: int = 0, cost_units: float = 0.0) -> None:
    with _session() as session:
        session.add(TempleTurn(
            day=day, kind=str(kind)[:32], wish=str(wish)[:16], candidates=int(candidates),
            citation_ok=1 if citation_ok else 0, degraded=1 if degraded else 0,
            refused=1 if refused else 0, review_items=int(review_items),
            latency_ms=int(latency_ms), cost_units=float(cost_units or 0.0),
        ))
        session.commit()


def turns_since(day_from: str) -> list[dict[str, Any]]:
    """返回某天之后的全部轮次（只含聚合字段，不含用户内容）。"""
    with _session() as session:
        rows = session.execute(
            select(TempleTurn.day, TempleTurn.kind, TempleTurn.wish, TempleTurn.candidates,
                   TempleTurn.citation_ok, TempleTurn.degraded, TempleTurn.refused,
                   TempleTurn.review_items, TempleTurn.latency_ms, TempleTurn.cost_units)
            .where(TempleTurn.day >= day_from)
            .order_by(TempleTurn.id)
        ).all()
    return [dict(row._mapping) for row in rows]


def clear_all() -> None:
    """清空指标表（仅测试/本地重置用）。"""
    with _session() as session:
        session.query(TempleTurn).delete()
        session.commit()


def reset_for_tests() -> None:
    global _Factory
    _Factory = None
