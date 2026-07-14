import unittest

from questionnaires import VISA_P_ACTIVITY_OPTIONS, VISA_P_TRAINING_OPTIONS, calculate_visa_p, visa_p_completion_status


class VisaPScoringTests(unittest.TestCase):
    def test_maximum_score_is_100(self):
        answers = {f"q{number}": 10 for number in range(1, 7)}
        answers.update({"q7": 10, "q8_case": "A", "q8_duration": 30})
        self.assertEqual(calculate_visa_p(answers), 100)

    def test_case_b_uses_its_own_score_map(self):
        answers = {f"q{number}": 5 for number in range(1, 7)}
        answers.update({"q7": 7, "q8_case": "B", "q8_duration": 14})
        self.assertEqual(calculate_visa_p(answers), 51)

    def test_incomplete_questionnaire_is_not_a_score(self):
        answers = {f"q{number}": 0 for number in range(1, 7)}
        answers.update({"q7": 0, "q8_case": "C", "q8_duration": None})
        self.assertIsNone(calculate_visa_p(answers))
        self.assertEqual(visa_p_completion_status(answers), "not completed")

    def test_source_option_sets_are_unchanged(self):
        self.assertEqual([score for _, score in VISA_P_ACTIVITY_OPTIONS], [0, 4, 7, 10])
        self.assertEqual([score for _, score in VISA_P_TRAINING_OPTIONS["C"][1]], [0, 2, 5, 7, 10])


if __name__ == "__main__":
    unittest.main()
