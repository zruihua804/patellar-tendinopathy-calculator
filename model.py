"""Versioned, non-probabilistic decision support for patellar tendinopathy."""

from __future__ import annotations

from dataclasses import dataclass


MODEL_VERSION = "PT-v0.1-trend-only-2026-07-14"


@dataclass(frozen=True)
class TrendSummary:
    visa_p_delta: int | None
    pain_delta: float | None
    interpretation: str


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
    """Population evidence only; deliberately no patient-specific probability."""
    return {
        "title": "研究总体中的康复比较（不是个人预后）",
        "population": "一项以慢性髌腱病为主、临床诊断且超声证实的 76 人随机试验，随访 24 周。",
        "structured_loading": "渐进肌腱负荷治疗组：VISA-P 平均改善 28 分。",
        "eccentric_only": "单纯离心训练组：VISA-P 平均改善 18 分。",
        "difference": "调整后组间差异 9 分（95% CI 1–16）。该结果不能转换成任何个人恢复率或保证恢复时间。",
        "source": "Breda SJ et al. Br J Sports Med. 2021;55:501–509. DOI:10.1136/bjsports-2020-103403",
    }
