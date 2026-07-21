"""Testes da external_data_api (auth + datasets)."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from fastapi import status
from fastapi.testclient import TestClient

os.environ["EXTERNAL_API_KEY"] = "test-api-key"
os.environ["EXTERNAL_API_SECRET"] = "test-api-secret"
os.environ["EXTERNAL_JWT_SECRET"] = "test-jwt-secret-for-unit-tests"
os.environ.setdefault("CSV_EXPORT_DIR", tempfile.mkdtemp())

from external_data_api.app import app  # noqa: E402


class TestExternalDataAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.TemporaryDirectory()
        root = Path(cls._tmpdir.name)
        (root / "hospitais.csv").write_text(
            "hospital_id,nome,cidade,estado,latitude,longitude\n"
            "1,Hospital Teste,Sao Paulo,SP,-23.5,-46.6\n",
            encoding="utf-8",
        )
        (root / "tecnicos.csv").write_text(
            "tecnico_id,especialidade_id,nome,latitude,longitude,telefone,email,base_latitude,base_longitude\n"
            "1,1,Ana, -23.5,-46.6,11999999999,ana@test.com,-23.5,-46.6\n",
            encoding="utf-8",
        )
        (root / "equipamentos.csv").write_text(
            "equipamento_id,hospital_id,tipo_equipamento,modelo,fabricante,status_operacao,data_instalacao,data_ultima_manutencao,desgaste_acumulado\n"
            "1,1,tc,ModeloX,FabY,ativo,2024-01-01,2024-06-01,0.1\n",
            encoding="utf-8",
        )
        (root / "chamados.csv").write_text(
            "chamado_id,hospital_id,equipamento_id,falha_id,tecnico_id,tipo_chamado,status,data_abertura,data_fechamento,prioridade,descricao,tempo_resposta_horas\n"
            "1,1,1,1,1,corretiva,em andamento,2024-05-01 10:00:00,,alto,teste,\n",
            encoding="utf-8",
        )
        (root / "falhas.csv").write_text(
            "falha_id,equipamento_id,data_hora_falha,tipo_falha,origem_falha,descricao_falha,severidade,status_falha,log_id\n"
            "1,1,2024-05-01 09:00:00,slip,hardware,erro,alto,aberta,1\n",
            encoding="utf-8",
        )
        (root / "manutencao.csv").write_text(
            "manutencao_id,equipamento_id,tecnico_id,chamado_id,data_manutencao,tipo_manutencao,descricao_problema,tempo_reparo,resultado_manutencao\n"
            "1,1,1,1,2024-05-01 12:00:00,corretiva,slip,,em andamento\n",
            encoding="utf-8",
        )
        os.environ["CSV_EXPORT_DIR"] = str(root)
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        cls._tmpdir.cleanup()

    def _token(self) -> str:
        resp = self.client.post(
            "/auth/token",
            json={"api_key": "test-api-key", "api_secret": "test-api-secret"},
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        return resp.json()["access_token"]

    def test_health(self):
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.json()["status"], "ok")

    def test_token_invalid_credentials(self):
        resp = self.client.post(
            "/auth/token",
            json={"api_key": "bad", "api_secret": "bad"},
        )
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_dataset_requires_bearer(self):
        resp = self.client.get("/v1/datasets/hospitais")
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_dataset_invalid_token(self):
        resp = self.client.get(
            "/v1/datasets/hospitais",
            headers={"Authorization": "Bearer not-a-valid-token"},
        )
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_dataset_hospitais_ok(self):
        token = self._token()
        resp = self.client.get(
            "/v1/datasets/hospitais",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        body = resp.json()
        self.assertEqual(body["part"], "hospitais")
        self.assertEqual(len(body["items"]), 1)
        self.assertEqual(body["items"][0]["hospital_id"], "1")
        self.assertEqual(body["items"][0]["nome"], "Hospital Teste")

    def test_dataset_equipamentos_adds_numero_serie(self):
        token = self._token()
        resp = self.client.get(
            "/v1/datasets/equipamentos",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        item = resp.json()["items"][0]
        self.assertEqual(item["numero_serie"], "EQ-1")
        self.assertEqual(item["equipamento_id"], "1")

    def test_dataset_chamados_maps_estado_terminal(self):
        token = self._token()
        resp = self.client.get(
            "/v1/datasets/chamados",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.json()["items"][0]["estado_terminal"], "ATIVO")

    def test_dataset_acoes_from_manutencao(self):
        token = self._token()
        resp = self.client.get(
            "/v1/datasets/acoes",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        item = resp.json()["items"][0]
        self.assertEqual(item["acao_id"], "1")
        self.assertEqual(item["status"], "EM_ANDAMENTO")

    def test_unknown_part_404(self):
        token = self._token()
        resp = self.client.get(
            "/v1/datasets/foobar",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)


if __name__ == "__main__":
    unittest.main()
