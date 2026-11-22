"""
test_honeypot_auth.py — Suíte de Testes da Autenticação Multi-Box Honeypot Defense
AgentCarDiag Full-Stack Cybersecurity Test Suite
"""

import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from starlette.testclient import TestClient

from app.main import app
from app.config import (
    DATA_DIR,
    USERS_CONFIG_PATH,
    BLOCKED_IPS_JSON_PATH,
    USER_FOLDERS_ROOT,
    MAX_AUTH_ATTEMPTS,
    HONEYPOT_LOCKOUT_SECONDS
)
from app.security.honeypot_auth import (
    get_client_ip,
    load_users_config,
    get_all_blocked_ips,
    unblock_ip_manual,
    create_session_token,
    verify_session_token,
    SESSION_COOKIE_NAME
)


class TestMultiBoxHoneypotDefense(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import asyncio
        from app import database as db
        asyncio.run(db.init_db())
        # Simulate a local reverse proxy, which is trusted by default.
        cls.client = TestClient(app, client=("127.0.0.1", 50000))

    def setUp(self):
        # Limpa IPs de teste antes de cada caso
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        for ip in ["192.168.1.100", "192.168.1.101", "192.168.1.102", "192.168.1.103", "203.0.113.195", "198.51.100.42", "192.0.2.77", "127.0.0.1", "testclient"]:
            loop.run_until_complete(unblock_ip_manual(ip))
        loop.close()

    def test_frontend_login_page_contract(self):
        """
        Verifica a interface visual anônima e minimalista (/login):
        1. 5 caixas de entrada neutras (b1..b5) e botão ENTER.
        2. Sem labels ou placeholders vazando contexto de usuário ou senha.
        3. Compatibilidade mobile com font-size: 16px e touch-action: manipulation.
        """
        response = self.client.get("/login")
        self.assertEqual(response.status_code, 200)
        html = response.text

        # Verifica presença dos 5 inputs neutros
        for i in range(1, 6):
            self.assertIn(f'id="b{i}"', html)
            self.assertIn(f'name="b{i}"', html)

        # Verifica botão ENTER
        self.assertIn("ENTER", html)

        # Garante ausência de rótulos/labels de formulário tradicional
        self.assertNotIn("<label", html.lower())
        self.assertNotIn("placeholder", html.lower())
        self.assertNotIn("usuário", html.lower())
        self.assertNotIn("senha", html.lower())

        # Verifica requisitos mobile
        self.assertIn("font-size: 16px", html)
        self.assertIn("touch-action: manipulation", html)

    def test_quantity_strict_rule_ban(self):
        """
        Regra da Quantidade Estrita:
        Se tiver 0, 1, 2, 4 ou 5 caixas preenchidas -> Ban imediato (HTTP 403).
        """
        # Apenas 2 caixas preenchidas (ex: 1 e 3)
        r2 = self.client.post(
            "/api/auth/login",
            json={"boxes": ["50", "", "Ñ@", "", ""]},
            headers={"X-Forwarded-For": "192.168.1.100"}
        )
        self.assertEqual(r2.status_code, 403)

        # Apenas 1 caixa preenchida
        r1 = self.client.post(
            "/api/auth/login",
            json={"boxes": ["", "admin", "", "", ""]},
            headers={"X-Forwarded-For": "192.168.1.101"}
        )
        self.assertEqual(r1.status_code, 403)

        # 4 caixas preenchidas
        r4 = self.client.post(
            "/api/auth/login",
            json={"boxes": ["a", "b", "c", "d", ""]},
            headers={"X-Forwarded-For": "192.168.1.102"}
        )
        self.assertEqual(r4.status_code, 403)

        # 5 caixas preenchidas (autofill de bot)
        r5 = self.client.post(
            "/api/auth/login",
            json={"boxes": ["a", "b", "c", "d", "e"]},
            headers={"X-Forwarded-For": "192.168.1.103"}
        )
        self.assertEqual(r5.status_code, 403)

    def test_invalid_pattern_signature_ban(self):
        """
        Regra da Assinatura de Posição:
        Preencheu 3 caixas, mas em linhas que nenhum usuário cadastrado utiliza
        (ex: Linhas 1, 2 e 3 preenchidas) -> Ban imediato (HTTP 403).
        """
        test_ip = "192.168.1.100"
        payload = {
            "boxes": ["dado1", "dado2", "dado3", "", ""]
        }
        response = self.client.post(
            "/api/auth/login",
            json=payload,
            headers={"X-Forwarded-For": test_ip}
        )
        self.assertEqual(response.status_code, 403)
        self.assertIn("Acesso Negado", response.json()["detail"])

    def test_random_lines_user_pattern(self):
        """
        Testa usuário com linhas aleatórias 1, 3 e 4:
        usuario_teste: ["50", "", "Ñ@", "nada", ""]
        - Acerto -> 200 OK
        - Erro no conteúdo mantendo posições 1, 3 e 4 -> Permite até 3 tentativas (401) e depois Ban (403).
        """
        test_ip = "192.168.1.102"
        # Erro de digitação na linha 4 (tentativa 1)
        r1 = self.client.post(
            "/api/auth/login",
            json={"boxes": ["50", "", "Ñ@", "errado", ""]},
            headers={"X-Forwarded-For": test_ip}
        )
        self.assertEqual(r1.status_code, 401)
        self.assertIn("Tentativas restantes antes do bloqueio: 2", r1.json()["detail"])

        # Tentativa 2
        r2 = self.client.post(
            "/api/auth/login",
            json={"boxes": ["50", "", "Ñ@", "errado", ""]},
            headers={"X-Forwarded-For": test_ip}
        )
        self.assertEqual(r2.status_code, 401)

        # Tentativa 3 -> Lockout de 15 min
        r3 = self.client.post(
            "/api/auth/login",
            json={"boxes": ["50", "", "Ñ@", "errado", ""]},
            headers={"X-Forwarded-For": test_ip}
        )
        self.assertEqual(r3.status_code, 403)

    def test_brute_force_lockout_after_3_attempts(self):
        """
        Campos honeypot vazios, mas credenciais erradas:
        - 1ª tentativa: 401 (2 restantes)
        - 2ª tentativa: 401 (1 restante)
        - 3ª tentativa: 403 (Lockout temporário de 15 minutos ativado)
        - 4ª tentativa: 403 (Rejeitada por ban ativo)
        """
        test_ip = "192.168.1.102"
        wrong_payload = {
            "boxes": ["", "usuario_errado", "", "99", "senha_errada"]
        }

        # Tentativa 1
        r1 = self.client.post("/api/auth/login", json=wrong_payload, headers={"X-Forwarded-For": test_ip})
        self.assertEqual(r1.status_code, 401)
        self.assertIn("Tentativas restantes antes do bloqueio: 2", r1.json()["detail"])

        # Tentativa 2
        r2 = self.client.post("/api/auth/login", json=wrong_payload, headers={"X-Forwarded-For": test_ip})
        self.assertEqual(r2.status_code, 401)
        self.assertIn("Tentativas restantes antes do bloqueio: 1", r2.json()["detail"])

        # Tentativa 3 -> Aciona Ban de 15 min
        r3 = self.client.post("/api/auth/login", json=wrong_payload, headers={"X-Forwarded-For": test_ip})
        self.assertEqual(r3.status_code, 403)
        self.assertIn("15 minutos", r3.json()["detail"])

        # Tentativa 4 -> Já bloqueado
        r4 = self.client.post("/api/auth/login", json=wrong_payload, headers={"X-Forwarded-For": test_ip})
        self.assertEqual(r4.status_code, 403)
        self.assertIn("bloqueado", r4.json()["detail"].lower())

    def test_dynamic_multi_user_authentication(self):
        """
        Valida login dos usuários configurados dinamicamente no usuarios.json local.
        """
        users = load_users_config()
        self.assertTrue(len(users) >= 1, "Nenhum usuário configurado em usuarios.json local")
        for uname, udata in list(users.items())[:2]:
            payload = {"boxes": udata["boxes"]}
            r = self.client.post("/api/auth/login", json=payload, headers={"X-Forwarded-For": "192.168.1.103"})
            self.assertEqual(r.status_code, 200)
            data = r.json()
            self.assertEqual(data["status"], "ok")
            self.assertEqual(data["user"], uname)
            self.assertEqual(data["folder"], udata["folder"])
            self.assertIn("token", data)
            self.assertTrue((USER_FOLDERS_ROOT / udata["folder"]).exists())

    def test_real_ip_detection_headers(self):
        """
        Testa extração de IP real priorizando CF-Connecting-IP e X-Forwarded-For.
        """
        # 1. Cloudflare CF-Connecting-IP
        r_cf = self.client.get("/api/auth/status", headers={"CF-Connecting-IP": "203.0.113.195"})
        self.assertEqual(r_cf.json()["client_ip"], "203.0.113.195")

        # 2. X-Forwarded-For (seleciona o salto não confiável mais próximo do proxy)
        r_xff = self.client.get("/api/auth/status", headers={"X-Forwarded-For": "198.51.100.42, 10.0.0.1"})
        self.assertEqual(r_xff.json()["client_ip"], "10.0.0.1")

        # 3. X-Real-IP
        r_real = self.client.get("/api/auth/status", headers={"X-Real-IP": "192.0.2.77"})
        self.assertEqual(r_real.json()["client_ip"], "192.0.2.77")

    def test_untrusted_peer_cannot_spoof_forwarded_ip(self):
        """Forwarding headers from a direct, untrusted client must be ignored."""
        direct_client = TestClient(app, client=("198.51.100.10", 50000))
        response = direct_client.get(
            "/api/auth/status",
            headers={"X-Forwarded-For": "192.0.2.99", "CF-Connecting-IP": "192.0.2.98"},
        )
        self.assertEqual(response.json()["client_ip"], "198.51.100.10")

    def test_persistence_in_sqlite_and_json(self):
        """
        Verifica se o banimento persiste tanto no SQLite (blocked_ips) quanto no arquivo JSON sincronizado.
        """
        test_ip = "192.168.1.100"
        # Dispara honeypot para o IP
        self.client.post(
            "/api/auth/login",
            json={"boxes": ["attacker", "any", "", "any", "any"]},
            headers={"X-Forwarded-For": test_ip}
        )

        # Verifica no arquivo JSON
        self.assertTrue(BLOCKED_IPS_JSON_PATH.exists())
        with open(BLOCKED_IPS_JSON_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertIn(test_ip, data)
        self.assertEqual(data[test_ip]["ip"], test_ip)
        self.assertTrue("TRAP" in data[test_ip]["reason"] or "HONEYPOT" in data[test_ip]["reason"])
        self.assertGreater(data[test_ip]["expires_at"], 0)

    def test_session_cookie_dashboard_access(self):
        """
        Verifica se após o login com sucesso no Multi-Box, o cookie de sessão permite
        acessar o dashboard / normalmente sem disparar basic auth.
        """
        login_res = self.client.post(
            "/api/auth/login",
            json={"boxes": ["", "tomate", "", "10", "Fnglckh14p@"]}
        )
        self.assertEqual(login_res.status_code, 200)

        # O TestClient armazena automaticamente os cookies definidos na resposta
        dash_res = self.client.get("/", follow_redirects=False)
        self.assertEqual(dash_res.status_code, 200)
        self.assertIn("<!DOCTYPE html>", dash_res.text)


if __name__ == "__main__":
    unittest.main()
