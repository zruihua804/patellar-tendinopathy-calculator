import unittest
from datetime import date

from feishu_adapter import FeishuConfig, FeishuConfigurationError, format_record_fields


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
