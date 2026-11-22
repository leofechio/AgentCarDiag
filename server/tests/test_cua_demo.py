"""Testes de demonstração para os endpoints de saúde e consulta DTC."""

import unittest
from fastapi.testclient import TestClient

from app.config import SERVICE_NAME, SYSTEM_VERSION
from app.main import app


class TestCuaDemo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_health(self):
        response = self.client.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"status": "ok", "service": SERVICE_NAME, "version": SYSTEM_VERSION},
        )

    def test_dtc_lookup_p0002(self):
        response = self.client.get("/api/dtc/lookup?code=P0002")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["code"], "P0002")
        self.assertTrue(data["found"])
        self.assertIn("Fuel Volume", data["description"])


if __name__ == "__main__":
    unittest.main()
