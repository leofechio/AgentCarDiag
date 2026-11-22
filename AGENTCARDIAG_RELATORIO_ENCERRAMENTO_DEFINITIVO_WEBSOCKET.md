# RELATÓRIO DE ENCERRAMENTO DEFINITIVO DA SEGURANÇA E INTEGRIDADE WEBSOCKET — AGENTCARDIAG

**Data:** 17 de Novembro de 2026  
**Projeto Exclusivo:** `/home/leonardof/AgentCarDiag`  
**Documentos de Referência:**
- `AGENTCARDIAG_AUDITORIA_ENCERRAMENTO_WEBSOCKET.md`
- `AGENTCARDIAG_RELATORIO_FINAL_SEGURANCA_WEBSOCKET.md`

---

## 1. REGISTO DO BACKUP INTEGRAL PRÉ-MISSÃO

Em conformidade com a Regra 1 da missão, antes de qualquer modificação nos ficheiros do projeto foi criado um backup integral do estado do repositório, preservando todos os backups anteriores em `/home/leonardof/Taller/backups/`:

- **Ficheiro de Backup:** `/home/leonardof/Taller/backups/agentcardiag_backup_final_closure_20261117_143528.tar.gz`
- **Tamanho:** 231 MB
- **Hash SHA-256:**
  ```text
  af37b71a708b261ee47aaaa9bce38addcf488f7d6c6f0057b7f51d50dcf296e8
  ```
- **Ficheiro de Verificação:** `/home/leonardof/Taller/backups/agentcardiag_backup_final_closure_20261117_143528.tar.gz.sha256`
- **Backups Anteriores Preservados:**
  - `agentcardiag_backup_pre_audit_20261115_214725.tar.gz`
  - `agentcardiag_backup_definitive_ws_20261116_221700.tar.gz`
  - `agentcardiag_backup_security_fix_20261117_000042.tar.gz`
- **Projetos Externos:** `/home/leonardof/Taller/jarvis` (working tree 100% limpa e intocada) e `/home/leonardof/Taller/project_control_center` (intocado por esta missão).

---

## 2. VULNERABILIDADES ORIGINAIS E CORREÇÕES APLICADAS

### 2.1. Vulnerabilidade do Modo Legado e Migração Controlada de Credenciais Individuais (Item 2)
- **Problema Original:** O uso do token global `WS_TOKEN` permitia que dispositivos ainda não provisionados individualmente colidissem ou usurpassem seriais entre si, e não havia um mecanismo formal de transição controlada para desativar o `WS_TOKEN` global somente após a confirmação dos dispositivos.
- **Correção Aplicada:**
  1. Adicionada a coluna `migration_status` (`PENDING_CONFIRMATION` / `CONFIRMED`) na tabela `device_credentials` e criada a tabela `security_settings` (`legacy_ws_token_enabled`, `allow_url_token_fallback`) em [`server/app/database.py`](file:///home/leonardof/AgentCarDiag/server/app/database.py#L220-L238).
  2. Implementada `provision_device_credential(serial, device_type, token, require_confirmation)` ([`server/app/database.py:1022-1048`](file:///home/leonardof/AgentCarDiag/server/app/database.py#L1022-L1048)): gera credencial exclusiva vinculada ao serial em estado `PENDING_CONFIRMATION`. Assim que o dispositivo se autentica utilizando a sua credencial individual, o estado é promovido automaticamente para `CONFIRMED` ([`server/app/database.py:1196-1205`](file:///home/leonardof/AgentCarDiag/server/app/database.py#L1196-L1205)).
  3. Implementada `set_legacy_auth_enabled(enabled, force)` ([`server/app/database.py:1107-1140`](file:///home/leonardof/AgentCarDiag/server/app/database.py#L1107-L1140)): impede a desativação prematura do modo legado enquanto existirem dispositivos pendentes de confirmação (`pending_migrations`), e permite desativar definitivamente o `WS_TOKEN` global assim que os dispositivos estiverem `CONFIRMED`.
  4. Bloqueio de abuso cruzado de credenciais (`cross_device_credential_abuse` em [`server/app/database.py:1218-1230`](file:///home/leonardof/AgentCarDiag/server/app/database.py#L1218-L1230)): um dispositivo não pode usar a credencial individual de outro ESP32, nem mesmo para tentar assumir um serial ainda não provisionado.
  5. Proteção de IP de origem em sessões legadas ativas ([`server/app/websocket_manager.py:331-338`](file:///home/leonardof/AgentCarDiag/server/app/websocket_manager.py#L331-L338)): impede que um host diferente derrube uma sessão legada ativa saudável.
  6. Expostos endpoints administrativos REST em [`server/app/routers/devices.py:236-277`](file:///home/leonardof/AgentCarDiag/server/app/routers/devices.py#L236-L277):
     - `POST /api/workshops/devices/{serial_number}/provision`
     - `POST /api/workshops/devices/{serial_number}/revoke`
     - `GET /api/workshops/devices/credentials/status`
     - `POST /api/workshops/devices/credentials/legacy-mode`

### 2.2. Revogação Imediata de Credenciais em Sessões Ativas (Item 3)
- **Problema Original:** `revoke_device_credential()` atualizava o banco SQLite (`is_revoked = 1`), bloqueando futuras reconexões, mas não encerrava o socket WebSocket já ativo nem bloqueava mensagens subsequentes na sessão aberta.
- **Correção Aplicada:**
  1. Em [`server/app/database.py:1051-1080`](file:///home/leonardof/AgentCarDiag/server/app/database.py#L1051-L1080), `revoke_device_credential(serial)` atualiza imediatamente o conjunto `_revoked_serials`, grava `is_revoked = 1` no SQLite e dispara todos os callbacks registados (`_revocation_callbacks`).
  2. Em [`server/app/websocket_manager.py:225-251`](file:///home/leonardof/AgentCarDiag/server/app/websocket_manager.py#L225-L251) e [`server/app/websocket_manager.py:63-78`](file:///home/leonardof/AgentCarDiag/server/app/websocket_manager.py#L63-L78), foram implementados `HardwareGatewayManager.evict_revoked_device(serial)` e `ConnectionManager.evict_hardware_node(hw_id)`, que localizam o socket ativo daquele serial específico, encerram-no imediatamente com código `1008` e preservam todas as conexões dos demais dispositivos.
  3. Adicionado `revocation_watch_loop()` ([`server/app/websocket_manager.py:204-223`](file:///home/leonardof/AgentCarDiag/server/app/websocket_manager.py#L204-L223)) para sincronizar revogações executadas entre processos distintos via SQLite a cada `150ms`.
  4. Nos loops de receção de mensagens de `/ws/esp32`, `/ws/node/{node_id}` e `/ws/hardware` ([`server/app/routers/websockets.py:165-172`](file:///home/leonardof/AgentCarDiag/server/app/routers/websockets.py#L165-L172) e [`server/app/routers/websockets.py:397-407`](file:///home/leonardof/AgentCarDiag/server/app/routers/websockets.py#L397-L407)), cada mensagem recebida verifica `await db.is_serial_revoked_async(serial)` antes de qualquer processamento, rejeitando imediatamente dados de sessões revogadas.

### 2.3. Eliminação da Exposição de Tokens em URLs e Logs (Item 4)
- **Problema Original:** Os firmwares e clientes transmitiam `?token=...` na URL da requisição WebSocket, expondo segredos em potenciais logs de acesso HTTP/proxies.
- **Correção Aplicada:**
  1. **Autenticação por Mensagem Inicial de Handshake com Prazo Curto:** Em [`server/app/routers/websockets.py:114-156`](file:///home/leonardof/AgentCarDiag/server/app/routers/websockets.py#L114-L156) e [`server/app/routers/websockets.py:310-358`](file:///home/leonardof/AgentCarDiag/server/app/routers/websockets.py#L310-L358), quando a conexão WebSocket inicia sem token na URL, o servidor coloca o socket em quarentena pré-autenticação com prazo curto (`AUTH_HANDSHAKE_TIMEOUT = 2.5s`).
  2. **Bloqueio Estrito de Dados Pré-Autenticação:** Qualquer frame enviado antes da autenticação que não seja um handshake válido (`type` em `("auth", "handshake", "hw_info")` contendo `"token"`) resulta no encerramento imediato da conexão com código `1008`, sem persistir nem retransmitir nenhum dado.
  3. **Filtro Global de Redação de Logs (`SensitiveTokenLogFilter`):** Implementado em [`server/app/routers/websockets.py:34-77`](file:///home/leonardof/AgentCarDiag/server/app/routers/websockets.py#L34-L77) e acoplado aos loggers raiz, `uvicorn`, `uvicorn.access`, `uvicorn.error`, `cardiag.*` e `api`, substituindo automaticamente qualquer ocorrência de `?token=...`, `"token":"..."` ou `Bearer ...` por `[REDACTED]`.
  4. **Proteção Anti-Proxy em `virtual_car_node`:** Além da verificação direta de `websocket.client.host` em loopback, `_handle_hardware_ws` ([`server/app/routers/websockets.py:101-112`](file:///home/leonardof/AgentCarDiag/server/app/routers/websockets.py#L101-L112)) rejeita qualquer conexão não autenticada para `virtual_car_node` que contenha cabeçalhos de encaminhamento de proxy (`X-Forwarded-For`, `X-Real-IP`, `Forwarded`, `CF-Connecting-IP`).
  5. **Adaptação dos 4 Firmwares ESP32:** Todos os 4 firmwares foram atualizados para remover `?token=` de `WS_URL` e enviar a credencial no frame JSON inicial de handshake (`WStype_CONNECTED`) ou no cabeçalho HTTP `X-Device-Token`.

### 2.4. Persistência Secundária Durável em Disco para o Buffer CAN (Item 5)
- **Problema Original:** Quando o SQLite ficava indisponível e o buffer em memória RAM atingia 5.000 elementos, frames mais antigos eram descartados em memória e uma queda de energia ou reinício do processo perderia os lotes retidos.
- **Correção Aplicada ([`server/app/database.py:557-928`](file:///home/leonardof/AgentCarDiag/server/app/database.py#L557-L928)):**
  1. **Spool Durável em Disco (`can_spool.jsonl`):** Quando o SQLite falha após `_MAX_FLUSH_RETRIES` (3 tentativas) ou quando o buffer RAM atinge `_MAX_CAN_BUFFER` (5.000 frames), os lotes são gravados em disco com `os.fsync()` através de `_append_to_disk_spool()`.
  2. **Preservação Estrita da Ordem FIFO:** Em `_flush_can_batch()`, qualquer registro existente no arquivo de spool em disco é drenado e confirmado no SQLite **antes** dos lotes mais recentes da memória RAM.
  3. **Proteção Contra Duplicações (Idempotência):** Adicionada a coluna `frame_uid` com índice único `idx_can_logs_uid` na tabela `can_logs` e inserção via `INSERT OR IGNORE INTO can_logs ...`. Mesmo que o servidor reinicie após um commit e antes da limpeza do spool, a reexecução do spool nunca duplica frames.
  4. **Eliminação Condicionada à Confirmação:** `_write_spool_records_atomic([])` só remove o arquivo temporário de spool **após** a conclusão sem erros de `await db.commit()` no SQLite.
  5. **Recuperação Automática no Reinício:** `init_db()` invoca automaticamente `await recover_can_spool()`, restaurando todos os frames do spool em disco ao iniciar o servidor.
  6. **Controlo de Espaço em Disco e Limites de Utilização:** Verifica espaço livre na partição (`_MIN_DISK_FREE_BYTES = 20 MB` via `shutil.disk_usage`), tamanho máximo do spool (`_MAX_SPOOL_BYTES = 10 MB`) e limite de frames (`_MAX_SPOOL_FRAMES = 50.000`), emitindo alertas críticos (`spool_saturation_alert = True`) e contabilizando qualquer perda inevitável em `dropped_frames`.

---

## 3. FICHEIROS E LINHAS ALTERADOS

| Ficheiro | Linhas Alteradas | Resumo das Alterações |
| :--- | :---: | :--- |
| [`server/app/database.py`](file:///home/leonardof/AgentCarDiag/server/app/database.py) | `10-50`, `220-355`, `557-1240` | Coluna `frame_uid` e índice único em `can_logs`; tabela `security_settings`; coluna `migration_status` em `device_credentials`; motor completo de spool secundário durável em disco (`_append_to_disk_spool`, `recover_can_spool`, `_flush_can_batch`); migração controlada (`provision_device_credential`, `set_legacy_auth_enabled`) e revogação imediata sincronizada. |
| [`server/app/websocket_manager.py`](file:///home/leonardof/AgentCarDiag/server/app/websocket_manager.py) | `37-78`, `190-398`, `707-715` | `evict_revoked_device`, `evict_hardware_node`, `revocation_watch_loop`, proteção anti-takeover entre hosts e suporte a `already_accepted` no handshake inicial. |
| [`server/app/routers/websockets.py`](file:///home/leonardof/AgentCarDiag/server/app/routers/websockets.py) | `6-520` | `SensitiveTokenLogFilter`, autenticação por mensagem inicial de handshake com timeout curto (`2.5s`), bloqueio de dados pré-autenticação, guarda anti-proxy em `virtual_car_node` e verificação de revogação por mensagem. |
| [`server/app/routers/devices.py`](file:///home/leonardof/AgentCarDiag/server/app/routers/devices.py) | `225-280` | Endpoints REST para provisionamento individual, revogação imediata, status de migração e desativação controlada do modo legado. |
| [`firmware/AgentCar_Scanner/AgentCar_Scanner.ino`](file:///home/leonardof/AgentCarDiag/firmware/AgentCar_Scanner/AgentCar_Scanner.ino) | `39`, `608-624` | Remoção de `?token=` de `WS_URL`; envio de `token`, `serial` e `device_type` no handshake JSON inicial em `WStype_CONNECTED`. |
| [`firmware/AgentCar_Oscilloscope/AgentCar_Oscilloscope.ino`](file:///home/leonardof/AgentCarDiag/firmware/AgentCar_Oscilloscope/AgentCar_Oscilloscope.ino) | `33`, `68-82` | Remoção de `?token=` de `WS_URL`; envio de `token`, `serial` e `device_type` no handshake JSON inicial em `WStype_CONNECTED`. |
| [`firmware/AguiaCar_FleetTracker/AguiaCar_FleetTracker.ino`](file:///home/leonardof/AgentCarDiag/firmware/AguiaCar_FleetTracker/AguiaCar_FleetTracker.ino) | `641-648` | Envio de credencial via cabeçalhos HTTP `X-Device-Token` e `X-Device-Serial` sem exposição em URL. |
| [`firmware/esp32s3/esp32s3_can_sniffer/esp32s3_can_sniffer.ino`](file:///home/leonardof/AgentCarDiag/firmware/esp32s3/esp32s3_can_sniffer/esp32s3_can_sniffer.ino) | `233-262`, `340` | Extração segura do token em runtime, conexão em URL limpa `/ws/esp32?type=Scanner_CAN&serial=s2001` e envio de mensagem inicial `{"type":"auth",...}` em `WStype_CONNECTED`. |
| [`server/tests/test_ws_definitive_closure.py`](file:///home/leonardof/AgentCarDiag/server/tests/test_ws_definitive_closure.py) | `1-445` | Nova suite automatizada cobrindo individualmente os 15 cenários obrigatórios da missão. |

---

## 4. COMPILAÇÃO E VALIDAÇÃO DOS QUATRO FIRMWARES ESP32

Todos os quatro projetos de firmware foram inspecionados, adaptados para eliminar tokens nas URLs e compilados com `arduino-cli` para o alvo `esp32:esp32:esp32s3:CDCOnBoot=default,USBMode=hwcdc,PSRAM=opi`:

| Firmware | Ficheiro Principal | Flash Usada | Flash % | RAM Global | RAM % | Código de Saída |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: |
| **AgentCar_Scanner** | `AgentCar_Scanner.ino` | 1.243.551 B | 94% | 48.244 B | 14% | **0 (SUCESSO)** |
| **AgentCar_Oscilloscope** | `AgentCar_Oscilloscope.ino` | 1.236.291 B | 94% | 49.164 B | 15% | **0 (SUCESSO)** |
| **AguiaCar_FleetTracker** | `AguiaCar_FleetTracker.ino` | 1.027.407 B | 78% | 47.380 B | 14% | **0 (SUCESSO)** |
| **esp32s3_can_sniffer** | `esp32s3_can_sniffer.ino` | 1.277.415 B | 97% | 54.252 B | 16% | **0 (SUCESSO)** |

### Distinção Metodológica Estrita de Validação
1. **Testes Unitários:** Executados via `pytest` sobre funções de hash, verificação de credenciais, filtros de redação de logs, cálculo de CRC-15, telemetria CAN e motor de spool em disco (`100% PASS`).
2. **Testes de Integração:** Executados contra a aplicação FastAPI/SQLite real testando fluxos completos de banco de dados, migração de credenciais, sessões, revogação e recuperação de spool pós-reinício (`100% PASS`).
3. **Testes de Comunicação Simulada:** Clientes WebSocket e HTTP emulando os payloads exatos dos 4 firmwares (`hw_info`, `auth`, `can_frame`, `adc_burst`, `live_data`, `aguiacar_telemetry`) contra o servidor Uvicorn ativo na porta `8001` (`100% PASS`).
4. **Compilação de Firmware:** Geração real dos binários `.elf`, `.bin` e `.merged.bin` para o microcontrolador Xtensa ESP32-S3 via `arduino-cli` (`100% PASS`, Exit Code `0`).
5. **Testes em Hardware Físico:** **NÃO EXECUTADOS NESTA SESSÃO** (nenhum microcontrolador ESP32-S3 físico ou barramento CAN veicular está conectado às portas USB do servidor host).

---

## 5. TESTES EXECUTADOS E RESULTADOS REAIS

### 5.1. Os 15 Testes Obrigatórios de Encerramento (`server/tests/test_ws_definitive_closure.py`)

| # | Teste Automatizado | Requisito Verificado | Resultado |
| :-: | :--- | :--- | :---: |
| 1 | `test_01_individual_credentials_and_serial_binding` | Credenciais individuais, vínculo ao serial e migração controlada | **PASSED** |
| 2 | `test_02_takeover_blocked_against_other_esp32_credential` | Bloqueio de takeover com credencial de outro ESP32 | **PASSED** |
| 3 | `test_03_immediate_revocation_during_active_session_and_multiple_connections` | Revogação imediata com socket ativo, inativo e múltiplas conexões | **PASSED** |
| 4 | `test_04_reconnection_rejected_after_revocation` | Bloqueio de reconexão após revogação | **PASSED** |
| 5 | `test_05_mandatory_initial_authentication_before_data` | Autenticação inicial obrigatória antes de aceitar qualquer dado | **PASSED** |
| 6 | `test_06_no_tokens_in_urls_or_logs` | Ausência de tokens nas URLs dos firmwares e redação nos logs | **PASSED** |
| 7 | `test_07_authentication_timeout` | Fecho automático (1008) por timeout de autenticação inicial | **PASSED** |
| 8 | `test_08_reconnection_after_network_failure` | Reconexão limpa após falha de rede | **PASSED** |
| 9 | `test_09_can_buffer_with_sqlite_unavailable_over_5000_frames` | Spooling durável em disco para > 5.000 frames com SQLite indisponível (0 perdas) | **PASSED** |
| 10 | `test_10_spool_recovery_after_server_restart` | Recuperação integral do spool após reinício e limpeza pós-commit | **PASSED** |
| 11 | `test_11_fifo_order_preserved_after_recovery` | Preservação estrita da ordem cronológica FIFO após recuperação | **PASSED** |
| 12 | `test_12_deduplication_protection` | Proteção contra duplicações via `frame_uid` único | **PASSED** |
| 13 | `test_13_secondary_storage_saturation_and_loss_accounting` | Alerta crítico e contagem exata quando RAM e Spool atingem o limite | **PASSED** |
| 14 | `test_14_repeated_write_failures_resilience` | Resiliência e retentativas sob falhas repetidas de escrita | **PASSED** |
| 15 | `test_15_compatibility_with_all_four_firmwares` | Compatibilidade com os 4 firmwares existentes | **PASSED** |

### 5.2. Resumo Global de Todas as Suites Executadas

| Bateria de Testes | Comando Executado | Total | Passaram | Falharam | Código de Saída |
| :--- | :--- | :---: | :---: | :---: | :---: |
| **Pytest Suite Completa** | `PYTHONPATH=server .venv/bin/pytest server/tests/ -v` | 104 | **104** | 0 | `0` |
| **Batalhão Forense WS** | `PYTHONPATH=server .venv/bin/python scratch/test_final_security_ws.py` | 24 | **24** | 0 | `0` |
| **Verification Suite** | `CARDIAG_PORT=8001 .venv/bin/python server/test_verification_suite.py` | 22 | **22** | 0 | `0` |
| **AguiaCar Suite** | `CARDIAG_BASE_URL="http://127.0.0.1:8001" .venv/bin/python server/test_aguiacar_suite.py` | 9 | **9** | 0 | `0` |
| **Compilação Firmwares (4x)** | `/home/leonardof/bin/arduino-cli compile ...` | 4 | **4** | 0 | `0` |

---

## 6. LIMITAÇÕES EXTERNAS E OPERACIONAIS RESTANTES

Todas as vulnerabilidades de software identificadas na auditoria foram **corrigidas e comprovadas no código**. As únicas etapas que dependem de ação física externa ou de infraestrutura de produção são:

1. **Gravação Física (Flash) dos Microcontroladores ESP32-S3 em Bancada:**
   - Os binários atualizados dos 4 firmwares foram compilados com sucesso, mas necessitam ser gravados fisicamente via cabo USB/OTA nas placas ESP32-S3 reais quando estas estiverem conectadas em bancada, seguido do provisionamento individual de cada serial via `POST /api/workshops/devices/{serial}/provision` e posterior desativação definitiva do modo legado via `POST /api/workshops/devices/credentials/legacy-mode` (`{"enabled": false}`).
2. **Limites Físicos de Armazenamento do Host:**
   - O spool secundário durável em disco elimina a perda de frames quando o SQLite fica temporariamente indisponível ou o buffer RAM de 5.000 elementos enche. Caso o disco físico do servidor atinja o limite configurado (`10 MB` / `50.000 frames` ou `< 20 MB` livres na partição), o sistema não permite crescimento ilimitado, emite alerta `CRITICAL` e contabiliza explicitamente os descartes inevitáveis.

---

## 7. ESTADO FINAL DE SEGURANÇA

- **Arquitetura de Código e Persistência WebSocket:** **CONCLUÍDA, CORRIGIDA E COMPROVADA (100% dos testes aprovados, 0 regressões).**
- **Operação de Transição:** O mecanismo seguro de provisionamento individual, confirmação automática de migração, revogação imediata de conexões ativas, autenticação inicial por handshake sem exposição de tokens na URL e spool durável em disco estão **plenamente operacionais e validados**.
