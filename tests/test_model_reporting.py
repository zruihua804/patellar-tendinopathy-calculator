import unittest

from model import return_to_sport_reference, trend_summary
from reporting import medical_record_text, medical_record_text_english, patient_report


class ModelAndReportingTests(unittest.TestCase):
    def test_mcid_interpretation_is_not_a_recovery_guarantee(self):
        summary = trend_summary(50, 63, 5, 3)
        self.assertEqual(summary.visa_p_delta, 13)
        self.assertIn("仍需结合", summary.interpretation)

    def test_trend_accepts_feishu_number_strings(self):
        summary = trend_summary("50", "63", "5", "3")
        self.assertEqual(summary.visa_p_delta, 13)
        self.assertEqual(summary.pain_delta, 2.0)

    def test_report_uses_structured_rom_values(self):
        assessment = {"affected_side": "左", "symptom_duration_weeks": 12, "pain_activity_description": "跳跃", "activity_pain_nrs": 4, "visa_p_total": 55, "visa_p_completion_status": "completed"}
        rom = {"mode": "主动", "flexion_deg": 130, "extension_deficit_deg": 5, "pain_or_limit": "末端疼痛", "method": "量角器"}
        report = medical_record_text(assessment, rom, trend_summary(50, 55, 5, 4))
        self.assertIn("伸展受限 5°", report)
        self.assertIn("量角器", report)
        self.assertIn("不替代", patient_report(assessment, trend_summary(50, 55, 5, 4)))

    def test_report_uses_wide_rom_row(self):
        assessment = {"affected_side": "左", "symptom_duration_weeks": 12, "pain_activity_description": "跳跃", "activity_pain_nrs": 4, "visa_p_total": 55, "visa_p_completion_status": "completed"}
        rom = {"affected_knee_flexion_deg": 130, "affected_knee_extension_deficit_deg": 5, "reference_knee_side": "右", "reference_knee_flexion_deg": 135, "reference_knee_extension_deficit_deg": 0, "affected_hip_flexion_deg": 120, "affected_hip_extension_deg": 20, "affected_hip_internal_rotation_deg": 35, "affected_hip_external_rotation_deg": 45, "affected_ankle_knee_to_wall_cm": 10, "method": "量角器"}
        report = medical_record_text(assessment, rom, trend_summary(50, 55, 5, 4))
        self.assertIn("右侧膝屈曲 135°", report)
        self.assertIn("患侧髋屈曲 120°", report)

    def test_english_note_uses_same_structured_values(self):
        assessment = {"affected_side": "左", "symptom_duration_weeks": 12, "pain_activity_description": "jump landing", "activity_pain_vas": 3, "visa_p_total": 62, "ultrasound_tendon_thickness_mm": 5.1}
        rom = {"affected_knee_flexion_deg": 130, "affected_knee_extension_deficit_deg": 0, "reference_knee_flexion_deg": 135, "reference_knee_extension_deficit_deg": 0}
        note = medical_record_text_english(assessment, rom, trend_summary(50, 62, 5, 3))
        self.assertIn("VISA-P 62/100", note)
        self.assertIn("5.1 mm", note)

    def test_return_to_sport_reference_uses_stable_literature_anchors(self):
        reference = return_to_sport_reference(
            visa_p_total=None,
            activity_pain_vas=None,
            symptom_duration_weeks=12,
            adherence_percent=50,
        )
        self.assertEqual(reference.regular_rehab_percent, 43)
        self.assertEqual(reference.incomplete_rehab_percent, 27)

    def test_return_to_sport_reference_changes_modestly_for_current_state(self):
        reference = return_to_sport_reference(
            visa_p_total=85,
            activity_pain_vas=2,
            symptom_duration_weeks=12,
            adherence_percent=80,
        )
        self.assertEqual(reference.regular_rehab_percent, 57)
        self.assertEqual(reference.incomplete_rehab_percent, 41)


if __name__ == "__main__":
    unittest.main()
