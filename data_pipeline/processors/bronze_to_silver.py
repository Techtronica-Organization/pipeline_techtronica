import io
import json
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from botocore.exceptions import ClientError
from data_pipeline.config import Config
from data_pipeline.storage.s3_client import get_s3_client
from monitoring_service.simulators.base import LIMITES_FISICOS

def get_silver_s3_path(hospital_id, tipo_eq, date_obj):
    """
    Returns the Silver bucket object key format.
    """
    return f"silver/equipments/hospital_id={hospital_id}/type={tipo_eq}/year={date_obj.year}/month={date_obj.month:02d}/data.parquet"

def process_bronze_to_silver(hospital_id, equipamento_id, tipo_eq, new_telemetry_msg):
    """
    Ingests raw telemetry from Kafka into the Bronze bucket,
    then processes, interpolates, and saves it into the Silver bucket as Parquet.
    """
    s3 = get_s3_client()
    timestamp_str = new_telemetry_msg["timestamp"]
    date_obj = datetime.fromisoformat(timestamp_str)
    
    # 1. Save Raw JSON to Bronze bucket
    bronze_key = f"bronze/hospital_id={hospital_id}/year={date_obj.year}/month={date_obj.month:02d}/day={date_obj.day:02d}/{timestamp_str.replace(':', '-')}_{equipamento_id}.json"
    try:
        s3.put_object(
            Bucket=Config.BRONZE_BUCKET,
            Key=bronze_key,
            Body=json.dumps(new_telemetry_msg, ensure_ascii=False)
        )
    except Exception as e:
        print(f"Erro ao salvar no bucket Bronze: {e}")

    # 2. Process Silver Layer (Incremental Update)
    silver_key = get_silver_s3_path(hospital_id, tipo_eq, date_obj)
    
    # Initialize variables to extract from telemetry
    sensors = new_telemetry_msg["telemetria"]
    row_data = {
        "timestamp": pd.to_datetime(date_obj),
        "equipamento_id": int(equipamento_id),
        "is_interpolated": False
    }
    for k, v in sensors.items():
        row_data[k] = float(v)
        
    df_new = pd.DataFrame([row_data])
    
    # Try to load existing silver parquet
    try:
        response = s3.get_object(Bucket=Config.SILVER_BUCKET, Key=silver_key)
        parquet_data = response["Body"].read()
        df_existing = pd.read_parquet(io.BytesIO(parquet_data))
        df_combined = pd.concat([df_existing, df_new], ignore_index=True)
    except ClientError as e:
        # If the file does not exist, start a new DataFrame
        if e.response["Error"]["Code"] in ("NoSuchKey", "404"):
            df_combined = df_new
        else:
            raise e
            
    # Clean up duplicate timestamps for this specific equipment
    df_combined = df_combined.drop_duplicates(subset=["timestamp", "equipamento_id"], keep="last")
    df_combined = df_combined.sort_values("timestamp").reset_index(drop=True)
    
    # Filter for the current equipment to apply interpolation
    df_eq = df_combined[df_combined["equipamento_id"] == equipamento_id].copy()
    df_others = df_combined[df_combined["equipamento_id"] != equipamento_id].copy()
    
    if len(df_eq) > 1:
        # Re-index on a clean hourly frequency to expose missing gaps
        df_eq = df_eq.set_index("timestamp")
        min_ts = df_eq.index.min()
        max_ts = df_eq.index.max()
        hourly_index = pd.date_range(start=min_ts, end=max_ts, freq="h")
        
        # Keep track of columns before reindexing
        sensor_cols = [c for c in df_eq.columns if c not in ("equipamento_id", "is_interpolated")]
        
        # Record which values were missing before interpolation
        df_eq_reindexed = df_eq.reindex(hourly_index)
        df_eq_reindexed["equipamento_id"] = equipamento_id
        
        # Mask representing where values are missing
        missing_mask = df_eq_reindexed[sensor_cols].isna()
        
        # Preserve existing is_interpolated flags, initialize new ones to False
        df_eq_reindexed.loc[df_eq_reindexed["is_interpolated"].isna(), "is_interpolated"] = False
        df_eq_reindexed["is_interpolated"] = df_eq_reindexed["is_interpolated"].astype(bool)
        
        # Perform linear interpolation up to Config.INTERPOLATION_GAP_LIMIT_HOURS
        df_eq_reindexed[sensor_cols] = df_eq_reindexed[sensor_cols].interpolate(
            method="linear", 
            limit=Config.INTERPOLATION_GAP_LIMIT_HOURS
        )
        
        # Set is_interpolated to True for any row where at least one sensor was filled
        interpolated_rows = missing_mask & df_eq_reindexed[sensor_cols].notna()
        df_eq_reindexed.loc[interpolated_rows.any(axis=1), "is_interpolated"] = True
        
        # Reset index back to timestamp column
        df_eq = df_eq_reindexed.reset_index().rename(columns={"index": "timestamp"})
        
    # Apply physical limits clamping
    limits = LIMITES_FISICOS.get(tipo_eq, {})
    for col, (min_val, max_val) in limits.items():
        if col in df_eq.columns:
            df_eq[col] = df_eq[col].clip(min_val, max_val)
            
    # Combine back with other equipments if any
    df_final = pd.concat([df_others, df_eq], ignore_index=True)
    df_final = df_final.sort_values("timestamp").reset_index(drop=True)
    
    # Save back to Silver bucket as Parquet
    buffer = io.BytesIO()
    df_final.to_parquet(buffer, index=False, engine="pyarrow")
    buffer.seek(0)
    
    try:
        s3.put_object(
            Bucket=Config.SILVER_BUCKET,
            Key=silver_key,
            Body=buffer.getvalue()
        )
        print(f"Processado Silver: Equipamento ID={equipamento_id} às {timestamp_str} (is_interpolated={row_data['is_interpolated']})")
    except Exception as e:
        print(f"Erro ao salvar no bucket Silver: {e}")
        
    # 3. Synchronize with Serving SQL Database
    try:
        import uuid
        from data_pipeline.database.connection import get_db_session
        from data_pipeline.database.models import StgSilverTelemetry

        session = get_db_session()
        msg_ts = pd.to_datetime(new_telemetry_msg["timestamp"]).to_pydatetime()
        msg_event_id = new_telemetry_msg.get("event_id")
        msg_serie = new_telemetry_msg.get("numero_serie") or f"SN-{int(equipamento_id)}"

        for _, row in df_eq.iterrows():
            ts = row["timestamp"]
            if hasattr(ts, "to_pydatetime"):
                ts = ts.to_pydatetime()
            eq_id = int(row["equipamento_id"])

            rec = session.query(StgSilverTelemetry).filter_by(timestamp=ts, equipamento_id=eq_id).first()
            is_new = rec is None
            if not rec:
                rec = StgSilverTelemetry(timestamp=ts, equipamento_id=eq_id)
                session.add(rec)

            rec.hospital_id = int(hospital_id)
            rec.tipo = tipo_eq
            rec.is_interpolated = bool(row["is_interpolated"])
            rec.numero_serie = msg_serie
            if not rec.event_id:
                if ts == msg_ts and msg_event_id:
                    rec.event_id = msg_event_id
                else:
                    rec.event_id = str(uuid.uuid4())
            if is_new or not rec.processing_status:
                rec.processing_status = "PENDING"
                rec.next_attempt_at = ts
                rec.attempt_count = 0

            skip_cols = {
                "timestamp",
                "equipamento_id",
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
            for col in df_eq.columns:
                if col in skip_cols:
                    continue
                val = row[col]
                if pd.isna(val):
                    val = None
                elif col in ("scan_count", "exposure_count", "minutes_since_injection"):
                    val = int(round(val))
                else:
                    val = float(val)
                setattr(rec, col, val)
        session.commit()
        session.close()
    except Exception as e:
        print(f"Erro ao sincronizar Silver para o banco SQL: {e}")

    return df_eq
