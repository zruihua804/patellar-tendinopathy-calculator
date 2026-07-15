"""Non-destructive Feishu Base adapter for the patellar-tendinopathy calculator."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import json
from typing import Any
from urllib.parse import urlparse

import requests


API_ROOT = "https://open.feishu.cn/open-apis"


class FeishuConfigurationError(RuntimeError):
    pass


class FeishuAPIError(RuntimeError):
    pass


@dataclass(frozen=True)
class FeishuConfig:
    app_id: str
    app_secret: str
    bitable_app_token: str = ""
    bitable_url: str = ""

    @classmethod
    def from_mapping(cls, values: dict[str, Any]) -> "FeishuConfig":
        app_id = str(values.get("app_id", "")).strip()
        app_secret = str(values.get("app_secret", "")).strip()
        source = str(values.get("bitable_app_token") or values.get("bitable_url") or "").strip()
        if not app_id or not app_secret:
            raise FeishuConfigurationError("请在 Secrets 中填写飞书 App ID 和 App Secret。")
        if not source:
            raise FeishuConfigurationError("请填写由临床用户创建的飞书多维表格链接或 App Token。")
        return cls(app_id, app_secret, str(values.get("bitable_app_token", "")).strip(), str(values.get("bitable_url", "")).strip())

    @property
    def source(self) -> str:
        return self.bitable_app_token or self.bitable_url


@dataclass(frozen=True)
class FieldSpec:
    key: str
    name: str
    kind: str = "text"
    options: tuple[str, ...] = ()

    def payload(self) -> dict[str, Any]:
        type_by_kind = {"text": 1, "number": 2, "select": 3, "date": 5, "checkbox": 7}
        field: dict[str, Any] = {"field_name": self.name, "type": type_by_kind[self.kind]}
        if self.kind == "select":
            field["property"] = {"options": [{"name": option} for option in self.options]}
        return field


@dataclass(frozen=True)
class TableSpec:
    key: str
    name: str
    fields: tuple[FieldSpec, ...]


def text(key: str, name: str) -> FieldSpec:
    return FieldSpec(key, name)


def number(key: str, name: str) -> FieldSpec:
    return FieldSpec(key, name, "number")


def choice(key: str, name: str, *options: str) -> FieldSpec:
    return FieldSpec(key, name, "select", options)


def when(key: str, name: str) -> FieldSpec:
    return FieldSpec(key, name, "date")


def check(key: str, name: str) -> FieldSpec:
    return FieldSpec(key, name, "checkbox")


TABLE_SPECS: tuple[TableSpec, ...] = (
    TableSpec("patients", "患者主表", (text("patient_id", "患者ID"), text("medical_record_no", "病历号"), text("name", "姓名"), choice("sex", "性别", "男", "女", "待确认"), when("birth_date", "出生日期"), choice("consent_status", "同意状态", "已同意", "未同意", "待确认"), when("saved_at", "保存时间"))),
    TableSpec("episodes", "髌腱病病程表", (text("episode_id", "病程ID"), text("patient_id", "患者ID"), choice("affected_side", "患侧", "左", "右", "双侧"), choice("status", "病程状态", "新诊断", "保守康复中", "复评", "已结束"), number("symptom_duration_weeks", "症状时长（周）"), choice("diagnostic_confidence", "诊断把握度", "确诊", "高度怀疑", "待鉴别"), check("red_flag_present", "红旗/优先复评"), text("doctor", "主管医生"), text("therapist", "康复治疗师"), when("saved_at", "保存时间"))),
    TableSpec("assessments", "髌腱病评估表", (text("assessment_id", "评估ID"), text("patient_id", "患者ID"), text("episode_id", "病程ID"), choice("timepoint", "评估节点", "基线", "6周", "12周", "6个月", "12个月"), when("assessment_date", "评估日期"), number("activity_pain_nrs", "指定负荷疼痛NRS"), number("activity_pain_vas", "指定负荷疼痛VAS"), text("pain_activity_description", "疼痛活动场景"), number("visa_p_total", "VISA-P总分"), choice("visa_p_completion_status", "VISA-P完成状态", "completed", "not completed"), choice("visa_p_respondent_source", "填写来源", "patient", "doctor-assisted", "therapist-assisted", "not completed"), text("target_sport", "目标运动"), choice("target_activity_level", "目标运动水平", "日常活动", "休闲运动", "校队/业余竞赛", "半职业", "职业/精英"), choice("return_to_activity_status", "重返活动状态", "未恢复", "恢复部分活动", "恢复目标运动但未达伤前水平", "恢复伤前水平"), text("warnings", "临床提示"), when("saved_at", "保存时间"))),
    TableSpec("rom", "膝关节活动度表", (text("rom_id", "ROM ID"), text("assessment_id", "评估ID"), choice("joint", "关节", "膝关节", "髋关节", "踝关节"), choice("side", "侧别", "左", "右", "双侧"), choice("comparison_role", "比较角色", "患侧", "健侧/对照侧", "患侧同侧"), choice("mode", "模式", "主动", "被动"), number("flexion_deg", "屈曲（度）"), number("extension_deficit_deg", "伸展受限（度）"), number("extension_deg", "伸展（度）"), number("internal_rotation_deg", "内旋（度）"), number("external_rotation_deg", "外旋（度）"), number("knee_to_wall_cm", "膝靠墙距离（cm）"), text("pain_or_limit", "疼痛/限制"), choice("method", "测量方法", "量角器", "倾角仪", "目测", "其他"), text("assessor", "评估者"), when("measured_at", "测量时间"))),
    TableSpec("rehab", "髌腱病康复记录", (text("rehab_id", "康复记录ID"), text("episode_id", "病程ID"), number("week_no", "康复周次"), choice("phase", "康复阶段", "症状管理", "恢复", "重建", "重返活动"), number("supervised_sessions", "监督治疗次数"), number("home_training_days", "居家训练天数"), number("adherence_percent", "依从性（%）"), number("pain_during_load_nrs", "训练时疼痛NRS"), number("pain_24h_after_nrs", "训练后24小时疼痛NRS"), text("therapist_interpretation", "康复师解释"), when("saved_at", "保存时间"))),
    TableSpec("outcomes", "髌腱病随访结局", (text("outcome_id", "结局ID"), text("episode_id", "病程ID"), choice("timepoint", "随访节点", "基线", "6周", "12周", "6个月", "12个月"), number("visa_p_total", "VISA-P总分"), number("visa_p_change_from_baseline", "VISA-P较基线变化"), number("activity_pain_nrs", "指定负荷疼痛NRS"), number("activity_pain_vas", "指定负荷疼痛VAS"), choice("return_to_activity_status", "重返活动状态", "未恢复", "恢复部分活动", "恢复目标运动但未达伤前水平", "恢复伤前水平"), choice("escalation_or_surgery", "升级治疗/手术", "无", "复评", "转诊", "已手术"), text("escalation_reason", "升级原因"), when("saved_at", "保存时间"))),
    TableSpec("reports", "患者报告与病历文本", (text("report_id", "报告ID"), text("assessment_id", "评估ID"), text("evidence_version", "证据版本"), choice("model_status", "模型状态", "数据采集与趋势计算"), text("patient_report_text", "患者解释"), text("medical_record_text", "病历文本"), when("saved_at", "保存时间"))),
)
SPEC_BY_KEY = {spec.key: spec for spec in TABLE_SPECS}


def _timestamp(value: Any) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return int(value.timestamp() * 1000)
    if isinstance(value, date):
        return int(datetime.combine(value, datetime.min.time()).timestamp() * 1000)
    try:
        return int(datetime.fromisoformat(str(value)).timestamp() * 1000)
    except ValueError:
        return None


def format_record_fields(table_key: str, record: dict[str, Any]) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    for field in SPEC_BY_KEY[table_key].fields:
        value = record.get(field.key)
        if value in (None, ""):
            continue
        if field.kind == "date":
            timestamp = _timestamp(value)
            if timestamp is not None:
                fields[field.name] = timestamp
        elif field.kind == "number":
            fields[field.name] = float(value)
        elif field.kind == "checkbox":
            fields[field.name] = bool(value)
        elif isinstance(value, (dict, list)):
            fields[field.name] = json.dumps(value, ensure_ascii=False)
        else:
            fields[field.name] = str(value)
    return fields


class FeishuBitableClient:
    def __init__(self, config: FeishuConfig, session: requests.Session | None = None) -> None:
        self.config = config
        self.session = session or requests.Session()
        self._tenant_access_token: str | None = None

    @staticmethod
    def _payload(response: requests.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise FeishuAPIError(f"飞书返回无法识别的响应（HTTP {response.status_code}）。") from exc
        if response.status_code >= 400 or payload.get("code", 0) != 0:
            raise FeishuAPIError(f"飞书接口调用失败：{payload.get('msg') or response.status_code}")
        return payload.get("data", payload)

    def _token(self) -> str:
        if self._tenant_access_token:
            return self._tenant_access_token
        response = self.session.post(f"{API_ROOT}/auth/v3/tenant_access_token/internal", json={"app_id": self.config.app_id, "app_secret": self.config.app_secret}, timeout=20)
        token = self._payload(response).get("tenant_access_token")
        if not token:
            raise FeishuAPIError("飞书未返回 tenant_access_token；请检查应用权限与发布状态。")
        self._tenant_access_token = str(token)
        return self._tenant_access_token

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None, params: dict[str, Any] | None = None) -> dict[str, Any]:
        response = self.session.request(method, f"{API_ROOT}{path}", headers={"Authorization": f"Bearer {self._token()}", "Content-Type": "application/json; charset=utf-8"}, json=payload, params=params, timeout=30)
        return self._payload(response)

    def resolve_bitable_token(self, source: str | None = None) -> str:
        cleaned = (source or self.config.source).strip()
        if cleaned.startswith("app"):
            return cleaned
        parsed = urlparse(cleaned)
        parts = [part for part in parsed.path.split("/") if part]
        if "base" in parts and len(parts) > parts.index("base") + 1:
            return parts[parts.index("base") + 1]
        if "wiki" in parts and len(parts) > parts.index("wiki") + 1:
            node = self._request("GET", "/wiki/v2/spaces/get_node", params={"token": parts[parts.index("wiki") + 1]}).get("node", {})
            if node.get("obj_type") == "bitable" and node.get("obj_token"):
                return str(node["obj_token"])
        raise FeishuConfigurationError("无法解析飞书多维表格链接。请粘贴完整 /base/ 或 /wiki/ 链接。")

    def list_tables(self, app_token: str) -> list[dict[str, Any]]:
        return list(self._request("GET", f"/bitable/v1/apps/{app_token}/tables").get("items", []))

    def list_fields(self, app_token: str, table_id: str) -> list[dict[str, Any]]:
        return list(self._request("GET", f"/bitable/v1/apps/{app_token}/tables/{table_id}/fields").get("items", []))

    def ensure_schema(self, app_token: str) -> dict[str, str]:
        """Add missing tables/fields only. This never deletes or recreates a user-owned Base."""
        existing = {str(row.get("name")): str(row.get("table_id")) for row in self.list_tables(app_token)}
        table_ids: dict[str, str] = {}
        for spec in TABLE_SPECS:
            table_id = existing.get(spec.name)
            if not table_id:
                data = self._request("POST", f"/bitable/v1/apps/{app_token}/tables", {"table": {"name": spec.name, "default_view_name": "全部记录", "fields": [field.payload() for field in spec.fields]}})
                table_id = str(data.get("table_id", ""))
                if not table_id:
                    raise FeishuAPIError(f"未能创建数据表：{spec.name}")
            else:
                existing_fields = {str(row.get("field_name")) for row in self.list_fields(app_token, table_id)}
                for field in spec.fields:
                    if field.name not in existing_fields:
                        self._request("POST", f"/bitable/v1/apps/{app_token}/tables/{table_id}/fields", field.payload())
            table_ids[spec.key] = table_id
        return table_ids

    def list_records(self, app_token: str, table_id: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        page_token = ""
        while True:
            data = self._request("GET", f"/bitable/v1/apps/{app_token}/tables/{table_id}/records", params={"page_size": 100, **({"page_token": page_token} if page_token else {})})
            rows.extend(data.get("items", []))
            if not data.get("has_more") or not data.get("page_token"):
                return rows
            page_token = str(data["page_token"])

    def upsert_record(self, app_token: str, table_id: str, table_key: str, record: dict[str, Any]) -> str:
        spec = SPEC_BY_KEY[table_key]
        primary = spec.fields[0].name
        fields = format_record_fields(table_key, record)
        value = fields.get(primary)
        if value in (None, ""):
            raise FeishuAPIError(f"缺少“{primary}”，不能安全保存。")
        matches = [row for row in self.list_records(app_token, table_id) if str(row.get("fields", {}).get(primary, "")) == str(value)]
        if len(matches) > 1:
            raise FeishuAPIError(f"飞书中存在 {len(matches)} 条相同“{primary}”记录；系统不会自动删除，请先人工核查。")
        if not matches:
            data = self._request("POST", f"/bitable/v1/apps/{app_token}/tables/{table_id}/records", {"fields": fields})
        else:
            record_id = str(matches[0].get("record_id", ""))
            data = self._request("PUT", f"/bitable/v1/apps/{app_token}/tables/{table_id}/records/{record_id}", {"fields": fields})
        return str(data.get("record", {}).get("record_id") or data.get("record_id") or "")
