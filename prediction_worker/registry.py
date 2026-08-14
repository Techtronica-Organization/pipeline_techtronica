from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from monitoring_service.equipment_types import normalize_tipo_slug

MODELS_DIR = Path(os.getenv("MODELS_DIR", Path(__file__).resolve().parents[1] / "models"))
MODEL_VERSION = os.getenv("MODEL_VERSION", "1.0.0")
PREPROCESSING_VERSION = "median_v1"
DEFAULT_THRESHOLD = float(os.getenv("PREDICTION_THRESHOLD", "0.5"))

SLUG_TO_FILE = {
    "tc": "best_model_tc.pkl",
    "ultrassom": "best_model_ultrassom.pkl",
    "raio_x": "best_model_raio_x.pkl",
    "pet": "best_model_pet.pkl",
    "ressonancia_magnetica": "best_model_ressonancia_magnetica.pkl",
    "arco_cirurgico": "best_model_arco_cirurgico.pkl",
    "angiografia": "best_model_angiografia.pkl",
}


@dataclass(frozen=True)
class ModelSpec:
    slug: str
    path: Path
    version: str
    threshold: float


def resolve_model_spec(tipo: str) -> ModelSpec:
    slug = normalize_tipo_slug(tipo)
    filename = SLUG_TO_FILE.get(slug)
    if not filename:
        raise KeyError(f"Nenhum modelo registrado para tipo={tipo!r}")
    path = MODELS_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Artefato ausente: {path}")
    threshold_env = os.getenv(f"PREDICTION_THRESHOLD_{slug.upper()}")
    threshold = float(threshold_env) if threshold_env else DEFAULT_THRESHOLD
    return ModelSpec(slug=slug, path=path, version=MODEL_VERSION, threshold=threshold)
