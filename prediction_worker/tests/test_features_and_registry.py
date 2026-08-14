from datetime import datetime, timedelta

from prediction_worker.feature_builder import build_feature_vector
from prediction_worker.registry import resolve_model_spec
from monitoring_service.equipment_types import normalize_tipo_slug, slug_to_simulator_tipo


def test_normalize_and_remap_types():
    assert normalize_tipo_slug("Raio-X") == "raio_x"
    assert slug_to_simulator_tipo("arco_cirurgico") == "arco cirurgico"
    assert resolve_model_spec("angiografia").path.name == "best_model_angiografia.pkl"
    assert resolve_model_spec("arco cirurgico").path.name == "best_model_arco_cirurgico.pkl"


def test_median_delta_features():
    now = datetime(2026, 7, 19, 12, 0, 0)
    history = []
    for hour in range(6):
        history.append(
            {
                "timestamp": now - timedelta(hours=5 - hour),
                "equipamento_id": 1,
                "tube_temp": 30 + hour,
            }
        )
    current = history[-1]
    expected = [
        "tube_temp",
        "tube_temp_mean_6h",
        "tube_temp_std_6h",
        "tube_temp_min_6h",
        "tube_temp_max_6h",
        "tube_temp_delta_6h",
    ]
    values = build_feature_vector(current_row=current, history_rows=history, expected_features=expected)
    assert values["tube_temp"] == 35.0
    assert values["tube_temp_min_6h"] == 30.0
    assert values["tube_temp_max_6h"] == 35.0
    assert values["tube_temp_delta_6h"] == 32.5
