"""Tests for inference with the saved churn-model artifacts."""

from pathlib import Path
import tempfile
import unittest

import pandas as pd

from services.churn_inference import ChurnInferenceService


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def sample_features() -> dict[str, object]:
    return {
        "Tenure": 10,
        "PreferredLoginDevice": "Mobile Phone",
        "CityTier": 1,
        "WarehouseToHome": 6,
        "PreferredPaymentMode": "Debit Card",
        "Gender": "Female",
        "HourSpendOnApp": 3,
        "NumberOfDeviceRegistered": 4,
        "PreferedOrderCat": "Laptop & Accessory",
        "SatisfactionScore": 3,
        "MaritalStatus": "Single",
        "NumberOfAddress": 2,
        "Complain": 0,
        "OrderAmountHikeFromlastYear": 15,
        "CouponUsed": 1,
        "OrderCount": 2,
        "DaySinceLastOrder": 5,
        "CashbackAmount": 150.0,
    }


class ChurnInferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.service = ChurnInferenceService()

    def test_single_prediction_uses_saved_artifacts_and_separate_id(self) -> None:
        result = self.service.predict_one("customer-17", sample_features())

        self.assertEqual(result.customer_id, "customer-17")
        self.assertGreaterEqual(result.churn_probability, 0.0)
        self.assertLessEqual(result.churn_probability, 1.0)
        self.assertTrue(result.model_version.startswith("sha256-"))

    def test_shuffled_dataframe_columns_are_reordered_to_training_schema(self) -> None:
        features = sample_features()
        shuffled = list(reversed(list(features)))
        frame = pd.DataFrame([{name: features[name] for name in shuffled}])

        result = self.service.predict_batch([42], frame)[0]
        direct_result = self.service.predict_one(42, features)
        self.assertEqual(result.churn_probability, direct_result.churn_probability)

    def test_batch_predictions_preserve_ids_and_match_single_predictions(self) -> None:
        first = sample_features()
        second = sample_features()
        second["Tenure"] = 2
        second["SatisfactionScore"] = 1

        batch = self.service.predict_batch(
            ["first", "second"], [first, second]
        )
        singles = [
            self.service.predict_one("first", first),
            self.service.predict_one("second", second),
        ]

        self.assertEqual([item.customer_id for item in batch], ["first", "second"])
        self.assertEqual(
            [item.churn_probability for item in batch],
            [item.churn_probability for item in singles],
        )
        self.assertTrue(all(item.model_version == batch[0].model_version for item in batch))

    def test_missing_feature_is_rejected_clearly(self) -> None:
        features = sample_features()
        del features["Tenure"]
        with self.assertRaisesRegex(ValueError, "missing features.*Tenure"):
            self.service.predict_one(1, features)

    def test_unexpected_identifier_or_target_is_rejected_as_feature(self) -> None:
        for extra in ("CustomerID", "Churn", "unexpected"):
            with self.subTest(extra=extra):
                features = sample_features()
                features[extra] = 1
                with self.assertRaisesRegex(ValueError, "unexpected features"):
                    self.service.predict_one(1, features)

    def test_invalid_batch_shape_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "customer_ids has 2 entries"):
            self.service.predict_batch([1, 2], [sample_features()])

    def test_empty_batch_returns_empty_results(self) -> None:
        self.assertEqual(self.service.predict_batch([], []), [])

    def test_missing_artifact_has_clear_file_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing.pkl"
            with self.assertRaisesRegex(FileNotFoundError, "preprocessor artifact"):
                ChurnInferenceService(
                    preprocessor_path=missing,
                    model_path=PROJECT_ROOT / "models" / "churn_model.pkl",
                )


if __name__ == "__main__":
    unittest.main()
