from __future__ import annotations

import re
import unicodedata

SIMULATOR_TIPOS = {
    "tc",
    "raio x",
    "ressonancia magnetica",
    "pet",
    "ultrassom",
    "arco cirurgico",
    "angiografia",
}

SLUG_TO_SIMULATOR = {
    "tc": "tc",
    "ultrassom": "ultrassom",
    "raio_x": "raio x",
    "pet": "pet",
    "ressonancia_magnetica": "ressonancia magnetica",
    "arco_cirurgico": "arco cirurgico",
    "angiografia": "angiografia",
}

SIMULATOR_TO_SLUG = {v: k for k, v in SLUG_TO_SIMULATOR.items()}


def _strip_accents(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def normalize_tipo_slug(value: str) -> str:
    raw = _strip_accents((value or "").strip().lower())
    raw = raw.replace("-", " ").replace("_", " ")
    raw = re.sub(r"\s+", " ", raw).strip()
    aliases = {
        "tc": "tc",
        "tomografo": "tc",
        "tomografia": "tc",
        "ultrassom": "ultrassom",
        "raio x": "raio_x",
        "rx": "raio_x",
        "pet": "pet",
        "ressonancia magnetica": "ressonancia_magnetica",
        "rm": "ressonancia_magnetica",
        "arco cirurgico": "arco_cirurgico",
        "arco cirurgico c arm": "arco_cirurgico",
        "angiografia": "angiografia",
    }
    slug = aliases.get(raw)
    if not slug:
        compact = raw.replace(" ", "_")
        if compact in SLUG_TO_SIMULATOR:
            slug = compact
    if not slug:
        raise ValueError(f"Tipo de equipamento nao suportado: {value!r}")
    return slug


def slug_to_simulator_tipo(slug: str) -> str:
    normalized = normalize_tipo_slug(slug)
    return SLUG_TO_SIMULATOR[normalized]


def simulator_tipo_to_slug(tipo: str) -> str:
    raw = _strip_accents((tipo or "").strip().lower())
    raw = re.sub(r"\s+", " ", raw.replace("-", " ").replace("_", " ")).strip()
    if raw in SIMULATOR_TO_SLUG:
        return SIMULATOR_TO_SLUG[raw]
    return normalize_tipo_slug(tipo)
