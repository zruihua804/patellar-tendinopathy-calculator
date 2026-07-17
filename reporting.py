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
        f"本次功能评分：VISA-P {visa}/100。\n"
        f"指定负荷活动“{activity}”疼痛：{pain}/10。\n"
        f"随访变化：{trend.interpretation}\n"
        "下一步重点：按康复师制定的渐进负荷计划完成训练，并依据疼痛和功能变化调整；若出现急性外伤、伸膝无力、明显肿胀或症状加重，请优先复评。\n"
        "本工具不替代医生或康复师的临床复评。\n"
        f"记录版本：{MODEL_VERSION}。"
    )


def medical_record_text(assessment: dict[str, Any], rom_rows: list[dict[str, Any]] | dict[str, Any], trend: TrendSummary) -> str:
    # Retain compatibility with early prototype records that had a single ROM row.
    if isinstance(rom_rows, dict):
        if "affected_knee_flexion_deg" in rom_rows:
            wide = rom_rows
            return (
                f"髌腱病评估：{_value(assessment, 'affected_side')}侧；症状持续 {_value(assessment, 'symptom_duration_weeks')} 周；"
                f"指定负荷活动“{_value(assessment, 'pain_activity_description')}”疼痛 VAS {_value(assessment, 'activity_pain_vas', _value(assessment, 'activity_pain_nrs'))}/10。"
                f"VISA-P {_value(assessment, 'visa_p_total')}/100（状态：{_value(assessment, 'visa_p_completion_status')}）。\n"
                f"ROM：患侧膝屈曲 {_value(wide, 'affected_knee_flexion_deg', '未测')}°、伸展受限 {_value(wide, 'affected_knee_extension_deficit_deg', '未测')}°；"
                f"{_value(wide, 'reference_knee_side')}侧膝屈曲 {_value(wide, 'reference_knee_flexion_deg', '未测')}°、伸展受限 {_value(wide, 'reference_knee_extension_deficit_deg', '未测')}°。"
                f"患侧髋屈曲 {_value(wide, 'affected_hip_flexion_deg', '未测')}°、伸展 {_value(wide, 'affected_hip_extension_deg', '未测')}°、内旋 {_value(wide, 'affected_hip_internal_rotation_deg', '未测')}°、外旋 {_value(wide, 'affected_hip_external_rotation_deg', '未测')}°；"
                f"踝膝靠墙 {_value(wide, 'affected_ankle_knee_to_wall_cm', '未测')} cm；测量方法 {_value(wide, 'method')}。\n"
                f"随访解释：{trend.interpretation}"
            )
        rom_rows = [{"joint": "膝关节", "comparison_role": "患侧", **rom_rows}]
    knee_affected = next((row for row in rom_rows if row.get("joint") == "膝关节" and row.get("comparison_role") == "患侧"), {})
    knee_reference = next((row for row in rom_rows if row.get("joint") == "膝关节" and row.get("comparison_role") == "健侧/对照侧"), {})
    hip = next((row for row in rom_rows if row.get("joint") == "髋关节"), {})
    ankle = next((row for row in rom_rows if row.get("joint") == "踝关节"), {})
    return (
        f"髌腱病评估：{_value(assessment, 'affected_side')}侧；症状持续 {_value(assessment, 'symptom_duration_weeks')} 周；"
        f"指定负荷活动“{_value(assessment, 'pain_activity_description')}”疼痛 VAS {_value(assessment, 'activity_pain_vas', _value(assessment, 'activity_pain_nrs'))}/10。"
        f"VISA-P {_value(assessment, 'visa_p_total')}/100（状态：{_value(assessment, 'visa_p_completion_status')}）。\n"
        f"ROM：患侧膝屈曲 {_value(knee_affected, 'flexion_deg', '未测')}°、伸展受限 {_value(knee_affected, 'extension_deficit_deg', '未测')}°；"
        f"对照侧膝屈曲 {_value(knee_reference, 'flexion_deg', '未测')}°、伸展受限 {_value(knee_reference, 'extension_deficit_deg', '未测')}°。"
        f"患侧髋屈曲 {_value(hip, 'flexion_deg', '未测')}°、伸展 {_value(hip, 'extension_deg', '未测')}°、内旋 {_value(hip, 'internal_rotation_deg', '未测')}°、外旋 {_value(hip, 'external_rotation_deg', '未测')}°；"
        f"踝膝靠墙 {_value(ankle, 'knee_to_wall_cm', '未测')} cm；测量方法 {_value(knee_affected, 'method')}。\n"
        f"随访解释：{trend.interpretation}"
    )


def medical_record_text_english(assessment: dict[str, Any], rom: dict[str, Any], trend: TrendSummary) -> str:
    """Concise English counterpart generated from the same structured record."""
    return (
        f"Patellar tendinopathy assessment: {_value(assessment, 'affected_side')} side; symptom duration {_value(assessment, 'symptom_duration_weeks')} weeks. "
        f"Load-related pain during {_value(assessment, 'pain_activity_description')}: VAS {_value(assessment, 'activity_pain_vas', _value(assessment, 'activity_pain_nrs'))}/10. "
        f"VISA-P {_value(assessment, 'visa_p_total')}/100.\n"
        f"ROM: affected knee flexion {_value(rom, 'affected_knee_flexion_deg', 'not measured')}°, extension deficit {_value(rom, 'affected_knee_extension_deficit_deg', 'not measured')}°; "
        f"contralateral knee flexion {_value(rom, 'reference_knee_flexion_deg', 'not measured')}°, extension deficit {_value(rom, 'reference_knee_extension_deficit_deg', 'not measured')}°. "
        f"Patellar tendon thickness on the affected side: {_value(assessment, 'ultrasound_tendon_thickness_mm', 'not recorded')} mm.\n"
        f"Follow-up interpretation: {trend.interpretation}"
    )
