import io
import pandas as pd
from data_pipeline.config import Config
from data_pipeline.storage.s3_client import get_s3_client


def _timestamp_for_sql(value):
    ts = pd.to_datetime(value).round("s")
    if hasattr(ts, "to_pydatetime"):
        ts = ts.to_pydatetime()
    return ts.replace(tzinfo=None) if getattr(ts, "tzinfo", None) else ts


def _upsert_gold_features(session, values):
    from data_pipeline.database.models import GoldEquipmentFeatures

    dialect = session.bind.dialect.name if session.bind is not None else ""
    table = GoldEquipmentFeatures.__table__

    if dialect == "mysql":
        from sqlalchemy.dialects.mysql import insert

        stmt = insert(table).values(values)
        stmt = stmt.on_duplicate_key_update(
            is_interpolated=stmt.inserted.is_interpolated,
            features=stmt.inserted.features,
        )
        session.execute(stmt)
        return

    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert

        stmt = insert(table).values(values)
        stmt = stmt.on_conflict_do_update(
            index_elements=["timestamp", "equipamento_id"],
            set_={
                "is_interpolated": stmt.excluded.is_interpolated,
                "features": stmt.excluded.features,
            },
        )
        session.execute(stmt)
        return

    if dialect == "sqlite":
        from sqlalchemy.dialects.sqlite import insert

        stmt = insert(table).values(values)
        stmt = stmt.on_conflict_do_update(
            index_elements=["timestamp", "equipamento_id"],
            set_={
                "is_interpolated": stmt.excluded.is_interpolated,
                "features": stmt.excluded.features,
            },
        )
        session.execute(stmt)
        return

    for item in values:
        rec = session.query(GoldEquipmentFeatures).filter_by(
            timestamp=item["timestamp"],
            equipamento_id=item["equipamento_id"],
        ).first()
        if not rec:
            rec = GoldEquipmentFeatures(timestamp=item["timestamp"], equipamento_id=item["equipamento_id"])
            session.add(rec)
        rec.is_interpolated = item["is_interpolated"]
        rec.features = item["features"]

def process_silver_to_gold(hospital_id, equipamento_id, tipo_eq, df_eq):
    """
    Reads Silver conformed telemetry for an equipment, calculates rolling window
    aggregates (6h, 12h, 24h, 72h), and saves the feature table to the Gold bucket.
    """
    s3 = get_s3_client()
    
    if len(df_eq) == 0:
        return
        
    # Ensure timestamp is datetime and sort
    df_eq = df_eq.copy()
    df_eq["timestamp"] = pd.to_datetime(df_eq["timestamp"])
    df_eq = df_eq.sort_values("timestamp").reset_index(drop=True)
    
    # Exclude metadata columns to perform aggregates on sensors only
    exclude_cols = {"timestamp", "equipamento_id", "is_interpolated"}
    sensor_cols = [c for c in df_eq.columns if c not in exclude_cols and not str(c).startswith("_")]
    
    # Target path in Gold
    gold_key = f"gold/features/hospital_id={hospital_id}/equipment_id={equipamento_id}/features.parquet"
    
    # Initialize base features DataFrame
    df_features = pd.DataFrame({
        "timestamp": df_eq["timestamp"],
        "equipamento_id": df_eq["equipamento_id"],
        "is_interpolated": df_eq["is_interpolated"]
    })
    
    new_cols = {}
    
    # Compute rolling window statistics
    # Note: rolling on datetime requires the index to be monotonic, which we guaranteed by sorting
    for window_hours in [6, 12, 24, 72]:
        window_str = f"{window_hours}h"
        # Include timestamp column in the slice so rolling on='timestamp' can resolve it
        rolling_cols = sensor_cols + ["timestamp"]
        rolling_obj = df_eq[rolling_cols].rolling(window=window_str, on="timestamp", closed="both")
        
        # Mean, Std, Min, Max
        mean_df = rolling_obj.mean()
        std_df = rolling_obj.std().fillna(0.0) # single item rolling std is NaN, set to 0.0
        min_df = rolling_obj.min()
        max_df = rolling_obj.max()
        
        for col in sensor_cols:
            new_cols[f"{col}_mean_{window_hours}h"] = mean_df[col]
            new_cols[f"{col}_std_{window_hours}h"] = std_df[col]
            new_cols[f"{col}_min_{window_hours}h"] = min_df[col]
            new_cols[f"{col}_max_{window_hours}h"] = max_df[col]
            
    if new_cols:
        df_features = pd.concat([df_features, pd.DataFrame(new_cols)], axis=1)
            
    # Serialize to Parquet
    buffer = io.BytesIO()
    df_features.to_parquet(buffer, index=False, engine="pyarrow")
    buffer.seek(0)
    
    try:
        s3.put_object(
            Bucket=Config.GOLD_BUCKET,
            Key=gold_key,
            Body=buffer.getvalue()
        )
        print(f"Processado Gold: Calculadas features rolantes de MLOps para Equipamento ID={equipamento_id} (Linhas={len(df_features)})")
    except Exception as e:
        print(f"Erro ao salvar no bucket Gold: {e}")
        
    # 3. Synchronize with Serving SQL Database
    session = None
    try:
        from data_pipeline.database.connection import get_db_session

        session = get_db_session()
        values = []
        for _, row in df_features.iterrows():
            ts = _timestamp_for_sql(row["timestamp"])
            eq_id = int(row["equipamento_id"])

            # Extract features as a JSON dictionary
            feat_dict = {}
            for col in df_features.columns:
                if col not in ("timestamp", "equipamento_id", "is_interpolated"):
                    val = row[col]
                    if pd.isna(val):
                        feat_dict[col] = None
                    else:
                        feat_dict[col] = float(val)
            values.append(
                {
                    "timestamp": ts,
                    "equipamento_id": eq_id,
                    "is_interpolated": bool(row["is_interpolated"]),
                    "features": feat_dict,
                }
            )
        if values:
            _upsert_gold_features(session, values)
        session.commit()
        session.close()
    except Exception as e:
        if session is not None:
            try:
                session.rollback()
                session.close()
            except Exception:
                pass
        print(f"Erro ao sincronizar Gold para o banco SQL: {e}")
        
    return df_features
