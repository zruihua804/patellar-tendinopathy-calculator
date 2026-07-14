import unittest

from voice import chinese_number_to_float, parse_rom_dictation


class VoiceParsingTests(unittest.TestCase):
    def test_parses_standard_therapist_rom_statement(self):
        parsed = parse_rom_dictation("左膝主动屈曲一百二十度，伸展受限五度，疼痛三分，量角器测量")
        self.assertEqual(parsed.values["affected_side"], "左")
        self.assertEqual(parsed.values["rom_mode"], "主动")
        self.assertEqual(parsed.values["knee_flexion_deg"], 120.0)
        self.assertEqual(parsed.values["knee_extension_deficit_deg"], 5.0)
        self.assertEqual(parsed.values["rom_pain_or_limit"], "语音记录：疼痛 NRS 3/10")
        self.assertEqual(parsed.values["rom_method"], "量角器")
        self.assertFalse(parsed.uncertainties)

    def test_parses_arabic_numbers_and_passive_mode(self):
        parsed = parse_rom_dictation("右膝被动屈曲 135 度，伸直差 0 度，倾角仪测量")
        self.assertEqual(parsed.values["affected_side"], "右")
        self.assertEqual(parsed.values["rom_mode"], "被动")
        self.assertEqual(parsed.values["knee_flexion_deg"], 135.0)
        self.assertEqual(parsed.values["knee_extension_deficit_deg"], 0.0)
        self.assertEqual(parsed.values["rom_method"], "倾角仪")

    def test_parses_plain_extension_and_colloquial_extension_deficit(self):
        plain = parse_rom_dictation("左膝主动屈曲120度，伸展0度，量角器测量")
        colloquial = parse_rom_dictation("右膝屈曲一百三十度，伸不开五度")
        self.assertEqual(plain.values["knee_extension_deficit_deg"], 0.0)
        self.assertEqual(colloquial.values["knee_extension_deficit_deg"], 5.0)

    def test_conflicting_modes_are_not_written(self):
        parsed = parse_rom_dictation("左膝主动屈曲一百二十度，被动屈曲一百三十度")
        self.assertNotIn("rom_mode", parsed.values)
        self.assertNotIn("knee_flexion_deg", parsed.values)
        self.assertTrue(parsed.uncertainties)

    def test_colloquial_hundred_numbers(self):
        self.assertEqual(chinese_number_to_float("一百二"), 120.0)
        self.assertEqual(chinese_number_to_float("一百零二"), 102.0)
        self.assertEqual(chinese_number_to_float("十五"), 15.0)


if __name__ == "__main__":
    unittest.main()
