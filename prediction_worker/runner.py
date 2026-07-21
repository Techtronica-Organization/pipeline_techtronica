from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import joblib
import numpy as np

from prediction_worker.feature_builder import build_feature_vector
from prediction_worker.registry import ModelSpec, PREPROCESSING_VERSION, resolve_model_spec


@dataclass
class PredictionResult:
    failure_detected: bool
    probability: float
    model_slug: str
    model_version: str
    preprocessing_version: str
    details: dict[str, Any]


@lru_cache(maxsize=16)
def _load_bundle(path_str: str) -> dict[str, Any]:
    return joblib.load(path_str)


def predict_for_event(
    *,
    tipo: str,
    current_row: dict[str, Any],
    history_rows: list[dict[str, Any]],
) -> PredictionResult:
    spec: ModelSpec = resolve_model_spec(tipo)
    bundle = _load_bundle(str(spec.path))
    features = list(bundle["features"])
    model = bundle["model"]
    scaler = bundle["scaler"]

    feature_map = build_feature_vector(
        current_row=current_row,
        history_rows=history_rows,
        expected_features=features,
    )
    matrix = np.array([[feature_map[name] for name in features]], dtype=float)
    scaled = scaler.transform(matrix)

    if hasattr(model, "predict_proba"):
        proba = model.predict_proba(scaled)[0]
        classes = list(getattr(model, "classes_", [0, 1]))
        if 1 in classes:
            probability = float(proba[list(classes).index(1)])
        elif "1" in [str(c) for c in classes]:
            probability = float(proba[[str(c) for c in classes].index("1")])
        else:
            probability = float(np.max(proba))
    else:
        pred = model.predict(scaled)[0]
        probability = 1.0 if str(pred) in {"1", "True", "true"} else 0.0

    failure_detected = probability >= spec.threshold
    rounded_features = {
        name: (round(float(val), 6) if isinstance(val, (int, float, np.floating)) else val)
        for name, val in feature_map.items()
    }
    return PredictionResult(
        failure_detected=failure_detected,
        probability=probability,
        model_slug=spec.slug,
        model_version=spec.version,
        preprocessing_version=PREPROCESSING_VERSION,
        details={
            "threshold": spec.threshold,
            "artifact": Path(spec.path).name,
            "algorithm": bundle.get("algorithm"),
            "features": rounded_features,
            "sensors_current": {
                key: current_row.get(key)
                for key in sorted(current_row.keys())
                if key
                not in {
                    "id",
                    "event_id",
                    "numero_serie",
                    "tipo",
                    "timestamp",
                    "processing_status",
                    "remote_falha_id",
                }
                and not str(key).startswith("_")
            },
        },
    )
