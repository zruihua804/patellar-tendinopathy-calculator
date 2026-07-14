"""In-process screenshot OCR. Uploaded images are never written to disk."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from io import BytesIO
import re

import numpy as np
from PIL import Image


class OCRUnavailableError(RuntimeError):
    """Raised when the optional local OCR engine is not installed."""


@dataclass(frozen=True)
class PatientScreenshotData:
    name: str = ""
    medical_record_no: str = ""
    sex: str = "待确认"
    age: int | None = None
    birth_date: date | None = None
    recognized_text: tuple[str, ...] = ()


MEDICAL_RECORD_PATTERNS = (
    re.compile(r"\bN[O0]\s*[.:：#]?[\s]*([A-Za-z0-9-]{4,})", re.IGNORECASE),
    re.compile(r"(?:病历号|门诊号|住院号)\s*[：:#]?\s*([A-Za-z0-9-]{4,})", re.IGNORECASE),
)
AGE_PATTERN = re.compile(r"(\d{1,3})\s*岁")
DATE_PATTERN = re.compile(
    r"(?<!\d)(?P<year>(?:19|20)\d{2})\s*(?:[-/.]|年)\s*"
    r"(?P<month>\d{1,2})\s*(?:[-/.]|月)\s*(?P<day>\d{1,2})(?:日)?"
)
CHINESE_NAME_PATTERN = re.compile(r"[\u4e00-\u9fff·]{2,8}")


@lru_cache(maxsize=1)
def _ocr_engine():
    try:
        from rapidocr import RapidOCR
    except ImportError as exc:
        raise OCRUnavailableError(f"本地 OCR 组件未就绪：{exc}") from exc
    return RapidOCR()


def parse_patient_texts(texts: list[str] | tuple[str, ...]) -> PatientScreenshotData:
    cleaned = tuple(text.strip() for text in texts if text and text.strip())
    joined = " ".join(cleaned)

    record_no = ""
    for pattern in MEDICAL_RECORD_PATTERNS:
        match = pattern.search(joined)
        if match:
            record_no = match.group(1).upper()
            break

    age_match = AGE_PATTERN.search(joined)
    age = int(age_match.group(1)) if age_match else None
    if age is not None and not 0 < age < 130:
        age = None

    birth_date = None
    date_match = DATE_PATTERN.search(joined)
    if date_match:
        try:
            birth_date = date(int(date_match.group("year")), int(date_match.group("month")), int(date_match.group("day")))
        except ValueError:
            birth_date = None

    sex = "待确认"
    if any("女" in text and "男性" not in text for text in cleaned):
        sex = "女"
    elif any("男" in text for text in cleaned):
        sex = "男"

    name = ""
    excluded = {"患者信息", "门诊病历", "女性", "男性", "病历号", "门诊号", "住院号"}
    for text in cleaned:
        compact = re.sub(r"\s+", "", text)
        if CHINESE_NAME_PATTERN.fullmatch(compact) and compact not in excluded:
            name = compact
            break

    return PatientScreenshotData(name, record_no, sex, age, birth_date, cleaned)


def extract_patient_screenshot_data(image_bytes: bytes) -> PatientScreenshotData:
    image = Image.open(BytesIO(image_bytes)).convert("RGB")
    result = _ocr_engine()(np.asarray(image))
    texts = tuple(getattr(result, "txts", ()) or ())
    return parse_patient_texts(texts)
