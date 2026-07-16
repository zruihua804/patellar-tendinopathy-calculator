"""Feishu Base adapter for the patellar-tendinopathy calculator."""

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
    unique_keys: tuple[str, ...]


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
    TableSpec("patients", "患者主表", (text("patient_id", "患者ID"), text("medical_record_no", "病历号"), text("name", "姓名"), choice("sex", "性别", "男", "女", "待确认"), when("birth_date", "出生日期"), choice("consent_status", "同意状态", "已同意", "未同意", "待确认"), when("saved_at", "保存时间")), ("patient_id",)),
    # One record = one patient at one dated follow-up point.  The natural key
    # is used only by the adapter and is deliberately not exposed as a column.
    TableSpec("assessments", "髌腱病评估表", (text("patient_id", "患者ID"), choice("timepoint", "评估节点", "基线", "6周", "12周", "6个月", "12个月"), when("assessment_date", "评估日期"), choice("affected_side", "患侧", "左", "右", "双侧"), choice("episode_status", "病程状态", "新诊断", "保守康复中", "复评", "已结束"), number("symptom_duration_weeks", "症状时长（周）"), choice("diagnostic_confidence", "诊断把握度", "确诊", "高度怀疑", "待鉴别"), check("red_flag_present", "红旗/优先复评"), text("doctor", "主管医生"), text("therapist", "康复治疗师"), text("primary_activity", "主运动/工作负荷"), text("recent_load_change", "近期负荷变化"), number("activity_pain_vas", "指定负荷疼痛VAS"), text("pain_activity_description", "疼痛活动场景"), number("visa_p_total", "VISA-P总分"), choice("visa_p_completion_status", "VISA-P完成状态", "completed", "not completed"), choice("visa_p_respondent_source", "填写来源", "patient", "doctor-assisted", "therapist-assisted", "not completed"), text("target_sport", "目标运动"), choice("target_activity_level", "目标运动水平", "日常活动", "休闲运动", "校队/业余竞赛", "半职业", "职业/精英"), choice("return_to_activity_status", "重返活动状态", "未恢复", "恢复部分活动", "恢复目标运动但未达伤前水平", "恢复伤前水平"), number("week_no", "康复周次"), choice("phase", "康复阶段", "症状管理", "恢复", "重建", "重返活动"), number("supervised_sessions", "监督治疗次数"), number("home_training_days", "居家训练天数"), number("adherence_percent", "依从性（%）"), number("pain_during_load_nrs", "训练时疼痛NRS"), number("pain_24h_after_nrs", "训练后24小时疼痛NRS"), text("therapist_interpretation", "康复师解释"), text("warnings", "临床提示"), when("saved_at", "保存时间")), ("patient_id", "timepoint", "assessment_date")),
    TableSpec("rom", "ROM 综合评估", (text("patient_id", "患者ID"), choice("timepoint", "评估节点", "基线", "6周", "12周", "6个月", "12个月"), when("measured_at", "测量日期"), choice("affected_side", "患侧", "左", "右", "双侧"), choice("reference_knee_side", "健侧/对照侧", "左", "右"), choice("mode", "模式", "主动", "被动"), number("affected_knee_flexion_deg", "患侧膝屈曲（度）"), number("affected_knee_extension_deficit_deg", "患侧膝伸展受限（度）"), number("reference_knee_flexion_deg", "健侧膝屈曲（度）"), number("reference_knee_extension_deficit_deg", "健侧膝伸展受限（度）"), number("affected_hip_flexion_deg", "患侧髋屈曲（度）"), number("affected_hip_extension_deg", "患侧髋伸展（度）"), number("affected_hip_internal_rotation_deg", "患侧髋内旋（度）"), number("affected_hip_external_rotation_deg", "患侧髋外旋（度）"), number("affected_ankle_knee_to_wall_cm", "患侧踝膝靠墙（cm）"), choice("method", "测量方法", "量角器", "倾角仪", "目测", "其他"), text("assessor", "评估者")), ("patient_id", "timepoint", "measured_at")),
    TableSpec("followup_summary", "患者随访总览", (text("patient_id", "患者ID"), when("baseline_date", "基线日期"), number("baseline_visa_p_total", "基线VISA-P"), number("baseline_activity_pain_vas", "基线VAS"), when("latest_date", "最近评估日期"), choice("latest_timepoint", "最近随访节点", "基线", "6周", "12周", "6个月", "12个月"), number("latest_visa_p_total", "最近VISA-P"), number("latest_activity_pain_vas", "最近VAS"), number("visa_p_change_from_baseline", "VISA-P较基线变化"), number("pain_change_from_baseline", "VAS较基线变化"), choice("return_to_activity_status", "重返活动状态", "未恢复", "恢复部分活动", "恢复目标运动但未达伤前水平", "恢复伤前水平"), choice("escalation_or_surgery", "升级治疗/手术", "无", "复评", "转诊", "已手术"), text("escalation_reason", "升级原因"), when("saved_at", "保存时间")), ("patient_id",)),
)

RETIRED_TABLE_NAMES = (
    "髌腱病病程表",
    "膝关节活动度表",
    "髌腱病康复记录",
    "髌腱病随访结局",
    "患者报告与病历文本",
)

RETIRED_FIELD_NAMES_BY_TABLE = {
    "髌腱病评估表": ("评估ID", "病程ID"),
    "ROM 综合评估": ("ROM ID", "评估ID", "病程ID"),
    "患者随访总览": ("病程ID",),
}
SPEC_BY_KEY = {spec.key: spec for spec in TABLE_SPECS}


def _timestamp(value: Any) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return int(value)
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

    @staticmethod
    def _same_key_value(left: Any, right: Any, field: FieldSpec) -> bool:
        if field.kind == "date":
            return _timestamp(left) == _timestamp(right)
        return str(left or "") == str(right or "")

    def delete_retired_tables(self, app_token: str) -> list[str]:
        """Delete only the explicitly retired prototype tables.

        This is deliberately an opt-in operation from the deployed admin panel;
        schema maintenance itself remains non-destructive.
        """
        existing = {str(row.get("name")): str(row.get("table_id")) for row in self.list_tables(app_token)}
        removed: list[str] = []
        for name in RETIRED_TABLE_NAMES:
            table_id = existing.get(name)
            if table_id:
                self._request("DELETE", f"/bitable/v1/apps/{app_token}/tables/{table_id}")
                removed.append(name)
        return removed

    def delete_retired_id_fields(self, app_token: str) -> list[str]:
        """Remove obsolete opaque-ID columns without deleting Feishu's mandatory primary field.

        Older prototype tables used an assessment/ROM ID as the primary column.
        Feishu does not permit deleting that column, so it is converted into the
        single patient-ID column after copying values from the existing patient
        ID field.  The duplicate non-primary patient-ID field is then removed.
        """
        existing = {str(row.get("name")): str(row.get("table_id")) for row in self.list_tables(app_token)}
        removed: list[str] = []
        for table_name, field_names in RETIRED_FIELD_NAMES_BY_TABLE.items():
            table_id = existing.get(table_name)
            if not table_id:
                continue
            field_rows = self.list_fields(app_token, table_id)
            fields = {str(row.get("field_name")): row for row in field_rows}
            for field_name in field_names:
                field = fields.get(field_name)
                if not field:
                    continue
                field_id = str(field.get("field_id"))
                if not field.get("is_primary"):
                    self._request("DELETE", f"/bitable/v1/apps/{app_token}/tables/{table_id}/fields/{field_id}")
                    removed.append(f"{table_name}·{field_name}")
                    continue

                patient_field = fields.get("患者ID")
                if patient_field and not patient_field.get("is_primary"):
                    patient_field_id = str(patient_field.get("field_id"))
                    for record in self.list_records(app_token, table_id):
                        patient_id = record.get("fields", {}).get("患者ID")
                        if patient_id not in (None, ""):
                            self._request(
                                "PUT",
                                f"/bitable/v1/apps/{app_token}/tables/{table_id}/records/{record['record_id']}",
                                {"fields": {field_name: patient_id}},
                            )
                    self._request("DELETE", f"/bitable/v1/apps/{app_token}/tables/{table_id}/fields/{patient_field_id}")

                self._request(
                    "PUT",
                    f"/bitable/v1/apps/{app_token}/tables/{table_id}/fields/{field_id}",
                    {"field_name": "患者ID"},
                )
                removed.append(f"{table_name}·{field_name}（已转为患者ID主列）")
        return removed

    def upsert_record(self, app_token: str, table_id: str, table_key: str, record: dict[str, Any]) -> str:
        spec = SPEC_BY_KEY[table_key]
        fields = format_record_fields(table_key, record)
        key_specs = tuple(field for field in spec.fields if field.key in spec.unique_keys)
        missing = [field.name for field in key_specs if fields.get(field.name) in (None, "")]
        if missing:
            raise FeishuAPIError(f"缺少用于安全更新的字段：{'、'.join(missing)}。")
        matches = [
            row for row in self.list_records(app_token, table_id)
            if all(self._same_key_value(row.get("fields", {}).get(field.name), fields.get(field.name), field) for field in key_specs)
        ]
        if len(matches) > 1:
            raise FeishuAPIError(f"飞书中存在 {len(matches)} 条相同患者与评估时间记录；系统不会自动删除，请先人工核查。")
        if not matches:
            data = self._request("POST", f"/bitable/v1/apps/{app_token}/tables/{table_id}/records", {"fields": fields})
        else:
            record_id = str(matches[0].get("record_id", ""))
            data = self._request("PUT", f"/bitable/v1/apps/{app_token}/tables/{table_id}/records/{record_id}", {"fields": fields})
        return str(data.get("record", {}).get("record_id") or data.get("record_id") or "")
