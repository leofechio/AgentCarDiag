"""
Módulo de Algoritmos de Desbloqueio de Segurança UDS (Serviço 0x27 - Seed/Key)
Suporte para famílias de centrais de injeção e módulos eletrônicos.
Engenharia reversa integrada via VAGFlasher, SA2 e bancos de dados UDS.
"""
from typing import Dict, Callable

class SecurityAccessError(Exception):
    pass

def _ror32(val: int, n: int) -> int:
    """Rotate Right 32-bit."""
    n &= 31
    return ((val >> n) | (val << (32 - n))) & 0xFFFFFFFF

def _rol32(val: int, n: int) -> int:
    """Rotate Left 32-bit."""
    n &= 31
    return ((val << n) | (val >> (32 - n))) & 0xFFFFFFFF

# ── 1. Bosch ME17 / MED17 (BiWbBuD101 - VAG EA888 / 2.0 TSI / TFSI) ─────────
def calc_sa2_bosch_me17(seed: bytes) -> bytes:
    """
    Algoritmo oficial Bosch ME17.5 / MED17 (EA888 Gen1/1.5).
    5 rounds de Feistel-style com constante de segurança 0x1A76B3C4.
    """
    if len(seed) < 4:
        raise SecurityAccessError(f"Seed deve ter 4 bytes, recebido: {len(seed)}")
    s = int.from_bytes(seed[:4], 'big')
    K = 0x1A76B3C4
    for _ in range(5):
        s = _ror32(s ^ K, 3)
        s = (s + K) & 0xFFFFFFFF
    return s.to_bytes(4, 'big')

# ── 2. Bosch MED9.1 (Golf GTI Mk5 / Audi TFSI EA113 / Porsche Cayenne) ───────
def calc_sa2_bosch_med91(seed: bytes) -> bytes:
    """
    Algoritmo Bosch MED9.1 (Processador MPC5xx PowerPC).
    Constante 0x5FBD5DBD com rotação variável a cada round.
    """
    if len(seed) < 4:
        raise SecurityAccessError(f"Seed deve ter 4 bytes, recebido: {len(seed)}")
    s = int.from_bytes(seed[:4], 'big')
    K = 0x5FBD5DBD
    for i in range(5):
        shift = (i * 7) & 31
        s = (s ^ K) & 0xFFFFFFFF
        s = _ror32(s, 32 - shift)
    return s.to_bytes(4, 'big')

# ── 3. Bosch ME7.x / KWP2000 (Golf Mk4, Audi A3 1.8T, Passat, Polo) ──────────
def calc_sa2_bosch_me7(seed: bytes) -> bytes:
    """
    Algoritmo clássico Bosch ME7.x (Linha K / CAN KWP2000).
    XOR com máscara 0x3F47 + deslocamento 0x1B6A.
    """
    if len(seed) < 2:
        raise SecurityAccessError(f"Seed deve ter pelo menos 2 bytes, recebido: {len(seed)}")
    s = int.from_bytes(seed[:2], 'big')
    s = ((s ^ 0x3F47) + 0x1B6A) & 0xFFFF
    return s.to_bytes(2, 'big')

# ── 4. Padrão Genérico GM / Opel / Delphi (XOR Mask) ──────────────────────────
def calc_sa2_delphi_gm(seed: bytes) -> bytes:
    """Algoritmo padrão Delphi/GM Delco E80/E84."""
    if len(seed) < 2:
        raise SecurityAccessError(f"Seed deve ter pelo menos 2 bytes")
    s = int.from_bytes(seed[:2], 'big')
    k = (s ^ 0x4854) + 0x1234
    return (k & 0xFFFF).to_bytes(2, 'big')

# ── 5. PSA Peugeot / Citroën (Valeo VD56 / Bosch EDC17C60) ───────────────────
def calc_sa2_psa_standard(seed: bytes) -> bytes:
    """Desbloqueio padrão UDS nível 1 e 3 PSA."""
    if len(seed) < 4:
        raise SecurityAccessError("Seed PSA requer 4 bytes")
    s = int.from_bytes(seed[:4], 'big')
    k = ((s >> 3) | (s << 29)) ^ 0x5A5AA5A5
    return (k & 0xFFFFFFFF).to_bytes(4, 'big')


ALGORITHMS: Dict[str, Callable[[bytes], bytes]] = {
    "BOSCH_ME17_VAG": calc_sa2_bosch_me17,
    "BOSCH_MED91": calc_sa2_bosch_med91,
    "BOSCH_ME7": calc_sa2_bosch_me7,
    "DELPHI_GM": calc_sa2_delphi_gm,
    "PSA_STANDARD": calc_sa2_psa_standard,
}

def calculate_security_key(algorithm_name: str, seed_hex: str) -> str:
    """
    Calcula a Chave de Segurança (Key) a partir da Seed (em hexadecimal).
    Retorna a Key em formato hexadecimal.
    """
    algo = ALGORITHMS.get(algorithm_name.upper())
    if not algo:
        available = ", ".join(ALGORITHMS.keys())
        raise ValueError(f"Algoritmo desconhecido: '{algorithm_name}'. Disponíveis: {available}")
    
    clean_hex = seed_hex.replace(" ", "").replace("0x", "")
    seed_bytes = bytes.fromhex(clean_hex)
    key_bytes = algo(seed_bytes)
    return key_bytes.hex().upper()
