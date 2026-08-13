import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

class Config:
    # Database configurations
    DB_DIALECT = os.getenv("DB_DIALECT", "mysql+pymysql")
    DB_USER = os.getenv("DB_USER", "root" if DB_DIALECT.startswith("mysql") else "postgres")
    DB_PASSWORD = os.getenv("DB_PASSWORD", "supersenha" if DB_DIALECT.startswith("mysql") else "strongpassword123")
    DB_HOST = os.getenv("DB_HOST", "localhost")
    DB_PORT = os.getenv("DB_PORT", "3306" if DB_DIALECT.startswith("mysql") else "5432")
    DB_NAME = os.getenv("DB_NAME", "techtronica_pipeline" if DB_DIALECT.startswith("mysql") else "serving_db")
    
    USE_SQL_DB = os.getenv("USE_SQL_DB", os.getenv("USE_POSTGRES", "false")).lower() == "true" or os.getenv("DB_HOST") is not None
    USE_POSTGRES = USE_SQL_DB and DB_DIALECT.startswith("postgresql")
