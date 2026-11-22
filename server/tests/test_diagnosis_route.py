"""Contrato HTTP da rota de validação cruzada diagnóstica."""

import asyncio
import unittest
from pydantic import ValidationError

from app.main import app
from app.routers.diagnosis import inspect_telemetry
from app.schemas import DiagnosticPayload


class TestDiagnosisRoute(unittest.TestCase):
    def test_route_is_registered_and_returns_deterministic_finding(self):
        operation = app.openapi()["paths"]["/api/diagnose/inspect"]["post"]
        self.assertTrue(operation["requestBody"]["required"])
        self.assertIn("422", operation["responses"])

        response = asyncio.run(
            inspect_telemetry(
                DiagnosticPayload(
                    oem_key="vw_group",
                    can_telemetry={"active_dtcs": []},
                    scope_telemetry={"tooth_offset": 2},
                )
            )
        )

        body = response
        self.assertEqual(body["source"], "LOCAL_DETERMINISTIC")
        self.assertEqual(body["tokens_used"], 0)
        self.assertEqual(body["local_analysis"]["oem_detected"], "Volkswagen AG (VW, Audi, SEAT, Škoda)")
        self.assertEqual(body["local_analysis"]["inconsistencies_count"], 1)
        self.assertEqual(body["ai_verdict"]["certeza_pct"], 99)

    def test_route_rejects_payload_without_oem_key(self):
        with self.assertRaises(ValidationError):
            DiagnosticPayload(can_telemetry={}, scope_telemetry={})


if __name__ == "__main__":
    unittest.main()
