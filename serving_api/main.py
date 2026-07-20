from contextlib import asynccontextmanager
from typing import List

from fastapi import Depends, FastAPI, HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from data_pipeline.database.models import GoldEquipmentFeatures, SilverTelemetry
from serving_api.database.connection import get_db
from serving_api.internal_auth import (
    TelemetryActivationRequest,
    TelemetryActivationResponse,
    verify_internal_token,
)
from serving_api.production_checks import assert_pipeline_production_ready


@asynccontextmanager
async def lifespan(_app: FastAPI):
    assert_pipeline_production_ready(role="serving")
    yield


app = FastAPI(
    title="Hospital Telemetry Serving API",
    description=(
        "Serving Silver/Gold para backend e ML. "
        "Rotas /api/v1/* (exceto health) e /internal/* exigem X-Internal-Token."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

_auth = [Depends(verify_internal_token)]


@app.put(
    "/internal/v1/equipments/{numero_serie}/telemetry",
    response_model=TelemetryActivationResponse,
    dependencies=_auth,
)
def activate_equipment_telemetry(numero_serie: str, body: TelemetryActivationRequest):
    from monitoring_service.equipment_types import simulator_tipo_to_slug
    from monitoring_service.persistence import db as sim_db

    try:
        sim_db.init_db()
        eq = sim_db.upsert_telemetry_equipment(
            numero_serie=numero_serie,
            tipo=body.tipo,
            modelo=body.modelo,
            fabricante=body.fabricante,
            hospital_id=body.hospital_id,
            telemetry_enabled=body.telemetry_enabled,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Falha ao ativar telemetria: {e}",
        ) from e

    return TelemetryActivationResponse(
        numero_serie=eq["numero_serie"],
        tipo=eq["tipo"],
        tipo_slug=simulator_tipo_to_slug(eq["tipo"]),
        equipamento_id=int(eq["equipamento_id"]),
        telemetry_enabled=bool(eq.get("telemetry_enabled", True)),
    )


@app.get("/api/v1/health")
def health_check(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Service unhealthy. Database connection failed: {str(e)}",
        ) from e
    return {"status": "healthy", "database": "connected"}


@app.get("/api/v1/equipments/{id}/telemetry", dependencies=_auth)
def get_equipment_telemetry(id: int, limit: int = 48, db: Session = Depends(get_db)):
    records = (
        db.query(SilverTelemetry)
        .filter(SilverTelemetry.equipamento_id == id)
        .order_by(SilverTelemetry.timestamp.desc())
        .limit(limit)
        .all()
    )
    if not records:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Nenhuma telemetria encontrada para o equipamento com ID {id}.",
        )
    return [_row_to_dict(r) for r in records]


@app.get("/api/v1/equipments/{id}/features", dependencies=_auth)
def get_latest_ml_features(id: int, db: Session = Depends(get_db)):
    latest_record = (
        db.query(GoldEquipmentFeatures)
        .filter(GoldEquipmentFeatures.equipamento_id == id)
        .order_by(GoldEquipmentFeatures.timestamp.desc())
        .first()
    )
    if not latest_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Nenhuma feature de MLOps calculada encontrada para o equipamento com ID {id}.",
        )
    return {
        "timestamp": latest_record.timestamp.isoformat(),
        "equipamento_id": latest_record.equipamento_id,
        "is_interpolated": latest_record.is_interpolated,
        "features": latest_record.features,
    }


@app.get("/api/v1/hospitals/{hospital_id}/telemetry", dependencies=_auth)
def get_hospital_telemetry(hospital_id: int, limit: int = 100, db: Session = Depends(get_db)):
    records = (
        db.query(SilverTelemetry)
        .filter(SilverTelemetry.hospital_id == hospital_id)
        .order_by(SilverTelemetry.timestamp.desc())
        .limit(limit)
        .all()
    )
    if not records:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Nenhuma telemetria encontrada para o hospital com ID {hospital_id}.",
        )
    return [_row_to_dict(r) for r in records]


@app.get("/api/v1/hospitals/{hospital_id}/features", dependencies=_auth)
def get_hospital_latest_features(hospital_id: int, db: Session = Depends(get_db)):
    equipments = (
        db.query(SilverTelemetry.equipamento_id)
        .filter(SilverTelemetry.hospital_id == hospital_id)
        .distinct()
        .all()
    )
    if not equipments:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Nenhum equipamento encontrado com telemetria registrada para o hospital com ID {hospital_id}.",
        )
    eq_ids = [e[0] for e in equipments]
    result: List[dict] = []
    for eq_id in eq_ids:
        latest_record = (
            db.query(GoldEquipmentFeatures)
            .filter(GoldEquipmentFeatures.equipamento_id == eq_id)
            .order_by(GoldEquipmentFeatures.timestamp.desc())
            .first()
        )
        if latest_record:
            result.append(
                {
                    "timestamp": latest_record.timestamp.isoformat(),
                    "equipamento_id": latest_record.equipamento_id,
                    "is_interpolated": latest_record.is_interpolated,
                    "features": latest_record.features,
                }
            )
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Nenhuma feature de MLOps encontrada para os equipamentos do hospital com ID {hospital_id}.",
        )
    return result


@app.get("/api/v1/hospitals/{hospital_id}/equipments/{equipment_id}", dependencies=_auth)
def get_hospital_equipment_data(
    hospital_id: int,
    equipment_id: int,
    limit: int = 48,
    db: Session = Depends(get_db),
):
    records = (
        db.query(SilverTelemetry)
        .filter(
            SilverTelemetry.hospital_id == hospital_id,
            SilverTelemetry.equipamento_id == equipment_id,
        )
        .order_by(SilverTelemetry.timestamp.desc())
        .limit(limit)
        .all()
    )
    if not records:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Nenhum registro encontrado para o equipamento {equipment_id} no hospital {hospital_id}.",
        )
    telemetry_list = [_row_to_dict(r) for r in records]
    latest_features = (
        db.query(GoldEquipmentFeatures)
        .filter(GoldEquipmentFeatures.equipamento_id == equipment_id)
        .order_by(GoldEquipmentFeatures.timestamp.desc())
        .first()
    )
    features_dict = None
    if latest_features:
        features_dict = {
            "timestamp": latest_features.timestamp.isoformat(),
            "equipamento_id": latest_features.equipamento_id,
            "is_interpolated": latest_features.is_interpolated,
            "features": latest_features.features,
        }
    return {
        "hospital_id": hospital_id,
        "equipamento_id": equipment_id,
        "telemetry": telemetry_list,
        "features": features_dict,
    }


def _row_to_dict(r) -> dict:
    row_dict = {}
    for col in r.__table__.columns:
        val = getattr(r, col.name)
        if val is not None:
            row_dict[col.name] = val.isoformat() if col.name == "timestamp" else val
    return row_dict
