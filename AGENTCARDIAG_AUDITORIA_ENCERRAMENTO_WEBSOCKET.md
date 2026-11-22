# AUDITORIA FINAL DE ENCERRAMENTO E REVISÃO FORENSE DE CÓDIGO WEBSOCKET — AGENTCARDIAG

**Data da Auditoria:** 17 de Novembro de 2026  
**Projeto Sob Análise:** `/home/leonardof/AgentCarDiag`  
**Modalidade:** Estritamente READ-ONLY (Sem modificação de código, credenciais, bases de dados ou backups)  
**Arquivos Inspecionados:**
- `server/app/routers/websockets.py`
- `server/app/websocket_manager.py`
- `server/app/database.py`

---

## 1. PARECER GERAL E CLASSIFICAÇÃO DE SEGURANÇA

> [!WARNING]
> **DECLARAÇÃO DE CONDIÇÃO DE SEGURANÇA:**
> **A segurança do subsistema WebSocket NÃO PODE ser declarada como "integral" neste estágio.**
> Embora todas as vulnerabilidades críticas imediatas tenham sido corrigidas e comprovadas por testes automatizados, existe uma **dependência operacional pendente**: a migração dos firmwares dos nós ESP32 para o provisionamento de credenciais individuais em banco de dados (`device_credentials`).
> Enquanto o sistema operar em **modo de transição retrocompatível (`legacy`)** via `WS_TOKEN` global compartilhado, os dispositivos ainda não provisionados permanecem vulneráveis a usurpação e colisão mútua de identidade entre si.

---

## 2. ANÁLISE PORMENORIZADA DOS 10 PONTOS AUDITADOS

---

### Ponto 1: Exploração do `virtual_car_node` através de proxy, configuração de produção ou origem não-local

#### Trecho de Código Auditado
Arquivo: [`server/app/routers/websockets.py`](file:///home/leonardof/AgentCarDiag/server/app/routers/websockets.py#L31-L47)
```python
is_virtual_simulator = (node_id == "virtual_car_node")
if is_virtual_simulator and token is None:
    # Permitir estritamente se for conexão comprovadamente local (loopback IPv4/IPv6 ou testclient)
    # Não confiar em cabeçalhos de proxy para validação de acesso físico/local
    client_host = getattr(websocket.client, "host", "") if websocket.client else ""
    if client_host not in ("127.0.0.1", "::1", "::ffff:127.0.0.1", "localhost", "testclient"):
        logger.warning(
            f"[HW] Bloqueada tentativa de conexão não-autenticada de virtual_car_node a partir de host remoto: {client_host!r}"
        )
        await websocket.close(code=1008)
        return
else:
    if not token or not secrets.compare_digest(token, WS_TOKEN):
        logger.warning(f"[HW] Acesso negado para node={node_id!r}. Token inválido ou ausente.")
        await websocket.close(code=1008)
        return
```

#### Análise Técnica e Evidências
1. **Inspeção Direta de Socket:** O código inspeciona `websocket.client.host`, obtido diretamente do objeto de transporte do socket TCP (`sockaddr`). Ele deliberadamente **não lê nem confia** em cabeçalhos como `X-Forwarded-For`, `X-Real-IP` ou `Forwarded`.
2. **Conexões Diretas:** Qualquer conexão TCP direta oriunda de outra máquina da LAN ou WAN (ex.: `192.168.x.x`, `10.x.x.x` ou IP público) preenche `websocket.client.host` com o IP remoto real e é **sumariamente rejeitada com código 1008**.
3. **Cenário de Proxy Reverso Local (Limitação Arquitetural Documentada):**
   - Se o AgentCarDiag for implantado em produção atrás de um proxy reverso (Nginx, Caddy, Traefik, Cloudflare Tunnel) rodando no **mesmo servidor host** e esse proxy escutar conexões externas e encaminhá-las via loopback (`127.0.0.1`) para o Uvicorn sem autenticação prévia, o socket Uvicorn registrará `client.host == "127.0.0.1"`.
   - Sob essa arquitetura de proxy não-segmentada, um atacante externo poderia enviar requisições a `/ws/node/virtual_car_node` e o Uvicorn as consideraria locais.
4. **Recomendação de Implantação:** O arquivo de configuração do proxy reverso de borda deve conter regra explícita bloqueando acesso externo aos endpoints `/ws/node/virtual_car_node` e `/ws/hardware` ou exigindo autenticação HTTP básica/mTLS na borda.

**Classificação:** `CORRIGIDO COM LIMITAÇÃO DOCUMENTADA DE INFRAESTRUTURA`

---

### Ponto 2: Avaliação da presença de `testclient` na allowlist local

#### Trecho de Código Auditado
Arquivo: [`server/app/routers/websockets.py`](file:///home/leonardof/AgentCarDiag/server/app/routers/websockets.py#L36)
```python
if client_host not in ("127.0.0.1", "::1", "::ffff:127.0.0.1", "localhost", "testclient"):
```

#### Análise Técnica e Evidências
1. **Origem do valor `testclient`:** A biblioteca Starlette (`starlette.testclient.TestClient`) implementa transporte em memória para testes ASGI e atribui `websocket.client = Address(host="testclient", port=50000)`.
2. **Impossibilidade de Spoofing via Rede:** No subsistema de rede do kernel Linux (IPv4/IPv6 TCP stack), o endereço remoto retornado por `getpeername()` no socket descritor é obrigatoriamente um binário `struct sockaddr_in` ou `sockaddr_in6`. O Python decodifica isso via `inet_ntop`, resultando estritamente em strings de formatação de IP numérico (ex.: `"192.168.1.1"`, `"127.0.0.1"`). Nenhum pacote TCP de rede consegue fazer o kernel Linux injetar a string literal `"testclient"`.
3. **Risco Residual:** Zero exploração remota via rede. Contudo, do ponto de vista de boas práticas de engenharia de segurança, trata-se de um artefato de teste residual em código produtivo que deveria idealmente ser injetado por injeção de dependência condicional a ambiente de teste.

**Classificação:** `COMPROVADAMENTE SEGURO CONTRA REDE EXTERNA`

---

### Ponto 3: Amarração Serial <-> Token Individual e Proteção Contra Takeover por Outro Token Individual

#### Trechos de Código Auditados
Arquivo: [`server/app/database.py`](file:///home/leonardof/AgentCarDiag/server/app/database.py#L687-L703)
```python
cred = await get_device_credential(clean_serial)
if cred:
    if cred.get("is_revoked", 0) == 1:
        logger.warning(f"[Auth] Acesso negado para serial={clean_serial}: credencial revogada.")
        return False, "revoked"
    
    presented_hash = hash_device_token(presented_token)
    if secrets.compare_digest(presented_hash, cred.get("token_hash", "")):
        now = _now()
        async with get_db() as db:
            await db.execute("UPDATE device_credentials SET last_auth_at = ? WHERE serial = ?", (now, clean_serial))
            await db.commit()
        return True, "individual"
    else:
        logger.warning(f"[Auth] Acesso negado para serial={clean_serial}: token individual incorreto.")
        return False, "individual_token_mismatch"
```

Arquivo: [`server/app/websocket_manager.py`](file:///home/leonardof/AgentCarDiag/server/app/websocket_manager.py#L231-L253)
```python
if clean_serial in self.devices:
    old_dev = self.devices[clean_serial]
    old_ws = old_dev.get("ws")
    old_auth = old_dev.get("auth_mode", "legacy")

    if old_ws and old_ws != websocket:
        if old_auth == "individual" and auth_mode == "legacy":
            logger.warning(
                f"[Gateway] Bloqueado takeover de serial={clean_serial}: dispositivo protegido por credencial "
                "individual não pode ser desconectado por token global legado."
            )
            return False

        logger.info(f"[Gateway] Encerrando sessão anterior para serial={clean_serial} (auth_mode={auth_mode})")
        old_dev["ws"] = None
        try:
            await old_ws.close(code=1000)
        except Exception:
            pass
```

#### Análise Técnica e Evidências
1. **Amarração Estrita de Serial:** `get_device_credential(clean_serial)` faz busca na tabela `device_credentials` estritamente por chave primária `serial = ?`.
2. **Tentativa de Usurpação com Token Individual de Outro Nó:**
   - Se um atacante possui o token individual legítimo do dispositivo B (`token_B`) e tenta se conectar declarando `serial=A`, a consulta recupera `token_hash_A`.
   - O cálculo `secrets.compare_digest(hash(token_B), token_hash_A)` falha (`False`).
   - `verify_device_authentication` retorna `(False, "individual_token_mismatch")`.
   - Em `websockets.py` (linha 191), o WebSocket é imediatamente fechado com código `1008` antes de alcançar o `gateway_manager`.
3. **Reconexão do Próprio Titular:**
   - Quando o titular autêntico com `token_A` se reconecta, ele passa na verificação (`auth_mode="individual"`).
   - Em `connect_esp32`, a sessão anterior pendente (socket zumbi ou desconexão não finalizada) é fechada limpa com código `1000`, e o novo socket assume a operação sem interrupções.

**Classificação:** `CORRIGIDO E COMPROVADO`

---

### Ponto 4: Usurpação entre Dispositivos Não-Provisionados Individualmente (Token Legado)

#### Trechos de Código Auditados
Arquivo: [`server/app/database.py`](file:///home/leonardof/AgentCarDiag/server/app/database.py#L704-L706)
```python
# 2. Modo de transição com token global legado (para dispositivos ainda sem credencial individual)
if secrets.compare_digest(presented_token, WS_TOKEN):
    return True, "legacy"
```

Arquivo: [`server/app/websocket_manager.py`](file:///home/leonardof/AgentCarDiag/server/app/websocket_manager.py#L238-L253)
```python
if old_auth == "individual" and auth_mode == "legacy":
    logger.warning(
        f"[Gateway] Bloqueado takeover de serial={clean_serial}: dispositivo protegido por credencial "
        "individual não pode ser desconectado por token global legado."
    )
    return False

logger.info(f"[Gateway] Encerrando sessão anterior para serial={clean_serial} (auth_mode={auth_mode})")
old_dev["ws"] = None
try:
    await old_ws.close(code=1000)
except Exception:
    pass
```

#### Análise Técnica e Evidências
1. **Vulnerabilidade Estrutural do Modo Legado:**
   - Se o dispositivo 1 conecta informando `serial=s2001` e o token legado global `WS_TOKEN`, ele obtém `auth_mode = "legacy"`.
   - Se o dispositivo 2 (ou um invasor que conheça o `WS_TOKEN`) conectar declarando o mesmo `serial=s2001` e o `WS_TOKEN`, ele também obtém `auth_mode = "legacy"`.
   - Na verificação de takeover: `old_auth == "legacy"` e `auth_mode == "legacy"`. A condição protetora (`old_auth == "individual" and auth_mode == "legacy"`) é **FALSA**.
   - O gateway encerra a conexão do dispositivo 1 com código `1000` e entrega a identidade `s2001` ao dispositivo 2!
2. **Conclusão:** Entre nós não-provisionados que utilizam a chave estática compartilhada, **o risco de usurpação e substituição de conexão (takeover) permanece ativo**.

**Classificação:** `LIMITAÇÃO DOCUMENTADA CRÍTICA — MIGRAÇÃO PENDENTE`

---

### Ponto 5: Revogação de Credenciais Individuais e Efeito em Conexões Ativas

#### Trecho de Código Auditado
Arquivo: [`server/app/database.py`](file:///home/leonardof/AgentCarDiag/server/app/database.py#L650-L662)
```python
async def revoke_device_credential(serial: str) -> bool:
    """Revoga imediatamente a credencial de um dispositivo."""
    clean_serial = serial.strip().lower()
    async with get_db() as db:
        cur = await db.execute(
            "UPDATE device_credentials SET is_revoked = 1 WHERE serial = ?",
            (clean_serial,)
        )
        await db.commit()
        revoked = cur.rowcount > 0
    if revoked:
        logger.warning(f"[Auth] Credencial individual REVOGADA para serial={clean_serial}")
    return revoked
```

Arquivo: [`server/app/routers/websockets.py`](file:///home/leonardof/AgentCarDiag/server/app/routers/websockets.py#L188-L204)
```python
is_auth, auth_mode = await db.verify_device_authentication(resolved_serial, token)
if not is_auth:
    logger.warning(f"[Gateway] Acesso negado para serial={resolved_serial}. Razão: {auth_mode}")
    await websocket.close(code=1008)
    return

connected = await gateway_manager.connect_esp32(...)
...
try:
    while True:
        raw = await websocket.receive_text()
        ...
```

#### Análise Técnica e Evidências
1. **Revogação na Base de Dados:** A função `revoke_device_credential` altera o campo `is_revoked = 1` com sucesso.
2. **Bloqueio de Novas Conexões:** Qualquer tentativa subsequente de reconexão do serial revogado é bloqueada em `verify_device_authentication` (retorna `(False, "revoked")`) e o socket é fechado com código `1008`.
3. **Comportamento em Conexões Ativas (Lacuna Forense):**
   - A validação de autenticação ocorre **exclusivamente no momento do handshake de abertura do WebSocket**.
   - Dentro do loop `while True: raw = await websocket.receive_text()`, não há revalidação periódica nem gancho (hook) entre o banco de dados e o `gateway_manager`.
   - A função `revoke_device_credential` **NÃO aciona o gateway para localizar e fechar o socket ativo** (`gateway_manager.devices[serial]["ws"].close()`).
   - Um dispositivo revogado que já esteja online continuará transmitindo telemetria e recebendo comandos até que ocorra uma desconexão de rede, timeout de ping (6 segundos) ou reinício do processo do servidor.

**Classificação:** `CORRIGIDO PARCIALMENTE — FALTA DESCONEXÃO ATIVA IMEDIATA`

---

### Ponto 6: Exposição de Tokens em URLs, Logs e Mensagens de Erro

#### Trecho de Código Auditado
Arquivo: [`server/app/routers/websockets.py`](file:///home/leonardof/AgentCarDiag/server/app/routers/websockets.py#L169-L175)
```python
@router.websocket("/ws/esp32")
async def esp32_endpoint(
    websocket: WebSocket,
    token: str = Query(None),
    type: str = Query("Desconhecido"),
    serial: str = Query(None),
    fw: str = Query(None)
):
```

#### Análise Técnica e Evidências
1. **Em Logs da Aplicação:**
   - Auditou-se todas as chamadas de log em `websockets.py`, `database.py` e `websocket_manager.py`.
   - Os logs registram apenas o `serial`, o `device_type` e a razão (`auth_mode`), e.g.:
     `logger.warning(f"[Gateway] Acesso negado para serial={resolved_serial}. Razão: {auth_mode}")`.
   - **Nenhum log da aplicação imprime o valor em claro de `token` ou `presented_token`.**
2. **No Banco de Dados:**
   - O armazenamento é realizado exclusivamente como hash criptográfico `hashlib.sha256(token.encode()).hexdigest()`. O token em texto plano nunca é persistido.
3. **Exposição no Transporte (Query Parameter):**
   - Os endpoints `/ws/esp32`, `/ws/hardware` e `/ws/node/{node_id}` recebem o token via parâmetro de consulta de URL (`?token=...`).
   - Embora seja comum em WebSockets devido à limitação de cabeçalhos de alguns clientes WebSocket nativos, a presença de credenciais na URL expõe os tokens a:
     - Logs de acesso padrão de proxies reversos e servidores web (`access.log` do Nginx, Cloudflare, etc.).
     - Histórico de navegadores e logs de firewall de aplicação.

**Classificação:** `LIMITAÇÃO DOCUMENTADA DE TRANSPORTE HTTP/WS`

---

### Ponto 7: Proteção Abrangente do Lock do Buffer CAN (Flushes, Retries e Reinserção)

#### Trecho de Código Auditado
Arquivo: [`server/app/database.py`](file:///home/leonardof/AgentCarDiag/server/app/database.py#L576-L618)
```python
async def _flush_can_batch() -> None:
    """Write accumulated CAN frames to the database with retry, flush synchronization and preservation."""
    global _can_batch, _can_dropped_frames_count, _can_buffer_overflow_alert

    # Serializa todos os flushes para impedir inversão concorrente de lotes
    async with _get_flush_lock():
        async with _get_can_lock():
            if not _can_batch:
                return
            batch = _can_batch
            _can_batch = []

        success = False
        for attempt in range(1, _MAX_FLUSH_RETRIES + 1):
            try:
                async with get_db() as db:
                    await db.executemany(
                        "INSERT INTO can_logs (session_id, timestamp, can_id, dlc, data_hex, source) VALUES (?,?,?,?,?,?)",
                        batch,
                    )
                    await db.commit()
                success = True
                break
            except Exception as e:
                logger.warning(f"Tentativa {attempt}/{_MAX_FLUSH_RETRIES} de gravação do lote CAN falhou: {e}")
                if attempt < _MAX_FLUSH_RETRIES:
                    await asyncio.sleep(0.05 * attempt)

        if not success:
            logger.critical(
                f"[DB] FALHA DEFINITIVA NA PERSISTÊNCIA CAN: {_MAX_FLUSH_RETRIES} tentativas falharam. "
                f"{len(batch)} frames retidos em memória sob risco de perda!"
            )
            _can_buffer_overflow_alert = True
            async with _get_can_lock():
                # Reinsere o lote preservando a ordem cronológica original
                _can_batch = batch + _can_batch
                if len(_can_batch) > _MAX_CAN_BUFFER:
                    dropped = len(_can_batch) - _MAX_CAN_BUFFER
                    _can_dropped_frames_count += dropped
                    _can_batch = _can_batch[-_MAX_CAN_BUFFER:]
```

#### Análise Técnica e Evidências
1. **Escopo do `_get_flush_lock()`:** O lock abrange todo o corpo da função (linhas 581 a 617).
2. **Comportamento Concorrente:**
   - Se uma rotina disparar `_flush_can_batch` enquanto outra está no meio da retentativa com `await asyncio.sleep(...)`, a segunda rotina é enfileirada no lock assíncrono.
   - Nenhuma operação de gravação subsequente consegue executar antes que o lote atual seja totalmente confirmado no SQLite ou restaurado em `_can_batch`.
3. **Preservação de Ordem:** A reinserção `_can_batch = batch + _can_batch` sob o lock `_can_batch_lock` assegura que os frames antigos fiquem na cabeça da fila, antes dos frames novos que chegaram durante o período de retry.

**Classificação:** `CORRIGIDO E COMPROVADO`

---

### Ponto 8: Descarte de Frames por Saturação do Buffer e Ausência de Persistência Secundária

#### Trecho de Código Auditado
Arquivo: [`server/app/database.py`](file:///home/leonardof/AgentCarDiag/server/app/database.py#L559-L569)
```python
async with _get_can_lock():
    if len(_can_batch) >= _MAX_CAN_BUFFER:
        _can_dropped_frames_count += 1
        _can_buffer_overflow_alert = True
        _can_batch.pop(0)
        logger.critical(
            f"[DB] CRITICAL BUFFER OVERFLOW: Buffer CAN atingiu {_MAX_CAN_BUFFER} elementos. "
            f"Frame mais antigo descartado sob backpressure. Total descartados: {_can_dropped_frames_count}. "
            "RISCO DE PERDA DE DADOS DE TELEMETRIA!"
        )
    _can_batch.append((session_id, ts, can_id, dlc, data_hex, source))
```

#### Análise Técnica e Evidências
1. **Saturação em Memória:** O buffer é estritamente uma lista em memória RAM (`_can_batch = []`) delimitada em `_MAX_CAN_BUFFER = 5000`.
2. **Comportamento sob Falha Prolongada:** Se o banco SQLite ficar travado ou indisponível por tempo suficiente para acumular mais de 5.000 frames (o que ocorre em poucos segundos em barramentos CAN de 500 kbps sob alta taxa de quadros), o sistema **descarta frames em memória**.
3. **Inexistência de Persistência Secundária Durável:**
   - O sistema não implementa arquivo de spooling em disco temporário (flat file ou journal WAL secundário).
   - Se o processo Uvicorn sofrer crash, falta de energia ou for finalizado enquanto existirem frames em `_can_batch`, todos os frames retidos são perdidos.

**Classificação:** `COMPORTAMENTO DE BACKPRESSURE CONTROLADO COM LIMITAÇÃO DOCUMENTADA`

---

### Ponto 9: Consistência do Contador de Perdas e Alertas

#### Trecho de Código Auditado
Arquivo: [`server/app/database.py`](file:///home/leonardof/AgentCarDiag/server/app/database.py#L537-L544)
```python
def get_can_buffer_status() -> dict:
    """Inspeciona estado em tempo real do buffer de persistência CAN."""
    return {
        "buffer_size": len(_can_batch),
        "max_buffer_bound": _MAX_CAN_BUFFER,
        "dropped_frames": _can_dropped_frames_count,
        "overflow_alert": _can_buffer_overflow_alert,
    }
```

#### Análise Técnica e Evidências
1. **Rastreamento de Descarte Unitário e em Bloco:**
   - Em `persist_can_frame`: incrementa `_can_dropped_frames_count += 1` em cada descarte de saturação.
   - Em `_flush_can_batch`: incrementa `_can_dropped_frames_count += dropped` no descarte pós-falha de flush.
2. **Sinalização de Alerta:** `_can_buffer_overflow_alert` é comutado para `True` no primeiro descarte e quando o flush atinge o limite de 3 falhas.
3. **Observabilidade:** O status pode ser consultado via `get_can_buffer_status()` e gera mensagens com nível de severidade `CRITICAL`.
4. **Ressalva:** A flag `_can_buffer_overflow_alert` permanece como "latch" (não reseta automaticamente para `False` após restabelecimento do buffer normal), funcionando como um indicador de que houve anomalia durante o ciclo de vida do processo.

**Classificação:** `CORRIGIDO E CONSISTENTE`

---

### Ponto 10: Preservação de Ordem e Prevenção de Duplicações na Recuperação

#### Trecho de Código Auditado
Arquivo: [`server/app/database.py`](file:///home/leonardof/AgentCarDiag/server/app/database.py#L591-L616)
```python
async with get_db() as db:
    await db.executemany(
        "INSERT INTO can_logs (session_id, timestamp, can_id, dlc, data_hex, source) VALUES (?,?,?,?,?,?)",
        batch,
    )
    await db.commit()
success = True
break
...
if not success:
    ...
    async with _get_can_lock():
        _can_batch = batch + _can_batch
```

#### Análise Técnica e Evidências
1. **Atomicidade da Transação SQLite:** O bloco `async with get_db() as db:` garante que `executemany` só consolida os registros se o `db.commit()` for alcançado sem exceção. Se ocorrer erro no meio da gravação, o SQLite executa rollback automático e nenhum frame parcial é persistido.
2. **Prevenção de Duplicatas:** Como o lote `batch` foi extraído da fila antes da tentativa (`batch = _can_batch; _can_batch = []`), se o commit tiver sucesso, o lote não é mais reinserido. Se o commit falhar, os frames voltam para o buffer integralmente sem ter sido gravados no banco.
3. **Integridade Cronológica:** A reinserção `batch + _can_batch` preserva a ordem temporal exata (FIFO).

**Classificação:** `CORRIGIDO E COMPROVADO`

---

## 3. RESUMO CONSOLIDADO DE CLASSIFICAÇÕES

| Item Auditado | Título do Requisito | Classificação Forense |
| :---: | :--- | :--- |
| **Ponto 1** | Proteção de `virtual_car_node` contra origens não-locais | **CORRIGIDO COM LIMITAÇÃO DOCUMENTADA DE INFRAESTRUTURA** |
| **Ponto 2** | Restrição de `testclient` a ambientes de teste | **COMPROVADAMENTE SEGURO CONTRA REDE EXTERNA** |
| **Ponto 3** | Amarração Serial <-> Token e bloqueio de takeover individual | **CORRIGIDO E COMPROVADO** |
| **Ponto 4** | Risco de usurpação entre nós legados não-provisionados | **LIMITAÇÃO DOCUMENTADA CRÍTICA — MIGRAÇÃO PENDENTE** |
| **Ponto 5** | Revogação de credenciais e corte imediato de conexões ativas | **CORRIGIDO PARCIALMENTE — FALTA DESCONEXÃO ATIVA IMEDIATA** |
| **Ponto 6** | Redação de tokens em logs vs exposição em Query Params | **LIMITAÇÃO DOCUMENTADA DE TRANSPORTE HTTP/WS** |
| **Ponto 7** | Cobertura do Lock no ciclo completo de flush e retries | **CORRIGIDO E COMPROVADO** |
| **Ponto 8** | Descarte sob saturação do buffer e persistência durável | **COMPORTAMENTO DE BACKPRESSURE CONTROLADO COM LIMITAÇÃO DOCUMENTADA** |
| **Ponto 9** | Consistência dos contadores de perda e alertas de overflow | **CORRIGIDO E CONSISTENTE** |
| **Ponto 10** | Recuperação após falha sem duplicação e em ordem sequencial | **CORRIGIDO E COMPROVADO** |

---

## 4. LIMITAÇÕES RESTANTES E ROTEIRO DE RECOMENDAÇÕES FUTURAS

Para que o AgentCarDiag possa alcançar a certificação de **Segurança Integral**, as seguintes ações devem ser executadas nas próximas fases de evolução:

1. **Migração Obrigatória dos Dispositivos Físicos:**
   - Registrar as credenciais individuais de todos os hardwares de produção na tabela `device_credentials` com hashes SHA-256 exclusivos.
   - Atualizar os firmwares dos ESP32 (Scanner, Osciloscópio, ÁguiaCar) para enviar suas credenciais individuais dedicadas.
   - Desativar permanentemente o modo de transição (`WS_TOKEN` legado) no servidor assim que todos os dispositivos estiverem provisionados.

2. **Desconexão Proativa na Revogação:**
   - Implementar no `revoke_device_credential(serial)` uma chamada síncrona/assíncrona para o `HardwareGatewayManager` localizar o socket ativo do serial revogado e forçar seu encerramento imediato via `await ws.close(code=1008)`.

3. **Migração de Transporte de Autenticação:**
   - Substituir a passagem do token via Query Parameter (`?token=...`) por envio de cabeçalho `Authorization: Bearer <TOKEN>` no handshake ou por uma primeira mensagem de autenticação dedicada pós-handshake antes da liberação do tráfego telemático.

4. **Regras de Borda de Proxy Reverso:**
   - Em caso de deploy com Nginx ou Caddy, vedar explicitamente requisições externas para `/ws/node/virtual_car_node`.
