"""Authorized Chinese VISA-P content and deterministic scoring."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class VisaPItem:
    key: str
    text: str
    low_label: str
    high_label: str
    maximum: int


# Source: clinical-user supplied and authorized VISA-P Chinese questionnaire
# (VISA-P中文版量表.docx, confirmed 2026-07-14). Keep source wording/version together.
VISA_P_SOURCE_VERSION = "VISA-P中文版量表（临床用户授权，2026-07-14）"

VISA_P_ITEMS: tuple[VisaPItem, ...] = (
    VisaPItem("q1", "您能够无疼痛坐多长时间？", "0分钟", "100分钟", 10),
    VisaPItem("q2", "您以正常步态下楼梯时，膝关节是否疼痛？", "剧烈疼痛", "无疼痛", 10),
    VisaPItem("q3", "在非负重情况下主动完全伸直膝关节时，膝关节是否疼痛？", "剧烈疼痛", "无疼痛", 10),
    VisaPItem("q4", "完全负重弓步动作时，膝关节是否疼痛？", "剧烈疼痛", "无疼痛", 10),
    VisaPItem("q5", "您下蹲时是否存在困难？", "无法完成", "无任何困难", 10),
    VisaPItem("q6", "完成10次单腿跳跃过程中或结束后，是否出现疼痛？", "剧烈疼痛/无法完成", "无疼痛", 10),
)

VISA_P_ACTIVITY_OPTIONS: tuple[tuple[str, int], ...] = (
    ("完全没有参加", 0),
    ("调整后的训练 ± 调整后的比赛", 4),
    ("完整训练 ± 比赛，但未达到症状出现前水平", 7),
    ("达到症状出现前或更高水平参加比赛", 10),
)

VISA_P_TRAINING_OPTIONS: dict[str, tuple[str, tuple[tuple[str, int], ...]]] = {
    "A": (
        "如果运动时完全无疼痛，您可以训练/练习多长时间？",
        (("无法进行", 0), ("1–5分钟", 7), ("6–10分钟", 14), ("11–15分钟", 21), (">15分钟", 30)),
    ),
    "B": (
        "如果运动时有疼痛，但疼痛不会导致您停止训练，您可以训练/练习多长时间？",
        (("无法进行", 0), ("1–5分钟", 4), ("6–10分钟", 10), ("11–15分钟", 14), (">15分钟", 20)),
    ),
    "C": (
        "如果运动时疼痛导致您无法完成训练，您在停止前可以训练/练习多长时间？",
        (("无法进行", 0), ("1–5分钟", 2), ("6–10分钟", 5), ("11–15分钟", 7), (">15分钟", 10)),
    ),
}


def item_score_labels(item: VisaPItem) -> list[str]:
    """Return labelled options in the source order, retaining end-point labels."""
    return [
        f"{score}分" + (f"（{item.low_label}）" if score == 0 else f"（{item.high_label}）" if score == item.maximum else "")
        for score in range(item.maximum + 1)
    ]


def score_from_label(label: str) -> int:
    return int(label.split("分", 1)[0])


def training_option_label(label: str, score: int) -> str:
    return f"{label}（{score}分）"


def calculate_visa_p(answers: Mapping[str, object]) -> int | None:
    """Calculate VISA-P only when every required answer is present and valid."""
    required = [item.key for item in VISA_P_ITEMS] + ["q7", "q8_case", "q8_duration"]
    if any(answers.get(key) in (None, "") for key in required):
        return None

    try:
        primary_total = sum(int(answers[item.key]) for item in VISA_P_ITEMS)
    except (TypeError, ValueError):
        return None
    if any(not 0 <= int(answers[item.key]) <= 10 for item in VISA_P_ITEMS):
        return None

    q7 = int(answers["q7"])
    if q7 not in {score for _, score in VISA_P_ACTIVITY_OPTIONS}:
        return None

    case = str(answers["q8_case"])
    if case not in VISA_P_TRAINING_OPTIONS:
        return None
    q8 = int(answers["q8_duration"])
    if q8 not in {score for _, score in VISA_P_TRAINING_OPTIONS[case][1]}:
        return None

    total = primary_total + q7 + q8
    return total if 0 <= total <= 100 else None


def visa_p_completion_status(answers: Mapping[str, object]) -> str:
    return "completed" if calculate_visa_p(answers) is not None else "not completed"
