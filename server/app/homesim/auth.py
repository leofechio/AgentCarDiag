import hashlib
import hmac
import os
import json
import base64
import time
from typing import Optional, Dict, Any

try:
    import app.config as _cfg  # noqa: F401 (garante carregamento de server/.env)
except Exception:
    pass

AUTH_SECRET = os.environ.get("HOMESIM_AUTH_SECRET", "")

def hash_password(password: str) -> str:
    """Gera hash seguro com Salt usando SHA256 (sem dependência externa pesada)."""
    salt = os.urandom(16).hex()
    pwd_hash = hashlib.sha256((salt + password).encode()).hexdigest()
    return f"{salt}:{pwd_hash}"

def verify_password(password: str, stored_hash: str) -> bool:
    """Valida se a senha corresponde ao hash armazenado."""
    try:
        salt, expected_hash = stored_hash.split(":", 1)
        actual_hash = hashlib.sha256((salt + password).encode()).hexdigest()
        return hmac.compare_digest(actual_hash, expected_hash)
    except Exception:
        return False

def create_session_token(user_id: int, email: str, expires_in_days: int = 30) -> str:
    """Cria um token JWT-compatível assinado com HMAC-SHA256."""
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "uid": user_id,
        "email": email,
        "exp": int(time.time()) + (expires_in_days * 86400)
    }
    
    b64_header = base64.urlsafe_b64encode(json.dumps(header).encode()).decode().rstrip("=")
    b64_payload = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    message = f"{b64_header}.{b64_payload}"
    signature = hmac.new(AUTH_SECRET.encode(), message.encode(), hashlib.sha256).digest()
    b64_sig = base64.urlsafe_b64encode(signature).decode().rstrip("=")
    return f"{message}.{b64_sig}"

def verify_session_token(token: str) -> Optional[Dict[str, Any]]:
    """Valida e decodifica o token de sessão."""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        b64_header, b64_payload, b64_sig = parts
        message = f"{b64_header}.{b64_payload}"
        expected_sig = hmac.new(AUTH_SECRET.encode(), message.encode(), hashlib.sha256).digest()
        
        # Corrige padding base64
        rem = len(b64_sig) % 4
        padded_sig = b64_sig + ("=" * (4 - rem) if rem else "")
        actual_sig = base64.urlsafe_b64decode(padded_sig.encode())
        
        if not hmac.compare_digest(expected_sig, actual_sig):
            return None
            
        rem_p = len(b64_payload) % 4
        padded_p = b64_payload + ("=" * (4 - rem_p) if rem_p else "")
        payload_data = json.loads(base64.urlsafe_b64decode(padded_p.encode()).decode())
        
        if payload_data.get("exp", 0) < time.time():
            return None
            
        return payload_data
    except Exception:
        return None
