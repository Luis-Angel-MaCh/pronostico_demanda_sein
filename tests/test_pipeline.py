import unittest

import numpy as np

from src.config import TEST_START, TRAIN_END
from src.data.load_data import load_dataset
from src.features.build_features import build_matrix, prepare_arrays


class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.df, cls.summary = load_dataset()

    def test_time_series_is_ordered_and_unique(self):
        self.assertTrue(self.df["fecha"].is_monotonic_increasing)
        self.assertEqual(self.df["fecha"].duplicated().sum(), 0)

    def test_train_precedes_validation(self):
        self.assertLess(np.datetime64(TRAIN_END), np.datetime64(TEST_START))

    def test_features_use_past_actuals(self):
        arrays = prepare_arrays(self.df)
        target = np.array([1000])
        matrix = build_matrix(arrays, target, 12)
        self.assertEqual(matrix.shape, (1, 24))
        self.assertEqual(matrix[0, 5], arrays["actual"][988] / 1000)


if __name__ == "__main__":
    unittest.main()

