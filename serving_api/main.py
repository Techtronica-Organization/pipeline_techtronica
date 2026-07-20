from fastapi import FastAPI, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import List, Dict, Any
from serving_api.database.connection import get_db
from serving_api.internal_auth import (
    TelemetryActivationRequest,
    TelemetryActivationResponse,
    verify_internal_token,
)
from data_pipeline.database.models import SilverTelemetry, GoldEquipmentFeatures

app = FastAPI(
    title="Hospital Telemetry Serving API",
    description="Interface de serving de dados para expor tabelas Silver (telemetrias tratadas) e Gold (features de MLOps) para o Backend e Modelos de Machine Learning.",
    version="1.0.0"
)


@app.put(
    "/internal/v1/equipments/{numero_serie}/telemetry",
    response_model=TelemetryActivationResponse,
    dependencies=[Depends(verify_internal_token)],
)
def activate_equipment_telemetry(numero_serie: str, body: TelemetryActivationRequest):
    from monitoring_service.persistence import db as sim_db
    from monitoring_service.equipment_types import simulator_tipo_to_slug

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
        return {"status": "healthy", "database": "connected"}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Service unhealthy. Database connection failed: {str(e)}"
        )

@app.get("/api/v1/equipments/{id}/telemetry")
def get_equipment_telemetry(id: int, limit: int = 48, db: Session = Depends(get_db)):
    """
    Retorna o historico de telemetrias limpas (camada Silver) para um determinado equipamento,
    ordenado do mais recente para o mais antigo.
    """
    records = db.query(SilverTelemetry).filter(
        SilverTelemetry.equipamento_id == id
    ).order_by(SilverTelemetry.timestamp.desc()).limit(limit).all()

    if not records:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Nenhuma telemetria encontrada para o equipamento com ID {id}."
        )

    result = []
    for r in records:
        row_dict = {}
        for col in r.__table__.columns:
            val = getattr(r, col.name)
            if val is not None:
                if col.name == "timestamp":
                    row_dict[col.name] = val.isoformat()
                else:
                    row_dict[col.name] = val
        result.append(row_dict)

    return result

@app.get("/api/v1/equipments/{id}/features")
def get_latest_ml_features(id: int, db: Session = Depends(get_db)):
    """
    Retorna o vetor de features agregadas mais recente (camada Gold) para servir a predicao de MLOps online.
    """
    latest_record = db.query(GoldEquipmentFeatures).filter(
        GoldEquipmentFeatures.equipamento_id == id
    ).order_by(GoldEquipmentFeatures.timestamp.desc()).first()

    if not latest_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Nenhuma feature de MLOps calculada encontrada para o equipamento com ID {id}."
        )

    return {
        "timestamp": latest_record.timestamp.isoformat(),
        "equipamento_id": latest_record.equipamento_id,
        "is_interpolated": latest_record.is_interpolated,
        "features": latest_record.features
    }

@app.get("/api/v1/hospitals/{hospital_id}/telemetry")
def get_hospital_telemetry(hospital_id: int, limit: int = 100, db: Session = Depends(get_db)):
    """
    Retorna o historico de telemetrias limpas (camada Silver) para todos os equipamentos
    de um determinado hospital, ordenado do mais recente para o mais antigo.
    """
    records = db.query(SilverTelemetry).filter(
        SilverTelemetry.hospital_id == hospital_id
    ).order_by(SilverTelemetry.timestamp.desc()).limit(limit).all()

    if not records:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Nenhuma telemetria encontrada para o hospital com ID {hospital_id}."
        )

    result = []
    for r in records:
        row_dict = {}
        for col in r.__table__.columns:
            val = getattr(r, col.name)
            if val is not None:
                if col.name == "timestamp":
                    row_dict[col.name] = val.isoformat()
                else:
                    row_dict[col.name] = val
        result.append(row_dict)

    return result

@app.get("/api/v1/hospitals/{hospital_id}/features")
def get_hospital_latest_features(hospital_id: int, db: Session = Depends(get_db)):
    """
    Retorna o vetor de features agregadas mais recente (camada Gold) de todos os equipamentos
    de um determinado hospital, pronto para inferencias de MLOps em lote.
    """
    # 1. Get unique equipment IDs belonging to this hospital from Silver telemetry
    equipments = db.query(SilverTelemetry.equipamento_id).filter(
        SilverTelemetry.hospital_id == hospital_id
    ).distinct().all()
    
    if not equipments:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Nenhum equipamento encontrado com telemetria registrada para o hospital com ID {hospital_id}."
        )
        
    eq_ids = [e[0] for e in equipments]
    result = []
    
    # 2. Query the latest Gold features row for each of these equipments
    for eq_id in eq_ids:
        latest_record = db.query(GoldEquipmentFeatures).filter(
            GoldEquipmentFeatures.equipamento_id == eq_id
        ).order_by(GoldEquipmentFeatures.timestamp.desc()).first()
        
        if latest_record:
            result.append({
                "timestamp": latest_record.timestamp.isoformat(),
                "equipamento_id": latest_record.equipamento_id,
                "is_interpolated": latest_record.is_interpolated,
                "features": latest_record.features
            })
            
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Nenhuma feature de MLOps encontrada para os equipamentos do hospital com ID {hospital_id}."
        )
        
    return result


@app.get("/api/v1/hospitals/{hospital_id}/equipments/{equipment_id}")
def get_hospital_equipment_data(
    hospital_id: int, 
    equipment_id: int, 
    limit: int = 48, 
    db: Session = Depends(get_db)
):
    """
    Retorna o histórico de telemetrias limpas (camada Silver, para o Backend) e as features
    agregadas mais recentes (camada Gold, para MLOps) de um equipamento específico em um hospital.
    """
    # 1. Buscar telemetrias da camada Silver para validar a associação entre hospital e equipamento
    records = db.query(SilverTelemetry).filter(
        SilverTelemetry.hospital_id == hospital_id,
        SilverTelemetry.equipamento_id == equipment_id
    ).order_by(SilverTelemetry.timestamp.desc()).limit(limit).all()

    if not records:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Nenhum registro encontrado para o equipamento {equipment_id} no hospital {hospital_id}."
        )

    # 2. Formatar telemetrias (ocultando campos nulos específicos)
    telemetry_list = []
    for r in records:
        row_dict = {}
        for col in r.__table__.columns:
            val = getattr(r, col.name)
            if val is not None:
                if col.name == "timestamp":
                    row_dict[col.name] = val.isoformat()
                else:
                    row_dict[col.name] = val
        telemetry_list.append(row_dict)

    # 3. Buscar as features de MLOps mais recentes (camada Gold)
    latest_features = db.query(GoldEquipmentFeatures).filter(
        GoldEquipmentFeatures.equipamento_id == equipment_id
    ).order_by(GoldEquipmentFeatures.timestamp.desc()).first()

    features_dict = None
    if latest_features:
        features_dict = {
            "timestamp": latest_features.timestamp.isoformat(),
            "equipamento_id": latest_features.equipamento_id,
            "is_interpolated": latest_features.is_interpolated,
            "features": latest_features.features
        }

    return {
        "hospital_id": hospital_id,
        "equipamento_id": equipment_id,
        "telemetry": telemetry_list,
        "features": features_dict
    }


