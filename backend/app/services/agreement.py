"""保障协议业务规则：到期提醒、续签留痕、状态流转与字段校验都收在这里。

提醒口径只有一个事实来源：以后端存储的「到期日期」对今天做差，
列表、提醒接口与统计卡片都调用同一套计算，避免各处各算、对不上账。
"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.store import store

MODULE = "agreement"
REQUIRED_FIELDS = ["协议编号", "服务单位", "保障项目"]
STATUS_ORDER = ["待签订", "履行中", "已到期", "已终止"]
ACTION_RULES = {"确认签订": "履行中", "标记到期": "已到期", "终止协议": "已终止"}
NEGATIVE_ACTIONS = []

DEFAULT_REMIND_WINDOW = 30  # 到期前 30 天起进入「即将到期」提醒
# 待签订还没有生效、已终止不再合作，这两类不参与到期提醒
REMIND_SILENT_STATUSES = {"待签订", "已终止"}


def parse_date(value: Any) -> date | None:
    """把 YYYY-MM-DD 文本解析成日期；空缺或格式不对一律返回 None，由调用方决定如何拒绝。"""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def reminder_info(entry: dict[str, Any], today: date, window: int) -> dict[str, Any]:
    """到期提醒的唯一口径：只看后端记录的「到期日期」，不相信前端传的状态。"""
    expire = parse_date(entry.get("到期日期"))
    if expire is None or entry.get("status") in REMIND_SILENT_STATUSES:
        return {"到期提醒": "", "剩余天数": None, "即将到期": False, "已逾期": False}
    days = (expire - today).days
    if days < 0:
        label = "今日到期" if days == 0 else f"已逾期{-days}天"
        return {"到期提醒": label, "剩余天数": days, "即将到期": False, "已逾期": True}
    if days == 0:
        return {"到期提醒": "今日到期", "剩余天数": 0, "即将到期": True, "已逾期": False}
    if days <= window:
        return {"到期提醒": f"{days}天后到期", "剩余天数": days, "即将到期": True, "已逾期": False}
    return {"到期提醒": "", "剩余天数": days, "即将到期": False, "已逾期": False}


def to_view(entry: dict[str, Any], window: int = DEFAULT_REMIND_WINDOW, today: date | None = None) -> dict[str, Any]:
    """组装对外返回的协议数据：补齐续签默认值并贴上统一口径的提醒标记。"""
    today = today or date.today()
    view = dict(entry)
    view.setdefault("续签次数", 0)
    view.setdefault("续签记录", {})
    view.update(reminder_info(entry, today, window))
    return view


class AgreementService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        reminding: bool = False,
        window: int = DEFAULT_REMIND_WINDOW,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        today = date.today()
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("协议编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        # 列表的「只看即将到期」与 /reminders、统计卡片共用 reminder_info，口径必然一致
        if reminding:
            rows = [row for row in rows if reminder_info(row, today, window)["即将到期"]]
        total = len(rows)
        start = max(page - 1, 0) * size
        page_rows = [to_view(row, window, today) for row in rows[start:start + size]]
        return page_rows, total

    def list_reminders(self, window: int) -> list[dict[str, Any]]:
        """即将到期清单：越接近到期排越前，供提醒区与列表筛选直接对照。"""
        today = date.today()
        views = [to_view(row, window, today) for row in store.rows(MODULE)]
        views = [view for view in views if view["即将到期"]]
        views.sort(key=lambda view: view["剩余天数"] if view["剩余天数"] is not None else 10**9)
        return views

    def summary(self, window: int) -> dict[str, Any]:
        """列表页三张统计卡：履行中、即将到期与协议总金额，数字与表格、提醒同口径。"""
        today = date.today()
        rows = store.rows(MODULE)
        active = [row for row in rows if row.get("status") == "履行中"]
        expiring = sum(1 for row in rows if reminder_info(row, today, window)["即将到期"])
        total_amount = 0.0
        for row in active:
            try:
                total_amount += float(row.get("协议金额") or 0)
            except (TypeError, ValueError):
                continue
        return {
            "履行中协议": len(active),
            "即将到期协议": expiring,
            "协议总金额": round(total_amount, 2),
            "提醒窗口天数": window,
        }

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        return to_view(entry) if entry is not None else None

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return to_view(entry), []

    def renew_entry(
        self, entry_id: int, values: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, str]:
        """确认续签：先留痕再写入新期限。终止与续签互斥，留痕字段不会被状态动作覆盖。"""
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"保障协议 {entry_id} 不存在或已归档"
        if entry.get("status") == "已终止":
            return None, "协议已终止，不能续签；如需继续合作请重新登记保障协议"
        if not str(entry.get("服务单位") or "").strip():
            return None, "服务单位空缺，无法续签，请先补全服务单位后再操作"

        period = str(values.get("服务期限") or "").strip()
        amount_raw = values.get("协议金额")
        signer = str(values.get("签订人员") or "").strip()
        sign_date = parse_date(values.get("签订日期"))
        expire_date = parse_date(values.get("到期日期"))

        missing = [
            label
            for label, value in (
                ("服务期限", period),
                ("协议金额", amount_raw),
                ("签订人员", signer),
                ("签订日期", values.get("签订日期")),
                ("到期日期", values.get("到期日期")),
            )
            if not str(value or "").strip()
        ]
        if missing:
            return None, f"续签信息缺少必填项：{'、'.join(missing)}"
        if sign_date is None:
            return None, "签订日期格式不正确，请使用 YYYY-MM-DD 格式的日期"
        if expire_date is None:
            return None, "到期日期格式不正确，请使用 YYYY-MM-DD 格式的日期"
        if expire_date < sign_date:
            return (
                None,
                f"到期日期 {expire_date.isoformat()} 早于签订日期 {sign_date.isoformat()}，"
                "服务期限不能倒签，请核对后重新提交",
            )
        try:
            amount = round(float(amount_raw), 2)
        except (TypeError, ValueError):
            return None, f"协议金额「{amount_raw}」不是有效金额，请填写数字"

        agreement_no = str(entry.get("协议编号") or "").strip()
        history = entry.setdefault("续签记录", {})
        # 同一协议编号重复续签只保留最新一次：直接按编号覆盖旧快照
        history[agreement_no] = {
            "服务期限": entry.get("服务期限", ""),
            "协议金额": entry.get("协议金额"),
            "签订人员": entry.get("签订人员", ""),
            "签订日期": entry.get("签订日期", ""),
            "到期日期": entry.get("到期日期", ""),  # 原到期日期留痕
            "保障项目": entry.get("保障项目", ""),  # 保障项目原样保留
        }

        entry["续签次数"] = int(entry.get("续签次数") or 0) + 1
        entry["服务期限"] = period
        entry["协议金额"] = amount
        entry["签订人员"] = signer
        entry["签订日期"] = sign_date.isoformat()
        entry["到期日期"] = expire_date.isoformat()
        entry["status"] = "履行中"
        entry["pending"] = True
        entry["abnormal"] = False
        return to_view(entry), f"保障协议 {agreement_no} 已续签，累计续签 {entry['续签次数']} 次"

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"保障协议 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于保障协议可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        # 只改状态相关字段，续签次数、续签记录、服务期限等留痕一律不动
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return to_view(entry), f"保障协议已{action}"
