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


if __name__ == "__main__":
    unittest.main()
