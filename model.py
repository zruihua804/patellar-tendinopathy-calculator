"""Versioned decision support and literature communication references for patellar tendinopathy."""

from __future__ import annotations

from dataclasses import dataclass


MODEL_VERSION = "PT-v0.2-followup-visual-2026-07-15"


@dataclass(frozen=True)
class TrendSummary:
    visa_p_delta: int | None
    pain_delta: float | None
    interpretation: str


@dataclass(frozen=True)
class ReturnToSportReference:
    regular_rehab_percent: int
    incomplete_rehab_percent: int
    drivers: tuple[str, ...]


def trend_summary(
    baseline_visa_p: int | None,
    current_visa_p: int | None,
    baseline_pain: float | None,
    current_pain: float | None,
) -> TrendSummary:
    visa_delta = None if baseline_visa_p is None or current_visa_p is None else current_visa_p - baseline_visa_p
    pain_delta = None if baseline_pain is None or current_pain is None else baseline_pain - current_pain
    if visa_delta is None:
        interpretation = "VISA-P 尚未同时在基线和当前时间点完成，不能计算功能变化。"
    elif visa_delta >= 13:
        interpretation = "VISA-P 较基线提高至少 13 分，提示有临床意义的功能改善；仍需结合疼痛、专项负荷和医生评估。"
    elif visa_delta > 0:
        interpretation = "VISA-P 有改善，但尚未达到 13 分的解释性变化参考值。"
    elif visa_delta == 0:
        interpretation = "VISA-P 与基线无变化；请核对负荷、依从性、诊断和症状场景。"
    else:
        interpretation = "VISA-P 较基线下降；建议由临床团队复评，不能根据本工具自动调整治疗。"
    return TrendSummary(visa_delta, pain_delta, interpretation)


def evidence_scenario_summary() -> dict[str, str | int]:
    """Population evidence for a visual comparison, never an individual forecast."""
    return {
        "title": "24 周康复方案对比（研究总体）",
        "population": "76 名以慢性髌腱病为主、每周至少运动 3 次的运动人群；不是对任一患者的个人预测。",
        "structured_loading_label": "结构化渐进肌腱负荷",
        "comparator_label": "疼痛诱发的单一离心训练",
        "structured_loading_return_rate": 43,
        "comparator_return_rate": 27,
        "structured_loading_visa_change": 28,
        "comparator_visa_change": 18,
        "difference": "研究中，渐进负荷方案的伤前运动水平回归率为 43%，对照方案为 27%；差异趋势未达到统计学显著。不能把这两个数当作“规律”与“不规律”康复的个人概率。",
        "source": "Breda SJ et al. Br J Sports Med. 2021;55:501–509. DOI:10.1136/bjsports-2020-103403",
    }


def return_to_sport_reference(
    *,
    visa_p_total: int | None,
    activity_pain_vas: float | int | None,
    symptom_duration_weeks: int | float | None,
    adherence_percent: float | int | None,
) -> ReturnToSportReference:
    """Literature-calibrated 24-week communication reference, not a validated equation.

    The anchors are the 24-week return-to-preinjury-sport proportions in the
    progressive tendon-loading and eccentric-comparator arms of Breda et al.
    Modifiers are intentionally small and transparent; they provide an
    individual communication aid while preserving the underlying study bounds.
    """
    adjustment = 0
    drivers: list[str] = []
    if visa_p_total is not None:
        if visa_p_total >= 80:
            adjustment += 6
            drivers.append("当前功能评分较高")
        elif visa_p_total <= 50:
            adjustment -= 6
            drivers.append("当前功能评分仍受限")
    if activity_pain_vas is not None:
        if float(activity_pain_vas) <= 3:
            adjustment += 4
            drivers.append("指定负荷疼痛较低")
        elif float(activity_pain_vas) >= 6:
            adjustment -= 4
            drivers.append("指定负荷疼痛仍较高")
    if symptom_duration_weeks is not None and float(symptom_duration_weeks) >= 52:
        adjustment -= 4
        drivers.append("病程较长")
    if adherence_percent is not None:
        if float(adherence_percent) >= 70:
            adjustment += 4
            drivers.append("近期康复执行度较高")
        elif float(adherence_percent) < 40:
            adjustment -= 4
            drivers.append("近期康复执行度偏低")
    regular = max(15, min(70, 43 + adjustment))
    incomplete = max(8, min(60, 27 + adjustment))
    return ReturnToSportReference(regular, incomplete, tuple(drivers))
