"""Local development storage with stable-ID upserts and duplicate detection."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


TABLE_FILES = {
    "patients": "patients.csv",
    "episodes": "episodes.csv",
    "assessments": "assessments.csv",
    "rom": "rom.csv",
    "rehab": "rehab.csv",
    "followup_summary": "followup_summary.csv",
    "reports": "reports.csv",
}
PRIMARY_KEY_BY_TABLE = {
    "patients": "patient_id",
    "episodes": "episode_id",
    "assessments": "assessment_id",
    "rom": "rom_id",
    "rehab": "rehab_id",
    "followup_summary": "episode_id",
    "reports": "report_id",
}


class DuplicateRecordError(RuntimeError):
    pass


class LocalStorage:
    def __init__(self, data_dir: Path | str = "data") -> None:
        self.data_dir = Path(data_dir)

    def _path(self, table: str) -> Path:
        if table not in TABLE_FILES:
            raise ValueError(f"未知数据表：{table}")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        return self.data_dir / TABLE_FILES[table]

    def upsert_record(self, table: str, record: dict[str, Any]) -> tuple[str, Path]:
        key = PRIMARY_KEY_BY_TABLE[table]
        key_value = record.get(key)
        if key_value in (None, ""):
            raise ValueError(f"缺少稳定临床 ID：{key}")
        path = self._path(table)
        row = {**record, "saved_at": datetime.now().isoformat(timespec="seconds")}
        if not path.exists():
            pd.DataFrame([row]).to_csv(path, index=False)
            return "created", path

        frame = pd.read_csv(path, dtype=object).fillna("")
        for column in row:
            if column not in frame.columns:
                frame[column] = ""
        matches = frame.index[frame[key].astype(str) == str(key_value)].tolist()
        if len(matches) > 1:
            raise DuplicateRecordError(f"发现 {len(matches)} 条相同 {key} 的历史记录；请人工核查，系统不会自动删除。")
        if not matches:
            pd.concat([frame, pd.DataFrame([row])], ignore_index=True).to_csv(path, index=False)
            return "created", path

        for column, value in row.items():
            frame.at[matches[0], column] = value
        frame.to_csv(path, index=False)
        return "updated", path

    def list_records(self, table: str) -> list[dict[str, Any]]:
        """Return saved rows for a clinician-facing longitudinal view.

        This is only a prototype fallback; the deployed application prefers the
        user-owned Feishu Base as the persistent source of follow-up history.
        """
        path = self._path(table)
        if not path.exists():
            return []
        return pd.read_csv(path, dtype=object).fillna("").to_dict(orient="records")


DEFAULT_STORAGE = LocalStorage(Path(__file__).parent / "data")
