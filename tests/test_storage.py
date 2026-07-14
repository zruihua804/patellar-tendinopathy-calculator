import tempfile
import unittest
from pathlib import Path

import pandas as pd

from storage import DuplicateRecordError, LocalStorage


class LocalStorageTests(unittest.TestCase):
    def test_repeated_save_updates_same_row(self):
        with tempfile.TemporaryDirectory() as directory:
            store = LocalStorage(directory)
            self.assertEqual(store.upsert_record("patients", {"patient_id": "PT-P-1", "name": "甲"})[0], "created")
            self.assertEqual(store.upsert_record("patients", {"patient_id": "PT-P-1", "name": "乙"})[0], "updated")
            saved = pd.read_csv(Path(directory) / "patients.csv")
            self.assertEqual(len(saved), 1)
            self.assertEqual(saved.loc[0, "name"], "乙")

    def test_historical_duplicates_are_not_deleted(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "patients.csv"
            pd.DataFrame([{"patient_id": "PT-P-1"}, {"patient_id": "PT-P-1"}]).to_csv(path, index=False)
            with self.assertRaises(DuplicateRecordError):
                LocalStorage(directory).upsert_record("patients", {"patient_id": "PT-P-1", "name": "甲"})


if __name__ == "__main__":
    unittest.main()
