## 40. Integração e Engenharia Reversa do Ecossistema Launch X-PRO5

### 40.1 Descobertas no Tablet Samsung SM-X200 (Launch X-PRO5 / SmartBox VCI)
- **APK Principal (`com.cnlaunch.x431.xpro5`):** Protegido por 360 Jiagu packer (`assets/libjiagu.so`), focado na interface gráfica e despacho de rotinas.
- **Serviço de Segurança Crítica (`DiagBaseService.apk`):** Código descompilado via JADX expondo o motor `sth2024.impl.AuSCrypto` e `com.cnlaunch.bmwService.BmwService`:
  - **PKI Assimétrica Oficial:** Licenças oficiais BMW E-SYS (`assets/security/sec_security.lic`) e pares de chaves de transporte/sessão (`sec_keyreference.xml`, `sec_ncdkeys.xml`, `sec_auth_l3.xml`).
  - **UDS 0x27 Seed/Key Dinâmico:** Desafio de segurança calculado via `validate2701`, `validate2713` e `signChallengeECU`, resolvendo bootloaders SGBM ID.
  - **Camada Física e VCI (`libSTD.so` / `libCOMM_ABSTRACT_LAYER.so`):** Símbolos `OpenCommunicationPort`, `SendData`, `ReadSmartBoxInfo`, gerenciando a VCI SmartBox com serial `988430843570`.
  - **Bancos Binários Modulares (`YZJM`):** 193 montadoras instaladas organizadas por arquivos `BIN.ZIP`, `FUNCDATA_*.BIN` e `SYSLIST_*.BIN` carregados dinamicamente via `lib.cfg`.

### 40.2 Aba "X-PRO5 Test" no AgentCarDiag
Implementada nova aba na aplicação Web (`#panel-xpro` e endpoint `/api/xpro`) replicando a experiência de uso do aplicativo comercial:
1. **Grid Visual de Montadoras:** Cards com os ícones oficiais das marcas extraídos diretamente do tablet (`ICON_TOYOTA.PNG`, `ICON_VW.PNG`, `ICON_BENZ.PNG`, `ICON_BMW.PNG`, etc.), versões de software e regiões.
2. **Varredura Rápida (Quick Test):** Varredura sequencial de módulos (Engine, Transmissão, ABS, SRS, etc.) com barra de progresso e detecção de DTCs.
3. **Fluxo de Dados ao Vivo (DataStream):** Visualização em tempo real de sensores com barra gráfica percentual fluida.
4. **Calculador de Desafios UDS 0x27 AuSCrypto:** Endpoint interativo (`POST /api/xpro/security/solve-challenge`) calculando respostas de chaves para bootloaders BMW E-SYS / UDS.

---

## 41. ÁguiaCar: Mitigação de Brownout 4G e Interface de Apresentação

### 41.1 Análise e Solução do Brownout / Queda de Tensão no Boot do ÁguiaCar (T-SIM7670G-S3)
- **Causa Raiz Identificada:** O modem celular SIM7670G exige pulsos de corrente de até **1.5A a 2.0A** durante o registro inicial da rede 4G LTE. No boot simultâneo com os periféricos do ESP32-S3 e transceptor CAN, ocorria afundamento da tensão de barramento (*voltage sag* abaixo de 2.7V), disparando o detector de brownout e corrompendo a sequência de boot.
- **Implementação no Firmware (`firmware/AguiaCar_FleetTracker/AguiaCar_FleetTracker.ino`):**
  1. **Inicialização Escalonada:** Periféricos locais (TWAI CAN, conversores ADC) inicializam primeiro. O sistema agora aguarda **3 segundos** para estabilização completa das linhas de alimentação antes de acordar o circuito de RF celular.
  2. **Controle Ativo do Regulador DC-DC (`MODEM_PS_PIN` - GPIO 42):** Forçado em nível lógico `HIGH`, garantindo a operação do conversor buck/boost no modo de máxima capacidade e baixíssimo *ripple*, amortecendo picos instantâneos de transmissão.
  3. **Sequência Precisa de PWRKEY (GPIO 46):** Pulso de 1.2s com repouso em nível baixo e janela de 2.5s para estabilização térmica e de clock da baseband antes do envio dos comandos AT.

### 41.2 Acesso Desbloqueado para Apresentação & Indicadores LED de Hardware
- **Desbloqueio de Navegação:** Removidas as restrições e redirecionamentos forçados em `switchTab()`, permitindo navegação livre por todas as abas (`Sniffer CAN`, `Osciloscópio`, `Scanner OBD-II`, `ÁguiaCar`, `ECU Flasher`, `X-PRO5`) mesmo com bancada ou veículos offline.
- **LEDs de Status Dinâmicos:** Cada aba agora conta com um indicador luminoso discreto (`.tab-hw-dot`):
  - **Negro / Apagado (`#1e293b`):** Hardware offline (modo apresentação/demonstração).
  - **Verde Luminoso (`#10b981`):** Hardware físico online e alimentando o canal correspondente.
- **Simulador do Osciloscópio Ativo:** Corrigida a inicialização de `sampleRate` e redimensionamento automático de canvas, permitindo a demonstração das formas de onda automotivas (CKP 60-2 + CMP Hall, compressão relativa, ripple de alternador) sem necessidade de placa conectada.
- **Gravação em Hardware Real:** Firmware compilado e gravado com sucesso no dispositivo LilyGO ESP32-S3 via `/dev/ttyACM0` (Hash verificado 100%, 340 KB gravados).

---

## 42. Sistema Proprietário Multi-Box Honeypot Defense & Deploy em Produção (Dell OptiPlex)

### 42.1 Arquitetura de Camuflagem Anônima e Honeypots
- **Interface Visual Minimalista & Anônima (`/login`):**
  - Desenvolvida em `server/app/static/login.html` com estética dark mode stealth (`#08090c`).
  - 5 caixas de entrada de texto empilhadas (`b1`, `b2`, `b3`, `b4`, `b5`) e um único botão "ENTER".
  - Ausência total de rótulos (`<label>`), dicas ou placeholders contextuais como "Usuário" ou "Senha".
  - Proteção anti-autofill (`autocomplete="off"`, `autocorrect="off"`, `data-lpignore="true"`).
  - Compatibilidade mobile: `font-size: 16px` em todos os inputs para evitar auto-zoom no Safari iOS, com `touch-action: manipulation` e áreas confortáveis de clique.

### 42.2 Motor de Segurança — Matriz Dinâmica do Agente Porteiro (`server/app/security/honeypot_auth.py`)
- **Triagem por Quantidade Estrita:** Exige exatamente 3 caixas preenchidas com pelo menos 1 caractere. Se vier 0, 1, 2, 4 ou 5 caixas -> Ban imediato do IP (HTTP 403 Forbidden).
- **Assinatura Topológica de Linhas:** O sistema inspeciona quais 3 linhas foram preenchidas e verifica se existe alguma coluna/usuário em `usuarios.json` que utiliza essa exata combinação (ex: linhas 1, 3 e 4 ou linhas 2, 4 e 5). Se ninguém usa essa combinação -> Ban imediato (HTTP 403 Forbidden).
- **Tolerância Humana de Digitação (3 Tentativas):** Se as 3 linhas coincidirem com a assinatura de um usuário cadastrado, mas houver erro na digitação do texto, o sistema trata como falha humana permitindo até 3 tentativas (HTTP 401). Na 3ª tentativa consecutiva, aplica ban temporário de 15 minutos (900s).
- **Compatibilidade UTF-8:** Comparação segura contra timing attacks via `secrets.compare_digest(act.encode('utf-8'), exp.encode('utf-8'))`, suportando caracteres especiais como `Ñ`, acentos e símbolos.

### 42.3 Sincronização e Deploy no Servidor Dell OptiPlex 3020 Micro (`192.168.0.50`)
- **Deploy via rsync:** Sincronizado para `anjos@192.168.0.50:/home/anjos/AgentCarDiag/server/`.
- **Docker Compose:** Container `cardiag-server` reiniciado com bind mount ativo de `./app` e `./data`.
- **Túnel Cloudflare (`cardiag-tunnel`):** Publicação validada em `https://diag.anality.me`.
  - Acessos anônimos em `https://diag.anality.me/` sofrem redirecionamento HTTP 307 para `/login`.
  - Acessos autenticados via cookie `cardiag_stealth_session` entram direto no dashboard sem pop-up de Basic Auth do navegador.

---

## 43. Compartilhamento Seguro de Rede Local (Samba SMB & SFTP) — Dell OptiPlex

### 43.1 Configuração do Samba Server (`/etc/samba/smb.conf`)
- **Restrição de Rede:** `hosts allow = 192.168.0.0/24 127.0.0.1` e `hosts deny = 0.0.0.0/0` (blindado contra qualquer tentativa fora da rede local).
- **Compartilhamentos Ativos:**
  - `[root]`: Mapeia a unidade raiz (`/`) com `force user = root` para permitir gestão total de arquivos e permissões pelo Dolphin/KDE.
  - `[home-anjos]`: Mapeia `/home/anjos`.
- **Credenciais SMB:** Usuário `anjos` / Senha `<ADMIN_PASSWORD>`.
- **Acesso no Dolphin (KDE):**
  - Via Samba: `smb://192.168.0.50/` ou `smb://192.168.0.50/root`
  - Via SFTP Seguro (SSH): `sftp://anjos@192.168.0.50/`

---

## 44. ÁguiaCar: Hotspot Wi-Fi Roteador 4G Integrado (`v7`)

### 44.1 Configuração e Operação do Roteador Wi-Fi
- **SSID Transmitido:** `v7`
- **Senha WPA2:`<REDACTED_CREDENTIAL>` `10203050`
- **Endereço Gateway:** `192.168.4.1` (Máscara `255.255.255.0`)
- **Canal Wi-Fi:** Canal 1 (802.11 b/g/n, 2.4 GHz)
- **Roteamento de Dados:** Pilha LwIP NAPT (`WiFi.AP.enableNAPT(true)`) ativa nativamente no ESP32-S3.
- **Hardware Validado:** LilyGO T-SIM7670G-S3 (ESP32-S3 com 2MB PSRAM QSPI, 16MB Flash, modem SIM7670G LTE Cat-1 e TWAI CAN).
- **Flashing e Verificação em Campo:** Gravado diretamente via `/dev/ttyACM0` a 921600 baud. Rede `v7` detectada e validada em tempo real com intensidade de sinal 100% (-40 dBm).

### 44.2 Enlace de Dados Celular PPP (Vodafone Espanha)
- **Driver WAN:** LwIP Point-to-Point Protocol (`PPP.h` com `PPP_MODEM_GENERIC` / `PPP_MODEM_SIM7600`).
- **APN Operadora:** `airtelnet.es` (Vodafone Espanha 4G LTE).
- **Modo de Dados:** `ESP_MODEM_MODE_DATA`. Ao receber o evento `ARDUINO_EVENT_PPP_GOT_IP`, a interface celular WAN é atrelada ao gateway SoftAP `192.168.4.1`, permitindo que todos os pacotes IP gerados pelos clientes do Wi-Fi `v7` sejam roteados e traduzidos via NAPT para a internet móvel.


