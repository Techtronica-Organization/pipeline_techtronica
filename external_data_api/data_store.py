"""Carrega CSVs de csv_export e normaliza para o formato do import do backend."""
from __future__ import annotations

import csv
import os
from pathlib import Path
from typing import Any, Dict, List

PARTS = ("hospitais", "tecnicos", "equipamentos", "chamados", "falhas", "acoes")

_STATUS_CHAMADO = {
    "em andamento": "ATIVO",
    "aberto": "ATIVO",
    "ativo": "ATIVO",
    "concluido": "CONCLUIDO",
    "concluído": "CONCLUIDO",
    "finalizado": "CONCLUIDO",
    "cancelado": "CANCELADO",
}

_STATUS_ACAO = {
    "RESOLVIDA": "CONCLUIDA",
    "RESOLVIDO": "CONCLUIDA",
    "CONCLUIDA": "CONCLUIDA",
    "CONCLUÍDA": "CONCLUIDA",
    "CONCLUIDO": "CONCLUIDA",
    "CONCLUÍDO": "CONCLUIDA",
    "PENDENTE": "PENDENTE",
    "EM ANDAMENTO": "EM_ANDAMENTO",
    "EM_ANDAMENTO": "EM_ANDAMENTO",
    "CANCELADA": "CANCELADA",
    "CANCELADO": "CANCELADA",
}


def csv_export_dir() -> Path:
    raw = (os.getenv("CSV_EXPORT_DIR") or "").strip()
    if raw:
        return Path(raw)
    return Path(__file__).resolve().parents[1] / "csv_export"


def _read_csv(path: Path) -> List[Dict[str, str]]:
    if not path.is_file():
        raise FileNotFoundError(f"CSV não encontrado: {path}")
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return [dict(row) for row in csv.DictReader(fh)]


def _map_estado_terminal(status: str) -> str:
    key = (status or "").strip().lower()
    return _STATUS_CHAMADO.get(key, "ATIVO")


def _map_status_acao(resultado: str) -> str:
    chave = (resultado or "").strip().upper()
    return _STATUS_ACAO.get(chave, "PENDENTE")


def _normalize_hospitais(rows: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    out = []
    for row in rows:
        out.append(
            {
                "hospital_id": row.get("hospital_id", ""),
                "nome": row.get("nome", ""),
                "cidade": row.get("cidade", ""),
                "estado": row.get("estado", ""),
                "latitude": row.get("latitude", ""),
                "longitude": row.get("longitude", ""),
            }
        )
    return out


def _normalize_tecnicos(rows: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    out = []
    for row in rows:
        out.append(
            {
                "tecnico_id": row.get("tecnico_id", ""),
                "nome": row.get("nome", ""),
                "email": row.get("email", ""),
                "telefone": row.get("telefone", ""),
                "latitude": row.get("latitude", ""),
                "longitude": row.get("longitude", ""),
                "especialidade_id": row.get("especialidade_id", ""),
            }
        )
    return out


def _normalize_equipamentos(rows: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    out = []
    for row in rows:
        eq_id = (row.get("equipamento_id") or "").strip()
        numero_serie = (row.get("numero_serie") or "").strip() or (f"EQ-{eq_id}" if eq_id else "")
        out.append(
            {
                "equipamento_id": eq_id,
                "numero_serie": numero_serie,
                "hospital_id": row.get("hospital_id", ""),
                "tipo_equipamento": row.get("tipo_equipamento", ""),
                "modelo": row.get("modelo", ""),
                "fabricante": row.get("fabricante", ""),
                "status_operacao": row.get("status_operacao", ""),
                "data_instalacao": row.get("data_instalacao", ""),
                "departamento": row.get("departamento", ""),
            }
        )
    return out


def _normalize_chamados(rows: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    out = []
    for row in rows:
        estado = (row.get("estado_terminal") or "").strip()
        if not estado:
            estado = _map_estado_terminal(row.get("status", ""))
        out.append(
            {
                "chamado_id": row.get("chamado_id", ""),
                "hospital_id": row.get("hospital_id", ""),
                "equipamento_id": row.get("equipamento_id", ""),
                "falha_id": row.get("falha_id", ""),
                "data_abertura": row.get("data_abertura", ""),
                "prioridade": row.get("prioridade", ""),
                "estado_terminal": estado,
            }
        )
    return out


def _normalize_falhas(rows: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    out = []
    for row in rows:
        out.append(
            {
                "falha_id": row.get("falha_id", ""),
                "equipamento_id": row.get("equipamento_id", ""),
                "data_hora_falha": row.get("data_hora_falha", ""),
                "tipo_falha": row.get("tipo_falha", ""),
                "origem_falha": row.get("origem_falha", ""),
                "descricao_falha": row.get("descricao_falha", ""),
                "severidade": row.get("severidade", ""),
                "status_falha": row.get("status_falha", ""),
            }
        )
    return out


def _normalize_acoes(rows: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    out = []
    for row in rows:
        if "acao_id" in row:
            out.append(
                {
                    "acao_id": row.get("acao_id", ""),
                    "chamado_id": row.get("chamado_id", ""),
                    "tecnico_id": row.get("tecnico_id", ""),
                    "data_acao": row.get("data_acao", ""),
                    "tipo_acao": row.get("tipo_acao", ""),
                    "descricao": row.get("descricao", ""),
                    "tempo_estimado": row.get("tempo_estimado", ""),
                    "status": row.get("status", ""),
                    "relatorio": row.get("relatorio", ""),
                }
            )
        else:
            out.append(
                {
                    "acao_id": row.get("manutencao_id", ""),
                    "chamado_id": row.get("chamado_id", ""),
                    "tecnico_id": row.get("tecnico_id", ""),
                    "data_acao": row.get("data_manutencao", ""),
                    "tipo_acao": row.get("tipo_manutencao", ""),
                    "descricao": row.get("descricao_problema", ""),
                    "tempo_estimado": row.get("tempo_reparo", ""),
                    "status": _map_status_acao(row.get("resultado_manutencao", "")),
                    "relatorio": "",
                }
            )
    return out


_LOADERS = {
    "hospitais": ("hospitais.csv", _normalize_hospitais),
    "tecnicos": ("tecnicos.csv", _normalize_tecnicos),
    "equipamentos": ("equipamentos.csv", _normalize_equipamentos),
    "chamados": ("chamados.csv", _normalize_chamados),
    "falhas": ("falhas.csv", _normalize_falhas),
    "acoes": ("manutencao.csv", _normalize_acoes),
}


def load_dataset(part: str) -> List[Dict[str, Any]]:
    if part not in _LOADERS:
        raise KeyError(part)
    filename, normalizer = _LOADERS[part]
    base = csv_export_dir()
    path = base / filename
    if part == "acoes" and not path.is_file():
        alt = base / "acoes.csv"
        if alt.is_file():
            path = alt
    return normalizer(_read_csv(path))
