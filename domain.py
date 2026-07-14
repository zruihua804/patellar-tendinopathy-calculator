"""Domain validation and stable identifiers for the patellar-tendinopathy workflow."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date


TIMEPOINTS = ("基线", "6周", "12周", "6个月", "12个月")
RETURN_TO_ACTIVITY = ("未恢复", "恢复部分活动", "恢复目标运动但未达伤前水平", "恢复伤前水平")
REHAB_PHASES = ("症状管理", "恢复", "重建", "重返活动")


def stable_id(prefix: str, *parts: object) -> str:
    clean_parts = [str(part).strip() for part in parts]
    digest = hashlib.sha256("|".join(clean_parts).encode("utf-8")).hexdigest()[:12].upper()
    return f"{prefix}-{digest}"


def patient_id_from_record(medical_record_no: str, name: str) -> str:
    identifier = re.sub(r"\s+", "", medical_record_no).upper() or re.sub(r"\s+", "", name)
    return stable_id("PT-P", identifier or "UNCONFIRMED")


def clinical_warnings(
    *,
    red_flag_present: bool,
    diagnostic_confidence: str,
    visa_p_total: int | None,
    activity_pain_nrs: float | int | None,
) -> list[str]:
    warnings: list[str] = []
    if red_flag_present:
        warnings.append("存在红旗或需优先排除的情况：请先由医生复评，不应按常规髌腱病康复流程推进。")
    if diagnostic_confidence == "待鉴别":
        warnings.append("诊断仍待鉴别：工具仅记录信息，不能替代临床诊断。")
    if visa_p_total is None:
        warnings.append("VISA-P 未完成：不会把未完成量表当作 0 分或正常分。")
    if activity_pain_nrs is not None and not 0 <= float(activity_pain_nrs) <= 10:
        warnings.append("活动疼痛 NRS 必须介于 0–10。")
    return warnings


@dataclass(frozen=True)
class AssessmentIdentity:
    patient_id: str
    episode_id: str
    assessment_id: str
    assessment_date: date
    timepoint: str


def assessment_identity(patient_id: str, affected_side: str, timepoint: str, assessment_date: date) -> AssessmentIdentity:
    if timepoint not in TIMEPOINTS:
        raise ValueError(f"不支持的评估时间点：{timepoint}")
    episode_id = stable_id("PT-E", patient_id, affected_side)
    assessment_id = stable_id("PT-A", episode_id, timepoint, assessment_date.isoformat())
    return AssessmentIdentity(patient_id, episode_id, assessment_id, assessment_date, timepoint)
