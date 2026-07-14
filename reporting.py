"""Patient-facing and medical-record text generated from structured values."""

from __future__ import annotations

from typing import Any

from model import MODEL_VERSION, TrendSummary


def _value(record: dict[str, Any], key: str, fallback: str = "未记录") -> str:
    value = record.get(key)
    return fallback if value in (None, "") else str(value)


def patient_report(assessment: dict[str, Any], trend: TrendSummary) -> str:
    visa = _value(assessment, "visa_p_total")
    pain = _value(assessment, "activity_pain_nrs")
    activity = _value(assessment, "pain_activity_description")
    return (
        "髌腱病通常表现为髌骨下方或髌腱的负荷相关疼痛。\n\n"
        f"本次记录：VISA-P {visa}/100；指定活动“{activity}”疼痛 NRS {pain}/10。\n\n"
        f"随访趋势：{trend.interpretation}\n\n"
        "本工具用于帮助记录症状、功能、训练负荷和康复过程，不会预测个人恢复概率、自动决定手术，"
        "也不替代医生或康复师的判断。若发生急性外伤、伸膝无力、明显肿胀或症状加重，请优先复评。\n\n"
        f"记录版本：{MODEL_VERSION}。"
    )


def medical_record_text(assessment: dict[str, Any], rom: dict[str, Any], trend: TrendSummary) -> str:
    mode = _value(rom, "mode")
    flexion = _value(rom, "flexion_deg", "未测")
    extension = _value(rom, "extension_deficit_deg", "未测")
    rom_note = _value(rom, "pain_or_limit", "未述特殊限制")
    method = _value(rom, "method", "未记录")
    return (
        f"髌腱病评估：{_value(assessment, 'affected_side')}侧；症状持续 {_value(assessment, 'symptom_duration_weeks')} 周；"
        f"指定负荷活动“{_value(assessment, 'pain_activity_description')}”疼痛 NRS {_value(assessment, 'activity_pain_nrs')}/10。"
        f"VISA-P {_value(assessment, 'visa_p_total')}/100（状态：{_value(assessment, 'visa_p_completion_status')}）。\n"
        f"关节活动度：患侧膝关节{mode}屈曲 {flexion}°、伸展受限 {extension}°（0°为完全伸直）；"
        f"{rom_note}，采用 {method} 测量。\n"
        f"随访解释：{trend.interpretation}"
    )
