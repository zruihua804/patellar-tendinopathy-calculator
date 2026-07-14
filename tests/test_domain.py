import unittest
from datetime import date

from domain import assessment_identity, clinical_warnings, stable_id


class DomainTests(unittest.TestCase):
    def test_stable_id_is_reproducible(self):
        self.assertEqual(stable_id("PT-A", "x", "基线"), stable_id("PT-A", "x", "基线"))

    def test_assessment_identity_changes_by_timepoint(self):
        baseline = assessment_identity("PT-P-A", "左", "基线", date(2026, 7, 14))
        week6 = assessment_identity("PT-P-A", "左", "6周", date(2026, 8, 25))
        self.assertEqual(baseline.episode_id, week6.episode_id)
        self.assertNotEqual(baseline.assessment_id, week6.assessment_id)

    def test_red_flag_and_missing_scale_are_explicit(self):
        messages = clinical_warnings(red_flag_present=True, diagnostic_confidence="待鉴别", visa_p_total=None, activity_pain_nrs=3)
        self.assertEqual(len(messages), 3)


if __name__ == "__main__":
    unittest.main()
