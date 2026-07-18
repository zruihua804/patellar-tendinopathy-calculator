"""Synthetic end-to-end persistence check; no patient data is used or retained."""

from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

import pandas as pd

from domain import patient_id_from_record
from questionnaires import calculate_visa_p
from storage import LocalStorage, TABLE_FILES


class SyntheticWorkflowTests(unittest.TestCase):
    def test_complete_assessment_is_saved_and_upserted_across_all_tables(self):
        """Exercise the clinic record contract with a fully synthetic encounter."""
        with tempfile.TemporaryDirectory() as directory:
            store = LocalStorage(directory)
            patient_id = patient_id_from_record("SYNTHETIC-001", "演练患者")
            score = calculate_visa_p(
                {
                    "q1": 10,
                    "q2": 10,
                    "q3": 10,
                    "q4": 10,
                    "q5": 10,
                    "q6": 10,
                    "q7": 10,
                    "q8_case": "A",
                    "q8_duration": 30,
                }
            )
            self.assertEqual(score, 100)

            records = {
                "patients": {
                    "patient_id": patient_id,
                    "medical_record_no": "SYNTHETIC-001",
                    "name": "演练患者",
                    "consent_status": "synthetic-test-only",
                },
                "assessments": {
                    "patient_id": patient_id,
                    "timepoint": "基线",
                    "assessment_date": date(2026, 7, 14),
                    "visa_p_total": score,
                    "visa_p_completion_status": "completed",
                },
                "rom": {
                    "patient_id": patient_id,
                    "timepoint": "基线",
                    "measured_at": date(2026, 7, 14),
                    "affected_knee_flexion_deg": 135,
                    "reference_knee_flexion_deg": 135,
                },
                "followup_summary": {
                    "patient_id": patient_id,
                    "latest_timepoint": "基线",
                    "latest_visa_p_total": score,
                },
            }

            for table, record in records.items():
                self.assertEqual(store.upsert_record(table, record)[0], "created")
                saved = pd.read_csv(Path(directory) / TABLE_FILES[table], dtype=object)
                self.assertEqual(len(saved), 1)

            amended_assessment = {**records["assessments"], "visa_p_total": 92}
            self.assertEqual(store.upsert_record("assessments", amended_assessment)[0], "updated")
            saved_assessment = pd.read_csv(Path(directory) / TABLE_FILES["assessments"], dtype=object)
            self.assertEqual(len(saved_assessment), 1)
            self.assertEqual(saved_assessment.loc[0, "visa_p_total"], "92")

            later_same_node = {**records["assessments"], "assessment_date": date(2026, 7, 21), "ultrasound_tendon_thickness_mm": 5.2}
            self.assertEqual(store.upsert_record("assessments", later_same_node)[0], "updated")
            saved_assessment = pd.read_csv(Path(directory) / TABLE_FILES["assessments"], dtype=object)
            self.assertEqual(len(saved_assessment), 1)
            self.assertEqual(saved_assessment.loc[0, "ultrasound_tendon_thickness_mm"], "5.2")


if __name__ == "__main__":
    unittest.main()
