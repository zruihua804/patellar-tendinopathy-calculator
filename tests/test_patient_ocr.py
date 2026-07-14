import unittest
from datetime import date

from patient_ocr import parse_patient_texts


class PatientScreenshotParserTests(unittest.TestCase):
    def test_parses_no_style_record_number(self):
        parsed = parse_patient_texts(["张春祺", "女", "36岁(1990-02-19)", "NO.SHJA09019"])
        self.assertEqual(parsed.name, "张春祺")
        self.assertEqual(parsed.medical_record_no, "SHJA09019")
        self.assertEqual(parsed.sex, "女")
        self.assertEqual(parsed.birth_date, date(1990, 2, 19))

    def test_parses_chinese_label_record_number(self):
        parsed = parse_patient_texts(["李明", "男", "门诊号：MZ-202401", "28岁 1998/01/02"])
        self.assertEqual(parsed.medical_record_no, "MZ-202401")
        self.assertEqual(parsed.sex, "男")

    def test_keeps_sex_for_human_confirmation_when_absent(self):
        parsed = parse_patient_texts(["徐一迪", "33岁(1993-01-02)", "NO.SHHP02263"])
        self.assertEqual(parsed.sex, "待确认")


if __name__ == "__main__":
    unittest.main()
