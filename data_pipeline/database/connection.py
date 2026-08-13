import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from data_pipeline.database.url import ensure_database_exists, sqlalchemy_database_url

USE_SQL_DB = os.getenv("USE_SQL_DB", os.getenv("USE_POSTGRES", "false")).lower() == "true" or os.getenv("DB_HOST") is not None

if USE_SQL_DB:
    ensure_database_exists()
    DATABASE_URL = sqlalchemy_database_url()
    engine = create_engine(DATABASE_URL, pool_size=10, max_overflow=20, pool_pre_ping=True)
else:
    # Local SQLite fallback for host-based integration testing
    sqlite_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "serving_database.db"))
    DATABASE_URL = f"sqlite:///{sqlite_path}"
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def init_sql_db():
    from data_pipeline.database.models import StgSilverTelemetry, GoldEquipmentFeatures
    from sqlalchemy import text, inspect

    Base.metadata.create_all(bind=engine)

    processing_columns = {
        "event_id": "VARCHAR(64)",
        "numero_serie": "VARCHAR(100)",
        "processing_status": "VARCHAR(32) DEFAULT 'PENDING' NOT NULL",
        "processing_started_at": "TIMESTAMP",
        "processing_finished_at": "TIMESTAMP",
        "next_attempt_at": "TIMESTAMP",
        "attempt_count": "INTEGER DEFAULT 0 NOT NULL",
        "last_error": "TEXT",
        "model_slug": "VARCHAR(64)",
        "model_version": "VARCHAR(64)",
        "preprocessing_version": "VARCHAR(64)",
        "remote_falha_id": "INTEGER",
        "remote_chamado_id": "INTEGER",
        "lease_until": "TIMESTAMP",
        "worker_id": "VARCHAR(128)",
    }

    with engine.begin() as conn:
        inspector = inspect(engine)
        if "stg_silver_telemetry" in inspector.get_table_names():
            existing = {col["name"] for col in inspector.get_columns("stg_silver_telemetry")}
            for col_name, col_type in processing_columns.items():
                if col_name not in existing:
                    conn.execute(
                        text(f"ALTER TABLE stg_silver_telemetry ADD COLUMN {col_name} {col_type}")
                    )
            conn.execute(
                text(
                    "UPDATE stg_silver_telemetry SET processing_status = 'PENDING' "
                    "WHERE processing_status IS NULL OR processing_status = ''"
                )
            )
            if engine.dialect.name in ("postgresql", "mysql"):
                existing_indexes = {idx["name"] for idx in inspector.get_indexes("stg_silver_telemetry")}
                if engine.dialect.name == "mysql":
                    index_statements = [
                        ("ix_stg_silver_processing_status", "processing_status"),
                        ("ix_stg_silver_next_attempt", "next_attempt_at"),
                        ("ix_stg_silver_numero_serie", "numero_serie"),
                    ]
                    for idx_name, col_name in index_statements:
                        if idx_name not in existing_indexes:
                            conn.execute(text(f"CREATE INDEX {idx_name} ON stg_silver_telemetry ({col_name})"))
                else:
                    conn.execute(
                        text(
                            "CREATE INDEX IF NOT EXISTS ix_stg_silver_processing_status "
                            "ON stg_silver_telemetry (processing_status)"
                        )
                    )
                    conn.execute(
                        text(
                            "CREATE INDEX IF NOT EXISTS ix_stg_silver_next_attempt "
                            "ON stg_silver_telemetry (next_attempt_at)"
                        )
                    )
                    conn.execute(
                        text(
                            "CREATE INDEX IF NOT EXISTS ix_stg_silver_numero_serie "
                            "ON stg_silver_telemetry (numero_serie)"
                        )
                    )

        if engine.dialect.name == "postgresql":
            conn.execute(
                text(
                    """
                    DO $$
                    BEGIN
                        IF EXISTS (
                            SELECT FROM information_schema.tables
                            WHERE table_schema = 'public'
                              AND table_name = 'silver_telemetry'
                              AND table_type = 'BASE TABLE'
                        ) THEN
                            DROP TABLE public.silver_telemetry CASCADE;
                        END IF;
                    END $$;
                    """
                )
            )
            conn.execute(text("CREATE OR REPLACE VIEW silver_telemetry AS SELECT * FROM stg_silver_telemetry;"))
        elif engine.dialect.name == "mysql":
            conn.execute(text("DROP VIEW IF EXISTS silver_telemetry"))
            conn.execute(text("DROP TABLE IF EXISTS silver_telemetry"))
            conn.execute(text("CREATE VIEW silver_telemetry AS SELECT * FROM stg_silver_telemetry"))
        else:
            res = conn.execute(text("SELECT type FROM sqlite_master WHERE name='silver_telemetry';")).fetchone()
            if res and res[0] == "table":
                conn.execute(text("DROP TABLE silver_telemetry;"))
            conn.execute(text("CREATE VIEW IF NOT EXISTS silver_telemetry AS SELECT * FROM stg_silver_telemetry;"))

def get_db_session():
    """
    Context manager for database sessions.
    """
    session = SessionLocal()
    try:
        return session
    finally:
        pass
