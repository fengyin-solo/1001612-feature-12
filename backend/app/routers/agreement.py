"""保障协议接口：维护保障协议，覆盖确认签订、标记到期、终止协议、到期提醒与确认续签。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.agreement import DEFAULT_REMIND_WINDOW, AgreementService

router = APIRouter(prefix="/api/agreement", tags=["保障协议"])

service = AgreementService()

LIST_FIELDS = ["协议编号", "服务单位", "保障项目", "协议金额", "服务期限", "签订人员", "到期日期", "协议状态"]
STATUSES = ["待签订", "履行中", "已到期", "已终止"]


def _window_param(remind_days: int) -> int:
    """提醒提前天数只允许合理范围，避免传入负数或超大值把口径搞乱。"""
    if 1 <= remind_days <= 365:
        return remind_days
    raise HTTPException(status_code=400, detail="提前提醒天数需在 1~365 之间")


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按协议编号检索"),
    status: str | None = Query(default=None, description="待签订、履行中、已到期、已终止"),
    reminding: bool = Query(default=False, description="为 true 时只看即将到期协议"),
    remind_days: int = Query(default=DEFAULT_REMIND_WINDOW, description="到期前提前提醒天数"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按协议编号、状态与到期提醒过滤保障协议；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    window = _window_param(remind_days)
    items, total = service.list_entries(
        keyword=keyword,
        status=status,
        reminding=reminding,
        window=window,
        page=page,
        size=size,
    )
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/reminders")
def list_reminders(
    remind_days: int = Query(default=DEFAULT_REMIND_WINDOW, description="到期前提前提醒天数"),
) -> dict[str, Any]:
    """即将到期提醒清单：以后端记录的到期日期为准，口径与列表筛选、统计卡片一致。"""
    window = _window_param(remind_days)
    items = service.list_reminders(window)
    return {"module": "agreement", "remind_days": window, "total": len(items), "items": items}


@router.get("/stats")
def stats(
    remind_days: int = Query(default=DEFAULT_REMIND_WINDOW, description="到期前提前提醒天数"),
) -> dict[str, Any]:
    """列表页统计卡：与表格使用同一提醒口径，翻页或筛选后数字仍对得上。"""
    return service.summary(_window_param(remind_days))


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


@router.post("/{entry_id}/renew", response_model=ActionResult)
def renew_entry(entry_id: int, payload: EntryPayload) -> ActionResult:
    """确认续签：写入新的服务期限、协议金额与签订人员，原到期日期与保障项目留痕。"""
    entry, message = service.renew_entry(entry_id, payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条保障协议执行确认签订、标记到期、终止协议；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出保障协议清单：返回与列表页同口径的全量数据（含提醒标记与续签次数）。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "agreement", "total": total, "items": items}
