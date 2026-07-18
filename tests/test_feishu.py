import unittest
from datetime import date

from feishu_adapter import FeishuBitableClient, FeishuConfig, FeishuConfigurationError, SPEC_BY_KEY, format_record_fields


class FeishuAdapterTests(unittest.TestCase):
    def test_requires_user_owned_base_source(self):
        with self.assertRaises(FeishuConfigurationError):
            FeishuConfig.from_mapping({"app_id": "a", "app_secret": "b"})

    def test_formats_typed_fields_without_json_columns(self):
        fields = format_record_fields("assessments", {"patient_id": "PT-P-1", "timepoint": "基线", "assessment_date": date(2026, 7, 14), "activity_pain_vas": 3.5, "visa_p_total": 55, "visa_p_completion_status": "completed"})
        self.assertEqual(fields["患者ID"], "PT-P-1")
        self.assertEqual(fields["指定负荷疼痛VAS"], 3.5)
        self.assertEqual(fields["VISA-P总分"], 55.0)
        self.assertIsInstance(fields["评估日期"], int)

    def test_assessment_identity_is_patient_and_timepoint(self):
        self.assertEqual(SPEC_BY_KEY["assessments"].unique_keys, ("patient_id", "timepoint"))
        self.assertEqual(SPEC_BY_KEY["rom"].unique_keys, ("patient_id", "timepoint"))

    def test_existing_table_ids_is_read_only_and_requires_all_standard_tables(self):
        config = FeishuConfig("app-id", "secret", "app-token")
        client = FeishuBitableClient(config)
        client.list_tables = lambda _: [
            {"name": "患者主表", "table_id": "tbl-patients"},
            {"name": "髌腱病评估表", "table_id": "tbl-assessments"},
            {"name": "ROM 综合评估", "table_id": "tbl-rom"},
        ]
        self.assertEqual(
            client.existing_table_ids("app-token"),
            {"patients": "tbl-patients", "assessments": "tbl-assessments", "rom": "tbl-rom"},
        )

    def test_formats_ultrasound_followup_fields(self):
        fields = format_record_fields(
            "assessments",
            {
                "patient_id": "PT-P-1",
                "timepoint": "6周",
                "ultrasound_tendon_thickness_mm": 5.2,
                "ultrasound_date": date(2026, 8, 25),
                "ultrasound_note": "同一测量位置复查",
            },
        )
        self.assertEqual(fields["患侧髌腱厚度（mm）"], 5.2)
        self.assertIsInstance(fields["超声检查日期"], int)
        self.assertEqual(fields["超声备注"], "同一测量位置复查")

    def test_formats_wide_rom_fields(self):
        fields = format_record_fields(
            "rom",
            {
                "patient_id": "PT-P-1",
                "timepoint": "基线",
                "measured_at": date(2026, 7, 14),
                "affected_side": "左",
                "affected_knee_flexion_deg": 135,
                "reference_knee_flexion_deg": 140,
                "affected_hip_internal_rotation_deg": 35,
                "affected_ankle_knee_to_wall_cm": 10,
            },
        )
        self.assertEqual(fields["患侧"], "左")
        self.assertEqual(fields["患侧膝屈曲（度）"], 135.0)
        self.assertEqual(fields["健侧膝屈曲（度）"], 140.0)
        self.assertEqual(fields["患侧髋内旋（度）"], 35.0)
        self.assertEqual(fields["患侧踝膝靠墙（cm）"], 10.0)


if __name__ == "__main__":
    unittest.main()
