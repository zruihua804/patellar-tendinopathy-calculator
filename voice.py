"""Deterministic parsing for short, therapist-initiated ROM dictation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


_NUMBER_CHARS = "0-9０-９零〇一二两三四五六七八九十百点."
_CN_DIGITS = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


@dataclass(frozen=True)
class VoiceParseResult:
    """Structured values pending clinician confirmation; raw text is never persisted."""

    transcript: str
    values: dict[str, Any]
    uncertainties: tuple[str, ...]


def chinese_number_to_float(raw: str) -> float | None:
    """Parse common spoken Chinese angle/NRS numbers without an LLM dependency."""
    value = raw.strip().replace("－", "-").translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    if not value:
        return None
    if re.fullmatch(r"\d+(?:\.\d+)?", value):
        return float(value)
    if "点" in value:
        whole, decimal = value.split("点", 1)
        whole_number = chinese_number_to_float(whole)
        decimal_digits = "".join(str(_CN_DIGITS[char]) for char in decimal if char in _CN_DIGITS)
        return float(f"{int(whole_number or 0)}.{decimal_digits}") if decimal_digits else whole_number
    if any(char not in _CN_DIGITS and char not in {"十", "百"} for char in value):
        return None

    # In ordinary clinical dictation, “一百二” means 120, whereas “一百零二” is 102.
    if "百" in value and "十" not in value and "零" not in value and "〇" not in value:
        before_hundred, after_hundred = value.split("百", 1)
        if len(after_hundred) == 1 and after_hundred in _CN_DIGITS:
            hundreds = _CN_DIGITS.get(before_hundred[-1], 1) if before_hundred else 1
            return float(hundreds * 100 + _CN_DIGITS[after_hundred] * 10)

    total = 0
    current = 0
    for char in value:
        if char in _CN_DIGITS:
            current = _CN_DIGITS[char]
        elif char == "十":
            total += (current or 1) * 10
            current = 0
        elif char == "百":
            total += (current or 1) * 100
            current = 0
    return float(total + current)


def _number_matches(pattern: str, text: str) -> list[float]:
    matches = re.findall(pattern, text)
    parsed = [chinese_number_to_float(match) for match in matches]
    return [number for number in parsed if number is not None]


def _single_value(label: str, values: list[float], warnings: list[str]) -> float | None:
    unique = list(dict.fromkeys(values))
    if len(unique) > 1:
        warnings.append(f"语音中识别到多个{label}数值，未自动写入。请在手工表单中确认。")
        return None
    return unique[0] if unique else None


def parse_rom_dictation(transcript: str) -> VoiceParseResult:
    """Extract short Chinese knee-ROM dictation into reviewable form fields.

    The parser deliberately refuses conflicting values instead of guessing. It is not
    a clinical decision engine and the caller must require explicit confirmation.
    """
    clean = re.sub(r"\s+", " ", transcript.strip())
    warnings: list[str] = []
    values: dict[str, Any] = {}
    if not clean:
        return VoiceParseResult("", values, ("未收到语音文字；请改用手工录入。",))

    sides = list(dict.fromkeys(re.findall(r"(左|右|双侧|两侧)(?:侧)?(?:膝|腿)?", clean)))
    if len(sides) == 1:
        values["affected_side"] = "双侧" if sides[0] in {"双侧", "两侧"} else sides[0]
    elif len(sides) > 1:
        warnings.append("语音中同时出现多个患侧，未自动写入患侧。")

    modes: list[str] = []
    if "主动" in clean:
        modes.append("主动")
    if "被动" in clean:
        modes.append("被动")
    if len(modes) == 1:
        values["rom_mode"] = modes[0]
    elif len(modes) > 1:
        warnings.append("语音中同时出现主动和被动测量，未自动覆盖当前测量模式。")

    flexion = _single_value(
        "屈曲角度",
        _number_matches(rf"(?:屈曲|屈膝|弯曲)(?:角度)?(?:为|是|约|大约)?\s*([{_NUMBER_CHARS}]+)\s*(?:度|°)", clean),
        warnings,
    )
    if flexion is not None:
        if 0 <= flexion <= 160:
            values["knee_flexion_deg"] = flexion
        else:
            warnings.append("屈曲角度超出本工具允许的 0–160° 范围，未自动写入。")

    extension = _single_value(
        "伸展受限角度",
        _number_matches(
            rf"(?:伸不直|伸不开|伸展(?:受限|不足|差|缺失|活动度)?|伸直(?:受限|不足|差|缺失)?)(?:为|是|约|大约)?\s*([{_NUMBER_CHARS}]+)\s*(?:度|°)",
            clean,
        ),
        warnings,
    )
    if extension is not None:
        if 0 <= extension <= 45:
            values["knee_extension_deficit_deg"] = extension
        else:
            warnings.append("伸展受限角度超出本工具允许的 0–45° 范围，未自动写入。")

    pain = _single_value(
        "疼痛评分",
        _number_matches(rf"(?:疼痛|痛)(?:评分|NRS)?(?:为|是|约|大约)?\s*([{_NUMBER_CHARS}]+)\s*(?:分|/10)?", clean),
        warnings,
    )
    if pain is not None:
        if 0 <= pain <= 10:
            values["rom_pain_or_limit"] = f"语音记录：疼痛 NRS {pain:g}/10"
        else:
            warnings.append("疼痛 NRS 超出 0–10 范围，未自动写入。")

    methods = [method for method in ("量角器", "倾角仪", "目测") if method in clean]
    if len(methods) == 1:
        values["rom_method"] = methods[0]
    elif len(methods) > 1:
        warnings.append("语音中出现多个测量方法，未自动写入。")

    if not values and not warnings:
        warnings.append("未识别到可写入的 ROM 字段。示例：左膝主动屈曲一百二十度，伸展受限五度，量角器测量。")
    return VoiceParseResult(clean, values, tuple(warnings))
