import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# Database configuration environment variables
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "strongpassword123")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "serving_db")

# Detect if we should use PostgreSQL or fallback to SQLite for offline testing/development
USE_POSTGRES = os.getenv("USE_POSTGRES", "false").lower() == "true" or os.getenv("DB_HOST") is not None

if USE_POSTGRES:
    DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    # Postgres engine parameters
    engine = create_engine(DATABASE_URL, pool_size=10, max_overflow=20)
else:
    # Local SQLite fallback for host-based integration testing
    sqlite_path = Path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "serving_database.db"))
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
            if engine.dialect.name == "postgresql":
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
