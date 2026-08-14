from __future__ import annotations

from datetime import timedelta
from typing import Any

import numpy as np
import pandas as pd

from prediction_worker.registry import PREPROCESSING_VERSION

SENSOR_EXCLUDE = {
    "timestamp",
    "equipamento_id",
    "hospital_id",
    "tipo",
    "is_interpolated",
    "event_id",
    "numero_serie",
    "processing_status",
    "processing_started_at",
    "processing_finished_at",
    "next_attempt_at",
    "attempt_count",
    "last_error",
    "model_slug",
    "model_version",
    "preprocessing_version",
    "remote_falha_id",
    "remote_chamado_id",
    "lease_until",
    "worker_id",
}

WINDOWS = (6, 24, 72)


def _sensor_columns(row: dict[str, Any]) -> list[str]:
    return [k for k, v in row.items() if k not in SENSOR_EXCLUDE and v is not None]


def build_feature_vector(
    *,
    current_row: dict[str, Any],
    history_rows: list[dict[str, Any]],
    expected_features: list[str],
) -> dict[str, float]:
    if not history_rows:
        history_rows = [current_row]

    df = pd.DataFrame(history_rows)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.sort_values("timestamp")
    current_ts = pd.to_datetime(current_row["timestamp"])
    sensors = _sensor_columns(current_row)

    values: dict[str, float] = {}
    for sensor in sensors:
        current_val = current_row.get(sensor)
        if current_val is None or (isinstance(current_val, float) and np.isnan(current_val)):
            continue
        values[sensor] = float(current_val)

        for hours in WINDOWS:
            window_start = current_ts - timedelta(hours=hours)
            window = df[(df["timestamp"] >= window_start) & (df["timestamp"] <= current_ts)]
            series = pd.to_numeric(window[sensor], errors="coerce").dropna() if sensor in window.columns else pd.Series(dtype=float)
            if series.empty:
                series = pd.Series([float(current_val)])

            values[f"{sensor}_mean_{hours}h"] = float(series.mean())
            values[f"{sensor}_std_{hours}h"] = float(series.std(ddof=0)) if len(series) > 1 else 0.0
            values[f"{sensor}_min_{hours}h"] = float(series.min())
            values[f"{sensor}_max_{hours}h"] = float(series.max())
            values[f"{sensor}_delta_{hours}h"] = float(series.median())

    ordered: dict[str, float] = {}
    missing: list[str] = []
    for name in expected_features:
        if name not in values or values[name] is None or (isinstance(values[name], float) and np.isnan(values[name])):
            missing.append(name)
        else:
            ordered[name] = float(values[name])

    if missing:
        raise ValueError(
            f"Features ausentes para preprocessing={PREPROCESSING_VERSION}: {missing[:8]}"
            + ("..." if len(missing) > 8 else "")
        )
    return ordered
