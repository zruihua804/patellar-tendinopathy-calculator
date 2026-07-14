"""Streamlit bridge for browser-native cloud speech recognition.

The component has no audio upload endpoint. A supported browser sends a short
push-to-talk utterance to its configured cloud speech service and returns only the
final text to Streamlit for clinician review.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import streamlit.components.v1 as components


_component = components.declare_component(
    "cloud_rom_voice_entry",
    path=str(Path(__file__).parent / "voice_component" / "frontend"),
)


def cloud_rom_voice_input(*, key: str, language: str = "zh-CN") -> dict[str, Any] | None:
    """Render a client-side, push-to-talk control and return its final event only."""
    value = _component(
        key=key,
        language=language,
        instruction="按住说话：例如“左膝主动屈曲一百二十度，伸展受限五度，量角器测量”。松开后仅返回文字供确认。",
        default=None,
    )
    return value if isinstance(value, dict) else None
