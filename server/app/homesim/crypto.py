import os
import base64
import hashlib
import json
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

def derive_key(secret: str) -> bytes:
    """Deriva chave AES-256 (32 bytes) a partir da chave secreta compartilhada"""
    return hashlib.sha256(secret.encode("utf-8")).digest()

def encrypt_payload(data: dict, secret: str) -> str:
    """Cifra dados JSON usando AES-256-GCM. Retorna string Base64 contendo IV (12B) + Dados Cifrados + Tag GCM"""
    if not secret:
        return ""
    key = derive_key(secret)
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)  # 12 bytes nonce (96 bits padrão NIST para GCM)
    plaintext = json.dumps(data).encode("utf-8")
    ciphertext = aesgcm.encrypt(nonce, plaintext, None)
    # Formato: 12 bytes IV + ciphertext (que já inclui a tag GCM de 16 bytes no final)
    full_payload = nonce + ciphertext
    return base64.b64encode(full_payload).decode("utf-8")

def decrypt_payload(encrypted_b64: str, secret: str) -> dict:
    """Descriptografa payload Base64 AES-256-GCM e retorna dicionário decodificado"""
    if not secret:
        raise ValueError("Chave secreta não configurada")
    key = derive_key(secret)
    aesgcm = AESGCM(key)
    full_payload = base64.b64decode(encrypted_b64.encode("utf-8"))
    if len(full_payload) < 28: # 12 bytes nonce + 16 bytes tag mínimo
        raise ValueError("Payload cifrado inválido ou truncado")
    nonce = full_payload[:12]
    ciphertext = full_payload[12:]
    decrypted_bytes = aesgcm.decrypt(nonce, ciphertext, None)
    return json.loads(decrypted_bytes.decode("utf-8"))
