from __future__ import annotations

import os
from urllib.parse import quote_plus

from sqlalchemy import create_engine, text


def db_dialect() -> str:
    return os.getenv("DB_DIALECT", os.getenv("SQLALCHEMY_DIALECT", "mysql+pymysql")).strip()


def db_settings() -> tuple[str, str, str, str, str]:
    dialect = db_dialect()
    default_user = "root" if dialect.startswith("mysql") else "postgres"
    default_password = "supersenha" if dialect.startswith("mysql") else "strongpassword123"
    default_port = "3306" if dialect.startswith("mysql") else "5432"
    default_name = "techtronica_pipeline" if dialect.startswith("mysql") else "serving_db"
    return (
        os.getenv("DB_USER", default_user),
        os.getenv("DB_PASSWORD", default_password),
        os.getenv("DB_HOST", "localhost"),
        os.getenv("DB_PORT", default_port),
        os.getenv("DB_NAME", default_name),
    )


def sqlalchemy_database_url(*, include_database: bool = True) -> str:
    dialect = db_dialect()
    user, password, host, port, name = db_settings()
    auth = f"{quote_plus(user)}:{quote_plus(password)}"
    base = f"{dialect}://{auth}@{host}:{port}"
    return f"{base}/{name}" if include_database else base


def ensure_database_exists() -> None:
    dialect = db_dialect()
    if not dialect.startswith("mysql"):
        return
    _, _, _, _, name = db_settings()
    escaped_name = name.replace("`", "``")
    engine = create_engine(sqlalchemy_database_url(include_database=False), pool_pre_ping=True)
    with engine.begin() as conn:
        conn.execute(text(f"CREATE DATABASE IF NOT EXISTS `{escaped_name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"))
    engine.dispose()
