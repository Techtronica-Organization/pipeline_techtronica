from __future__ import annotations

import json
import os
import random
import sqlite3
from datetime import datetime
from typing import Any

from monitoring_service.config import Config
from monitoring_service.equipment_types import slug_to_simulator_tipo, simulator_tipo_to_slug
from monitoring_service.simulators.base import inicializar_estado_temporal

DB_PATH = Config.SIMULATION_DB_PATH


def _connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_columns(cur: sqlite3.Cursor) -> None:
    cur.execute("PRAGMA table_info(sim_equipamentos)")
    existing = {row[1] for row in cur.fetchall()}
    migrations = {
        "numero_serie": "ALTER TABLE sim_equipamentos ADD COLUMN numero_serie TEXT",
        "telemetry_enabled": "ALTER TABLE sim_equipamentos ADD COLUMN telemetry_enabled INTEGER NOT NULL DEFAULT 1",
    }
    for column, ddl in migrations.items():
        if column not in existing:
            cur.execute(ddl)


def init_db() -> None:
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS sim_equipamentos (
            equipamento_id INTEGER PRIMARY KEY AUTOINCREMENT,
            hospital_id INTEGER NOT NULL DEFAULT 1,
            numero_serie TEXT UNIQUE,
            tipo TEXT NOT NULL,
            modelo TEXT NOT NULL,
            fabricante TEXT NOT NULL,
            idade_dias INTEGER NOT NULL,
            desgaste REAL NOT NULL,
            carga_acumulada REAL NOT NULL,
            ultima_manutencao TEXT,
            estado_operacional_interno TEXT NOT NULL,
            modo_falha_ativo TEXT,
            intensidade_falha REAL NOT NULL,
            horas_falha_restantes INTEGER NOT NULL,
            ultimo_estado_temporal TEXT NOT NULL,
            telemetry_enabled INTEGER NOT NULL DEFAULT 1
        )
        """
    )
    _ensure_columns(cur)
    cur.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_sim_equipamentos_numero_serie ON sim_equipamentos(numero_serie)"
    )
    conn.commit()

    cur.execute("SELECT COUNT(*) FROM sim_equipamentos")
    count = cur.fetchone()[0]
    if count == 0:
        initialize_equipments_from_csv(conn)
    else:
        _backfill_numero_serie(conn)
    conn.close()


def _backfill_numero_serie(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.execute("SELECT equipamento_id, numero_serie FROM sim_equipamentos")
    for row in cur.fetchall():
        if not row["numero_serie"]:
            cur.execute(
                "UPDATE sim_equipamentos SET numero_serie = ? WHERE equipamento_id = ?",
                (f"SN-{row['equipamento_id']}", row["equipamento_id"]),
            )
    conn.commit()


def initialize_equipments_from_csv(sim_conn: sqlite3.Connection) -> None:
    import csv

    csv_path = Config.CSV_PATH
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"Arquivo CSV de equipamentos nao encontrado em: {csv_path}")

    sim_cur = sim_conn.cursor()
    hoje = datetime.now()
    carregados = 0

    with open(csv_path, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            h_id = int(row["hospital_id"])
            if h_id not in Config.HOSPITAL_IDS:
                continue
            eq_id = int(row["equipamento_id"])
            tipo = row["tipo_equipamento"]
            modelo = row["modelo"]
            fabricante = row["fabricante"]
            desgaste = float(row["desgaste_acumulado"])
            data_instalacao_str = row["data_instalacao"]
            data_ultima_manut_str = row["data_ultima_manutencao"]
            numero_serie = (row.get("numero_serie") or "").strip() or f"SN-{eq_id}"

            try:
                data_inst = datetime.strptime(data_instalacao_str, "%Y-%m-%d")
                idade_dias = (hoje - data_inst).days
            except Exception:
                idade_dias = random.randint(100, 1000)

            estado_fisico = inicializar_estado_temporal(tipo, desgaste)
            if "scan_count" in estado_fisico:
                carga_acumulada = estado_fisico["scan_count"]
            elif "exposure_count" in estado_fisico:
                carga_acumulada = estado_fisico["exposure_count"]
            else:
                carga_acumulada = random.randint(100, 10000)

            estado_op = "DEGRADANDO" if desgaste >= 0.55 else "NORMAL"
            sim_cur.execute(
                """
                INSERT INTO sim_equipamentos (
                    equipamento_id, hospital_id, numero_serie, tipo, modelo, fabricante,
                    idade_dias, desgaste, carga_acumulada, ultima_manutencao,
                    estado_operacional_interno, modo_falha_ativo, intensidade_falha,
                    horas_falha_restantes, ultimo_estado_temporal, telemetry_enabled
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 0.0, 0, ?, 1)
                """,
                (
                    eq_id,
                    h_id,
                    numero_serie,
                    tipo,
                    modelo,
                    fabricante,
                    idade_dias,
                    desgaste,
                    carga_acumulada,
                    data_ultima_manut_str,
                    estado_op,
                    json.dumps(estado_fisico),
                ),
            )
            carregados += 1

    sim_conn.commit()
    print(
        f"Banco de simulacao inicializado com {carregados} equipamentos "
        f"de {len(Config.HOSPITAL_IDS)} hospitais."
    )


def _row_to_equipment(row: sqlite3.Row) -> dict[str, Any]:
    eq = dict(row)
    eq["ultimo_estado_temporal"] = json.loads(eq["ultimo_estado_temporal"])
    eq["telemetry_enabled"] = bool(eq.get("telemetry_enabled", 1))
    if not eq.get("numero_serie"):
        eq["numero_serie"] = f"SN-{eq['equipamento_id']}"
    eq["tipo_slug"] = simulator_tipo_to_slug(eq["tipo"])
    return eq


def get_all_equipments(only_enabled: bool = True) -> list[dict[str, Any]]:
    conn = _connect()
    cur = conn.cursor()
    if only_enabled:
        cur.execute("SELECT * FROM sim_equipamentos WHERE telemetry_enabled = 1")
    else:
        cur.execute("SELECT * FROM sim_equipamentos")
    equipments = [_row_to_equipment(r) for r in cur.fetchall()]
    conn.close()
    return equipments


def get_equipment_by_numero_serie(numero_serie: str) -> dict[str, Any] | None:
    conn = _connect()
    cur = conn.cursor()
    cur.execute("SELECT * FROM sim_equipamentos WHERE numero_serie = ?", (numero_serie,))
    row = cur.fetchone()
    conn.close()
    return _row_to_equipment(row) if row else None


def update_equipment(eq: dict[str, Any]) -> None:
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE sim_equipamentos
        SET idade_dias = ?,
            desgaste = ?,
            carga_acumulada = ?,
            ultima_manutencao = ?,
            estado_operacional_interno = ?,
            modo_falha_ativo = ?,
            intensidade_falha = ?,
            horas_falha_restantes = ?,
            ultimo_estado_temporal = ?,
            telemetry_enabled = ?
        WHERE equipamento_id = ?
        """,
        (
            eq["idade_dias"],
            eq["desgaste"],
            eq["carga_acumulada"],
            eq["ultima_manutencao"],
            eq["estado_operacional_interno"],
            eq["modo_falha_ativo"],
            eq["intensidade_falha"],
            eq["horas_falha_restantes"],
            json.dumps(eq["ultimo_estado_temporal"]),
            1 if eq.get("telemetry_enabled", True) else 0,
            eq["equipamento_id"],
        ),
    )
    conn.commit()
    conn.close()


def upsert_telemetry_equipment(
    *,
    numero_serie: str,
    tipo: str,
    modelo: str | None = None,
    fabricante: str | None = None,
    hospital_id: int | None = None,
    telemetry_enabled: bool = True,
) -> dict[str, Any]:
    numero_serie = numero_serie.strip()
    if not numero_serie:
        raise ValueError("numero_serie obrigatorio")

    simulator_tipo = slug_to_simulator_tipo(tipo)
    existing = get_equipment_by_numero_serie(numero_serie)
    desgaste = existing["desgaste"] if existing else 0.15
    estado_fisico = (
        existing["ultimo_estado_temporal"]
        if existing
        else inicializar_estado_temporal(simulator_tipo, desgaste)
    )

    if "scan_count" in estado_fisico:
        carga = estado_fisico["scan_count"]
    elif "exposure_count" in estado_fisico:
        carga = estado_fisico["exposure_count"]
    else:
        carga = existing["carga_acumulada"] if existing else 1000.0

    payload = {
        "hospital_id": hospital_id if hospital_id is not None else (existing["hospital_id"] if existing else 1),
        "numero_serie": numero_serie,
        "tipo": simulator_tipo,
        "modelo": (modelo or (existing["modelo"] if existing else "desconhecido")).strip() or "desconhecido",
        "fabricante": (
            fabricante or (existing["fabricante"] if existing else "desconhecido")
        ).strip()
        or "desconhecido",
        "idade_dias": existing["idade_dias"] if existing else 365,
        "desgaste": desgaste,
        "carga_acumulada": carga,
        "ultima_manutencao": existing["ultima_manutencao"] if existing else None,
        "estado_operacional_interno": existing["estado_operacional_interno"] if existing else "NORMAL",
        "modo_falha_ativo": existing["modo_falha_ativo"] if existing else None,
        "intensidade_falha": existing["intensidade_falha"] if existing else 0.0,
        "horas_falha_restantes": existing["horas_falha_restantes"] if existing else 0,
        "ultimo_estado_temporal": json.dumps(estado_fisico),
        "telemetry_enabled": 1 if telemetry_enabled else 0,
    }

    conn = _connect()
    cur = conn.cursor()
    if existing:
        cur.execute(
            """
            UPDATE sim_equipamentos
            SET hospital_id = ?, tipo = ?, modelo = ?, fabricante = ?,
                ultimo_estado_temporal = ?, telemetry_enabled = ?
            WHERE numero_serie = ?
            """,
            (
                payload["hospital_id"],
                payload["tipo"],
                payload["modelo"],
                payload["fabricante"],
                payload["ultimo_estado_temporal"],
                payload["telemetry_enabled"],
                numero_serie,
            ),
        )
    else:
        cur.execute(
            """
            INSERT INTO sim_equipamentos (
                hospital_id, numero_serie, tipo, modelo, fabricante, idade_dias, desgaste,
                carga_acumulada, ultima_manutencao, estado_operacional_interno, modo_falha_ativo,
                intensidade_falha, horas_falha_restantes, ultimo_estado_temporal, telemetry_enabled
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload["hospital_id"],
                payload["numero_serie"],
                payload["tipo"],
                payload["modelo"],
                payload["fabricante"],
                payload["idade_dias"],
                payload["desgaste"],
                payload["carga_acumulada"],
                payload["ultima_manutencao"],
                payload["estado_operacional_interno"],
                payload["modo_falha_ativo"],
                payload["intensidade_falha"],
                payload["horas_falha_restantes"],
                payload["ultimo_estado_temporal"],
                payload["telemetry_enabled"],
            ),
        )
    conn.commit()
    conn.close()
    return get_equipment_by_numero_serie(numero_serie)
