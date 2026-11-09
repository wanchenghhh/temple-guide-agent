"""Users endpoints; every operation uses the existing harness dependencies."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from app.agent.harness.admin import ALL_SCOPES, AdminPrincipal, AuditedAdminRoute, require_scope
from app.admin import users
from app.admin.models import AdminChangeLog
from app.admin.store import session

router = APIRouter(prefix="/api/admin", tags=["admin"], route_class=AuditedAdminRoute)


@router.get("/me")
def me(principal: AdminPrincipal = Depends(require_scope(""))):
    return {"principal": principal.name, "scopes": sorted(principal.scopes), "available_scopes": ALL_SCOPES}


@router.get("/users", dependencies=[Depends(require_scope("users:read"))])
def user_list(q: str = Query("", max_length=128), disabled: bool | None = None,
              limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    return users.list_users(q, disabled, limit, offset)


@router.get("/schedules", dependencies=[Depends(require_scope("users:read"))])
def schedules(user_id: str | None = None, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    from app.agent.schedules.models import Schedule
    from app.agent.schedules.service import serialize
    with session() as s:
        query = select(Schedule).where(Schedule.status != 'deleted')
        if user_id is not None:
            query = query.where(Schedule.user_id == user_id)
        # Operations metadata only: no prompts, names or private output bodies.
        fields = {'id', 'user_id', 'job_kind', 'enabled', 'status', 'paused_by_idle',
                  'next_run_at', 'last_run_at', 'last_status', 'run_count', 'success_count', 'fail_count'}
        return {'items': [{k: v for k, v in serialize(row).items() if k in fields}
                          for row in s.scalars(query.order_by(Schedule.id).offset(offset).limit(limit))]}


@router.get("/users/{user_id}", dependencies=[Depends(require_scope("users:read"))])
def user_detail(user_id: str, reveal: bool = False):
    return users.detail(user_id, reveal)


@router.post("/users/{user_id}/disable")
def disable(user_id: str, principal: AdminPrincipal = Depends(require_scope("users:write"))):
    return users.set_disabled(user_id, True, principal)


@router.post("/users/{user_id}/enable")
def enable(user_id: str, principal: AdminPrincipal = Depends(require_scope("users:write"))):
    return users.set_disabled(user_id, False, principal)


@router.get("/changes", dependencies=[Depends(require_scope("audit:read"))])
def changes(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    with session() as s:
        return {"items": [{c.name: getattr(row, c.name) for c in AdminChangeLog.__table__.columns}
                          for row in s.scalars(select(AdminChangeLog).order_by(
                              AdminChangeLog.id.desc()).offset(offset).limit(limit))]}


@router.get("/temple/reports", dependencies=[Depends(require_scope("users:read"))])
def temple_reports(limit: int = 50, status: str = "open"):
    """用户提交的资料纠错（不含任何身份信息）。status 为空则返回全部。"""
    from app.data_access import temple_reports as store

    return {"items": store.list_reports(status, limit), "counts": store.counts()}


@router.post("/temple/reports/{report_id}/status")
def temple_report_status(report_id: int, status: str,
                         principal: AdminPrincipal = Depends(require_scope("users:write"))):
    """标记处理结果：resolved / rejected（不改数据，只记状态）。"""
    from app.data_access import temple_reports as store

    row = store.set_status(report_id, status)
    if row is None:
        raise HTTPException(404, "报告不存在")
    return {"item": row, "counts": store.counts()}


@router.get("/temple/metrics", dependencies=[Depends(require_scope("users:read"))])
def temple_metrics(days: int = 7):
    """寺庙向导的领域指标（只给聚合值，不含任何用户内容）。"""
    from app.agent import temple_metrics as metrics

    return metrics.summary(max(1, min(int(days), 90))).as_dict()
