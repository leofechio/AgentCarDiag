"""
test_modular_api.py — Testes Unitários e de Integração dos Routers Refatorados
AgentCarDiag
"""

import unittest
from fastapi.testclient import TestClient

from app.main import app
from app.config import SYSTEM_VERSION, SERVICE_NAME


class TestRefactoredApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_health_check(self):
        """Verifica se o endpoint /health refatorado responde 200 OK com contrato correto."""
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["service"], SERVICE_NAME)
        self.assertEqual(data["version"], SYSTEM_VERSION)

    def test_dtc_lookup(self):
        """Verifica a consulta ao banco local de DTCs."""
        response = self.client.get("/api/dtc/lookup?code=P0002")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["code"], "P0002")
        self.assertTrue(data["found"])
        self.assertIn("Fuel Volume", data["description"])

    def test_auth_me_unauthorized(self):
        """Verifica se /api/auth/me bloqueia acessos sem autenticação HTTP Basic."""
        response = self.client.get("/api/auth/me")
        self.assertEqual(response.status_code, 401)

    def test_auth_me_admin_success(self):
        """Verifica se o master admin autentica com sucesso."""
        response = self.client.get("/api/auth/me", auth=("admin", "oficina2026"))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["username"], "admin")
        self.assertTrue(data["is_admin"])

    def test_vin_decoder_wmi(self):
        """Verifica a decodificação WMI do chassi da Renault Trafic / Vito."""
        response = self.client.get("/api/vin/decode?vin=VF1FL000000000000")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data.get("valid"))
        self.assertEqual(data.get("make"), "Renault")


if __name__ == "__main__":
    unittest.main()
