import unittest
from unittest.mock import MagicMock
from fastapi import status
from fastapi.testclient import TestClient

import os
from datetime import datetime

os.environ["PIPELINE_INTERNAL_TOKEN"] = "test-pipeline-token-ok"
os.environ["PIPELINE_ENV"] = "dev"

mock_db = MagicMock()


def mock_get_db():
    yield mock_db


import serving_api.database.connection

serving_api.database.connection.get_db = mock_get_db

from serving_api.main import app
from data_pipeline.database.models import SilverTelemetry, GoldEquipmentFeatures

_AUTH = {"X-Internal-Token": "test-pipeline-token-ok"}


class TestServingAPI(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        mock_db.reset_mock()
        mock_db.execute.side_effect = None

    def test_health_check_healthy(self):
        mock_db.execute.return_value = MagicMock()
        response = self.client.get("/api/v1/health")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["status"], "healthy")

    def test_health_check_unhealthy(self):
        mock_db.execute.side_effect = Exception("Conexão falhou")
        response = self.client.get("/api/v1/health")
        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)

    def test_telemetry_requires_auth(self):
        response = self.client.get("/api/v1/equipments/1/telemetry")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_get_telemetry_not_found(self):
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = []
        response = self.client.get("/api/v1/equipments/999/telemetry", headers=_AUTH)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_get_telemetry_success(self):
        t_now = datetime(2026, 6, 7, 12, 0, 0)
        mock_record = SilverTelemetry(
            timestamp=t_now,
            equipamento_id=1,
            hospital_id=1,
            tipo="tc",
            is_interpolated=False,
            tube_temp=42.5,
            gantry_vibration_fft=0.31,
        )
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = [mock_record]
        response = self.client.get("/api/v1/equipments/1/telemetry", headers=_AUTH)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()[0]
        self.assertEqual(data["equipamento_id"], 1)
        self.assertEqual(data["tube_temp"], 42.5)
        self.assertEqual(data["timestamp"], t_now.isoformat())
        self.assertNotIn("exposure_count", data)

    def test_get_features_success(self):
        t_now = datetime(2026, 6, 7, 12, 0, 0)
        mock_feature_record = GoldEquipmentFeatures(
            timestamp=t_now,
            equipamento_id=1,
            is_interpolated=True,
            features={"tube_temp_mean_6h": 44.0, "vibration_std_12h": 0.05},
        )
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.first.return_value = mock_feature_record
        response = self.client.get("/api/v1/equipments/1/features", headers=_AUTH)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["equipamento_id"], 1)
        self.assertTrue(data["is_interpolated"])
        self.assertEqual(data["features"]["tube_temp_mean_6h"], 44.0)

    def test_get_hospital_telemetry_success(self):
        t_now = datetime(2026, 6, 7, 12, 0, 0)
        mock_record = SilverTelemetry(
            timestamp=t_now,
            equipamento_id=1,
            hospital_id=1,
            tipo="tc",
            is_interpolated=False,
            tube_temp=42.5,
        )
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = [mock_record]
        response = self.client.get("/api/v1/hospitals/1/telemetry", headers=_AUTH)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()[0]["hospital_id"], 1)

    def test_get_hospital_features_success(self):
        t_now = datetime(2026, 6, 7, 12, 0, 0)
        mock_feature_record = GoldEquipmentFeatures(
            timestamp=t_now,
            equipamento_id=1,
            is_interpolated=False,
            features={"tube_temp_mean_6h": 44.0},
        )
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.distinct.return_value = mock_query
        mock_query.all.return_value = [(1,)]
        mock_query.order_by.return_value = mock_query
        mock_query.first.return_value = mock_feature_record
        response = self.client.get("/api/v1/hospitals/1/features", headers=_AUTH)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()[0]["equipamento_id"], 1)

    def test_get_hospital_equipment_data_success(self):
        t_now = datetime(2026, 6, 7, 12, 0, 0)
        mock_record = SilverTelemetry(
            timestamp=t_now,
            equipamento_id=1,
            hospital_id=1,
            tipo="tc",
            is_interpolated=False,
            tube_temp=42.5,
        )
        mock_feature_record = GoldEquipmentFeatures(
            timestamp=t_now,
            equipamento_id=1,
            is_interpolated=False,
            features={"tube_temp_mean_6h": 44.0},
        )
        mock_query_telemetry = MagicMock()
        mock_db.query.return_value = mock_query_telemetry
        mock_query_telemetry.filter.return_value = mock_query_telemetry
        mock_query_telemetry.order_by.return_value = mock_query_telemetry
        mock_query_telemetry.limit.return_value = mock_query_telemetry
        mock_query_telemetry.all.return_value = [mock_record]
        mock_query_telemetry.first.return_value = mock_feature_record
        response = self.client.get("/api/v1/hospitals/1/equipments/1", headers=_AUTH)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["hospital_id"], 1)
        self.assertEqual(len(data["telemetry"]), 1)
        self.assertEqual(data["features"]["features"]["tube_temp_mean_6h"], 44.0)

    def test_get_hospital_equipment_data_not_found(self):
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = []
        response = self.client.get("/api/v1/hospitals/1/equipments/999", headers=_AUTH)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


if __name__ == "__main__":
    unittest.main()
