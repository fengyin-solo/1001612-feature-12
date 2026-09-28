"""保障协议业务规则：到期提醒、续签留痕、终止路径与筛选口径都收在这里。

口径约定（列表与提醒必须对得上，全部以后端数据为准）：
- ``到期日期`` 是唯一的日期基准，前端不自行计算；
- 未终止、且已过“确认签订”的协议，按到期日期派生“已到期 / 即将到期 / 履行中”；
- 提前提醒窗口默认 30 天，窗口内（含到期当天）记为“即将到期”；
- 续签流水按协议编号只保留最新一次，列表里的“续签次数”以流水为唯一来源。
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from app.store import store

MODULE = "agreement"
REQUIRED_FIELDS = ["协议编号", "服务单位", "保障项目"]
STATUS_ORDER = ["待签订", "履行中", "已到期", "已终止"]
ACTION_RULES = {"确认签订": "履行中", "标记到期": "已到期", "终止协议": "已终止"}

# 到期提醒提前天数：到期日期往前推这个窗口内都算“即将到期”
REMIND_WINDOW_DAYS = 30
TODAY = date(2026, 9, 28)


def _parse_date(value: Any) -> date | None:
    """尽量宽松地解析 YYYY-MM-DD 日期；解析不了就返回 None，由调用方决定口径。"""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _parse_amount(value: Any) -> float | None:
    """协议金额允许数字或纯数字字符串；空串、非数字返回 None。"""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, bool):  # bool 是 int 的子类，这里不当金额
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip().replace(",", ""))
    except ValueError:
        return None


class AgreementService:
    def __init__(self) -> None:
        # 续签流水：协议编号 -> 最新一次续签记录（同一编号重复续签只保留最新一次）
        self.renewals: dict[str, dict[str, Any]] = {}

    # ----- 列表与派生口径 -------------------------------------------------

    def _renewal_count(self, agreement_no: str) -> int:
        record = self.renewals.get(agreement_no)
        return int(record["续签次数"]) if record else 0

    def _derive(self, row: dict[str, Any]) -> dict[str, Any]:
        """在不改动存储行的前提下，补出状态、到期提醒与续签次数等派生字段。

        列表筛选、提醒接口、统计接口都走这里，保证三个口径一致。
        """
        view = dict(row)
        stored_status = str(row.get("status") or "").strip()

        # “待签订”“已终止”是流程状态，不按日期派生；其余按到期日期以后端数据为准
        if stored_status in ("待签订", "已终止"):
            effective_status = stored_status
        else:
            effective_status = stored_status or "履行中"
            expire_on = _parse_date(row.get("到期日期"))
            if expire_on is not None and expire_on < TODAY:
                effective_status = "已到期"

        expire_on = _parse_date(row.get("到期日期"))
        days_left: int | None = None
        if expire_on is not None and stored_status not in ("待签订", "已终止"):
            days_left = (expire_on - TODAY).days

        if effective_status == "已到期":
            expire_remind = "已到期"
        elif days_left is not None and 0 <= days_left <= REMIND_WINDOW_DAYS:
            expire_remind = f"即将到期（剩余{days_left}天）" if days_left else "今日到期"
        else:
            expire_remind = ""

        agreement_no = str(row.get("协议编号") or "").strip()
        view["协议状态"] = effective_status
        view["到期提醒"] = expire_remind
        view["剩余天数"] = days_left
        view["续签次数"] = self._renewal_count(agreement_no)
        return view

    def _filtered_rows(self, *, keyword: str | None, status: str | None) -> list[dict[str, Any]]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("协议编号", ""))]
        if status:
            rows = [row for row in rows if self._derive(row)["协议状态"] == status]
        return rows

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = self._filtered_rows(keyword=keyword, status=status)
        total = len(rows)
        start = max(page - 1, 0) * size
        return [self._derive(row) for row in rows[start:start + size]], total

    def list_reminders(self) -> list[dict[str, Any]]:
        """到期提醒：与列表同一派生口径，返回即将到期与已到期的协议。"""
        reminders: list[dict[str, Any]] = []
        for row in store.rows(MODULE):
            view = self._derive(row)
            if view["到期提醒"]:
                reminders.append({
                    "id": row.get("id"),
                    "协议编号": row.get("协议编号"),
                    "服务单位": row.get("服务单位"),
                    "保障项目": row.get("保障项目"),
                    "到期日期": row.get("到期日期"),
                    "协议状态": view["协议状态"],
                    "到期提醒": view["到期提醒"],
                    "剩余天数": view["剩余天数"],
                    "续签次数": view["续签次数"],
                })
        reminders.sort(key=lambda item: (item["剩余天数"] is None, item["剩余天数"] or 0))
        return reminders

    def summary(self) -> dict[str, Any]:
        """列表页统计卡片：与列表、提醒同一口径计算。"""
        views = [self._derive(row) for row in store.rows(MODULE)]
        performing = sum(1 for view in views if view["协议状态"] == "履行中")
        expiring = sum(1 for view in views if view["到期提醒"].startswith("即将到期") or view["到期提醒"] == "今日到期")
        expired = sum(1 for view in views if view["协议状态"] == "已到期")
        terminated = sum(1 for view in views if view["协议状态"] == "已终止")
        total_amount = 0.0
        for view in views:
            amount = _parse_amount(view.get("协议金额"))
            if amount is not None:
                total_amount += amount
        return {
            "履行中协议": performing,
            "即将到期协议": expiring,
            "已到期协议": expired,
            "已终止协议": terminated,
            "协议总金额": round(total_amount, 2),
            "提醒提前天数": REMIND_WINDOW_DAYS,
            "统计基准日": TODAY.isoformat(),
        }

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        row = store.find(MODULE, entry_id)
        return self._derive(row) if row is not None else None

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        # 登记时可一并带上金额、期限、人员、到期日期，列表才能做到期提醒
        for field in ("协议金额", "服务期限", "签订人员", "到期日期"):
            if values.get(field) is not None:
                entry[field] = values.get(field)
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return self._derive(entry), []

    # ----- 状态动作 -------------------------------------------------------

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"保障协议 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于保障协议可执行范围"

        stored_status = str(entry.get("status") or "")
        if action == "终止协议":
            if stored_status == "已终止":
                return None, "协议已终止，无需重复终止"
            # 终止路径只落终止标记，不碰续签流水与续签写入的服务字段
            entry["status"] = "已终止"
            entry["pending"] = False
            return self._derive(entry), "保障协议已终止"

        if action == "确认签订":
            if stored_status == "已终止":
                return None, "协议已终止，不能再确认签订"
            entry["status"] = "履行中"
            entry["pending"] = False
            return self._derive(entry), "保障协议已确认签订"

        if action == "标记到期":
            if stored_status == "待签订":
                return None, "协议尚未确认签订，不能标记到期"
            if stored_status == "已终止":
                return None, "协议已终止，不能标记到期"
            expire_on = _parse_date(entry.get("到期日期"))
            if expire_on is None:
                return None, "协议缺少有效的到期日期，无法标记到期；到期日期以后端数据为准"
            if expire_on >= TODAY:
                return None, f"协议尚未到期（到期日期 {expire_on.isoformat()}），不能提前标记到期"
            entry["status"] = "已到期"
            entry["pending"] = False
            return self._derive(entry), "保障协议已标记到期"

        return None, f"动作「{action}」不属于保障协议可执行范围"

    # ----- 续签留痕 -------------------------------------------------------

    def renew(
        self,
        entry_id: int,
        values: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, str]:
        """确认续签：写入新的服务期限、协议金额、签订人员，并留一条续签流水。

        - 原到期日期与保障项目只保留不覆盖；
        - 同一协议编号重复续签只保留最新一次，次数累加；
        - 服务单位空缺、新服务期限早于签订日期时拒绝并说明原因；
        - 已终止 / 待签订协议不允许续签，避免和终止路径互相覆盖。
        """
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"保障协议 {entry_id} 不存在或已归档"

        stored_status = str(entry.get("status") or "")
        if stored_status == "已终止":
            return None, "协议已终止，不能续签；如需继续保障请重新登记协议"
        if stored_status == "待签订":
            return None, "协议尚未确认签订，不能直接续签"

        agreement_no = str(entry.get("协议编号") or "").strip()
        service_unit = str(values.get("服务单位") or entry.get("服务单位") or "").strip()
        if not service_unit:
            return None, "续签被拒绝：服务单位不能为空，请补齐服务单位后再续签"

        new_period = str(values.get("服务期限") or "").strip()
        signer = str(values.get("签订人员") or "").strip()
        if not new_period:
            return None, "续签被拒绝：新的服务期限不能为空"
        if not signer:
            return None, "续签被拒绝：签订人员不能为空"

        amount = _parse_amount(values.get("协议金额"))
        if amount is None:
            return None, "续签被拒绝：协议金额需填写为不小于 0 的数字"
        if amount < 0:
            return None, "续签被拒绝：协议金额不能为负数"

        period_start = _parse_date(new_period)
        if period_start is None:
            return None, f"续签被拒绝：服务期限「{new_period}」不是有效日期（格式应为 YYYY-MM-DD）"

        # 签订日期：优先取本次提交，未提交则以业务当天为准
        sign_date = _parse_date(values.get("签订日期")) or TODAY
        if period_start < sign_date:
            return (
                None,
                "续签被拒绝：新的服务期限"
                f"（{period_start.isoformat()}）早于签订日期（{sign_date.isoformat()}），"
                "请核对服务期限或签订日期",
            )

        # 保留原到期日期与保障项目：续签主体字段不覆盖它们，只在流水里留痕
        old_period = entry.get("服务期限")
        old_amount = entry.get("协议金额")
        old_signer = entry.get("签订人员")
        previous = self.renewals.get(agreement_no)
        renew_count = int(previous["续签次数"]) + 1 if previous else 1

        record = {
            "协议编号": agreement_no,
            "服务单位": service_unit,
            "保障项目": entry.get("保障项目"),
            "续签次数": renew_count,
            "原服务期限": old_period,
            "新服务期限": new_period,
            "原协议金额": old_amount,
            "新协议金额": amount,
            "原签订人员": old_signer,
            "新签订人员": signer,
            "签订日期": sign_date.isoformat(),
            "原到期日期": entry.get("到期日期"),
            "续签时间": datetime.combine(TODAY, datetime.min.time()).isoformat(timespec="seconds"),
        }
        # 同一协议编号重复续签：只保留最新一次（次数继续累加）
        self.renewals[agreement_no] = record

        # 只写入新的服务期限、协议金额、签订人员；原到期日期与保障项目原样保留
        entry["服务期限"] = new_period
        entry["协议金额"] = amount
        entry["签订人员"] = signer
        # 续签成功后回到“履行中”，是否已到期仍由后端按到期日期派生
        entry["status"] = "履行中"
        entry["pending"] = False
        return self._derive(entry), f"保障协议已完成第 {renew_count} 次续签"

    def list_renewals(self) -> list[dict[str, Any]]:
        """续签留痕清单：每个协议编号只出现最新一次续签记录。"""
        return sorted(
            (dict(record) for record in self.renewals.values()),
            key=lambda item: (-int(item["续签次数"]), str(item["协议编号"])),
        )
