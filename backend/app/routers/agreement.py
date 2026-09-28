"""保障协议接口：维护保障协议，覆盖确认签订、到期提醒、续签留痕、终止协议等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.agreement import AgreementService

router = APIRouter(prefix="/api/agreement", tags=["保障协议"])

service = AgreementService()

LIST_FIELDS = ["协议编号", "服务单位", "保障项目", "协议金额", "服务期限", "签订人员", "到期日期", "协议状态", "到期提醒", "续签次数"]
STATUSES = ["待签订", "履行中", "已到期", "已终止"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按协议编号检索"),
    status: str | None = Query(default=None, description="待签订、履行中、已到期、已终止"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按协议编号与状态过滤保障协议列表；没有数据时返回空页，不报错。

    到期状态与到期提醒由后端按到期日期统一派生，列表、提醒、统计口径一致。
    """
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/summary")
def summary() -> dict[str, Any]:
    """列表页统计卡片：履行中、即将到期、已到期数量与协议总金额，口径与列表一致。"""
    return service.summary()


@router.get("/reminders")
def list_reminders() -> dict[str, Any]:
    """到期提醒清单：以后端到期日期为准，提前窗口内的“即将到期”和已到期都在这里。"""
    items = service.list_reminders()
    return {"items": items, "total": len(items)}


@router.get("/renewals")
def list_renewals() -> dict[str, Any]:
    """续签留痕清单：同一协议编号重复续签只保留最新一次。"""
    items = service.list_renewals()
    return {"items": items, "total": len(items)}


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出保障协议清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "agreement", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条保障协议明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"保障协议 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条保障协议，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="保障协议已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条保障协议执行确认签订、标记到期、终止协议；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/renew", response_model=ActionResult)
def renew_entry(entry_id: int, payload: EntryPayload) -> ActionResult:
    """确认续签：写入新的服务期限、协议金额、签订人员，并保留原到期日期与保障项目。

    服务单位空缺、服务期限早于签订日期等情况会被拒绝并说明原因；
    已终止协议不能续签，续签与终止两条路径互不覆盖。
    """
    entry, message = service.renew(entry_id, payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
