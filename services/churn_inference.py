"""Inference for the saved dataset-defined customer churn classifier."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Any

import joblib
import pandas as pd


_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_PREPROCESSOR = _PROJECT_ROOT / "models" / "preprocessor.pkl"
_DEFAULT_MODEL = _PROJECT_ROOT / "models" / "churn_model.pkl"


@dataclass(frozen=True)
class ChurnPrediction:
    """Prediction metadata; customer identifiers are never model features."""

    customer_id: str | int
    churn_probability: float
    model_version: str


class ChurnInferenceService:
    """Load the saved preprocessing/model artifacts once and serve predictions."""

    def __init__(
        self,
        preprocessor_path: str | Path = _DEFAULT_PREPROCESSOR,
        model_path: str | Path = _DEFAULT_MODEL,
        *,
        model_version: str | None = None,
    ) -> None:
        self.preprocessor_path = Path(preprocessor_path)
        self.model_path = Path(model_path)
        for artifact_path, label in (
            (self.preprocessor_path, "preprocessor"),
            (self.model_path, "churn model"),
        ):
            if not artifact_path.is_file():
                raise FileNotFoundError(
                    f"The saved {label} artifact was not found: {artifact_path}"
                )

        try:
            self.preprocessor = joblib.load(self.preprocessor_path)
            self.model = joblib.load(self.model_path)
        except Exception as exc:
            raise RuntimeError(f"Could not load inference artifacts: {exc}") from exc

        try:
            self.feature_names = tuple(str(name) for name in self.preprocessor.feature_names_in_)
            transformed_names = tuple(
                str(name) for name in self.preprocessor.get_feature_names_out()
            )
            model_names = tuple(str(name) for name in self.model.feature_names_in_)
            class_labels = list(self.model.classes_)
        except (AttributeError, TypeError) as exc:
            raise ValueError(
                "Artifacts must expose fitted feature names and model classes."
            ) from exc

        if not self.feature_names:
            raise ValueError("The saved preprocessor has no raw input features.")
        if "CustomerID" in self.feature_names or "Churn" in self.feature_names:
            raise ValueError("CustomerID and Churn must not be preprocessor input features.")
        if transformed_names != model_names:
            raise ValueError(
                "Saved model feature names do not match the preprocessor output order."
            )
        if getattr(self.model, "n_features_in_", len(model_names)) != len(transformed_names):
            raise ValueError("Saved model and preprocessor feature counts do not match.")
        if 1 not in class_labels:
            raise ValueError("Saved churn model does not contain the positive class label 1.")

        self._positive_class_index = class_labels.index(1)
        self.model_version = model_version or self._artifact_version()

    def _artifact_version(self) -> str:
        """Return a short identifier derived from both loaded artifact files."""
        digest = hashlib.sha256()
        for path in (self.preprocessor_path, self.model_path):
            with path.open("rb") as artifact_file:
                for chunk in iter(lambda: artifact_file.read(1024 * 1024), b""):
                    digest.update(chunk)
        return f"sha256-{digest.hexdigest()[:12]}"

    def predict_one(
        self, customer_id: str | int, features: Mapping[str, Any]
    ) -> ChurnPrediction:
        """Predict one customer's probability from their raw feature values."""
        self._validate_customer_id(customer_id)
        frame = self._frame_from_records([features])
        return self._predict_frame(frame, [customer_id])[0]

    def predict_batch(
        self,
        customer_ids: Sequence[str | int],
        customers: Sequence[Mapping[str, Any]] | pd.DataFrame,
    ) -> list[ChurnPrediction]:
        """Predict a batch; identifiers are supplied separately from features."""
        ids = list(customer_ids)
        for customer_id in ids:
            self._validate_customer_id(customer_id)

        if isinstance(customers, pd.DataFrame):
            frame = self._validate_dataframe(customers)
        else:
            if isinstance(customers, (str, bytes)):
                raise ValueError("customers must be a DataFrame or a sequence of feature mappings.")
            records = list(customers)
            frame = self._frame_from_records(records)

        if len(ids) != len(frame):
            raise ValueError(
                f"customer_ids has {len(ids)} entries but customers has {len(frame)} rows."
            )
        return self._predict_frame(frame, ids)

    def _validate_customer_id(self, customer_id: Any) -> None:
        if isinstance(customer_id, bool) or not isinstance(customer_id, (str, int)):
            raise ValueError("customer_id must be a non-empty string or integer.")
        if isinstance(customer_id, str) and not customer_id.strip():
            raise ValueError("customer_id must be a non-empty string or integer.")

    def _validate_feature_names(self, names: Sequence[Any]) -> None:
        if len(set(names)) != len(names):
            raise ValueError("Input contains duplicate feature names.")
        received = set(names)
        expected = set(self.feature_names)
        missing = [name for name in self.feature_names if name not in received]
        unexpected = [name for name in names if name not in expected]
        if missing or unexpected:
            parts = []
            if missing:
                parts.append(f"missing features: {missing}")
            if unexpected:
                parts.append(f"unexpected features: {unexpected}")
            raise ValueError("Invalid input schema (" + "; ".join(parts) + ").")

    def _frame_from_records(
        self, records: Sequence[Mapping[str, Any]]
    ) -> pd.DataFrame:
        if not records:
            return pd.DataFrame(columns=self.feature_names)
        for row_number, record in enumerate(records):
            if not isinstance(record, Mapping):
                raise ValueError(f"Customer row {row_number} must be a feature mapping.")
            self._validate_feature_names(list(record.keys()))
        return pd.DataFrame.from_records(records, columns=self.feature_names)

    def _validate_dataframe(self, customers: pd.DataFrame) -> pd.DataFrame:
        if not customers.columns.is_unique:
            raise ValueError("Input contains duplicate feature names.")
        self._validate_feature_names(list(customers.columns))
        return customers.loc[:, list(self.feature_names)]

    def _predict_frame(
        self, raw_features: pd.DataFrame, customer_ids: Sequence[str | int]
    ) -> list[ChurnPrediction]:
        if raw_features.empty:
            return []
        transformed = self.preprocessor.transform(raw_features)
        transformed_frame = pd.DataFrame(
            transformed,
            columns=list(self.preprocessor.get_feature_names_out()),
            index=raw_features.index,
        )
        probabilities = self.model.predict_proba(transformed_frame)
        positive_probabilities = probabilities[:, self._positive_class_index]
        return [
            ChurnPrediction(
                customer_id=customer_id,
                churn_probability=float(probability),
                model_version=self.model_version,
            )
            for customer_id, probability in zip(customer_ids, positive_probabilities)
        ]

