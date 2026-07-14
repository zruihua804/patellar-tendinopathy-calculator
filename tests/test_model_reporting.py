import unittest

from model import trend_summary
from reporting import medical_record_text, patient_report


class ModelAndReportingTests(unittest.TestCase):
    def test_mcid_interpretation_is_not_a_recovery_guarantee(self):
        summary = trend_summary(50, 63, 5, 3)
        self.assertEqual(summary.visa_p_delta, 13)
        self.assertIn("仍需结合", summary.interpretation)

    def test_report_uses_structured_rom_values(self):
        assessment = {"affected_side": "左", "symptom_duration_weeks": 12, "pain_activity_description": "跳跃", "activity_pain_nrs": 4, "visa_p_total": 55, "visa_p_completion_status": "completed"}
        rom = {"mode": "主动", "flexion_deg": 130, "extension_deficit_deg": 5, "pain_or_limit": "末端疼痛", "method": "量角器"}
        report = medical_record_text(assessment, rom, trend_summary(50, 55, 5, 4))
        self.assertIn("伸展受限 5°", report)
        self.assertIn("量角器", report)
        self.assertIn("不替代", patient_report(assessment, trend_summary(50, 55, 5, 4)))


if __name__ == "__main__":
    unittest.main()
