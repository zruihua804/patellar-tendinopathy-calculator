import unittest
from datetime import date

from feishu import FeishuConfig, FeishuConfigurationError, format_record_fields


class FeishuAdapterTests(unittest.TestCase):
    def test_requires_user_owned_base_source(self):
        with self.assertRaises(FeishuConfigurationError):
            FeishuConfig.from_mapping({"app_id": "a", "app_secret": "b"})

    def test_formats_typed_fields_without_json_columns(self):
        fields = format_record_fields("assessments", {"assessment_id": "PT-A-1", "assessment_date": date(2026, 7, 14), "activity_pain_nrs": 3.5, "visa_p_total": 55, "visa_p_completion_status": "completed"})
        self.assertEqual(fields["评估ID"], "PT-A-1")
        self.assertEqual(fields["指定负荷疼痛NRS"], 3.5)
        self.assertEqual(fields["VISA-P总分"], 55.0)
        self.assertIsInstance(fields["评估日期"], int)

    def test_formats_new_rom_and_vas_fields(self):
        fields = format_record_fields(
            "rom",
            {
                "rom_id": "PT-ROM-1",
                "assessment_id": "PT-A-1",
                "joint": "髋关节",
                "comparison_role": "患侧同侧",
                "internal_rotation_deg": 35,
                "external_rotation_deg": 45,
                "knee_to_wall_cm": 10,
            },
        )
        self.assertEqual(fields["关节"], "髋关节")
        self.assertEqual(fields["内旋（度）"], 35.0)
        self.assertEqual(fields["膝靠墙距离（cm）"], 10.0)


if __name__ == "__main__":
    unittest.main()
