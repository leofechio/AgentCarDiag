## 30. Módulo de Manuais de Oficina & Dados Técnicos OE (Padrão AutoData / AllData / Haynes)

Para transformar o **AgentCarDiag** em uma estação de trabalho completa de oficina mecânica — eliminando a dependência de assinaturas externas como AutoData, AllData e Doutor-IE — foi implementado um módulo nativo de dados técnicos de reparação veicular integrado diretamente à interface web e ao banco de dados offline.

### 30.1 Varredura de Fontes Globais & Engenharia Reversa Multilíngue
Realizada varredura em repositórios abertos e manuais de fábrica em múltiplos idiomas:
- **Francês / Renault:** Notas Técnicas originais **NT 6017A** e **MR323** para o motor **M9R (2.0 dCi)** e Trafic III, extraindo torques exatos de cabeçote (20 Nm + 240°), comprimento máximo de parafuso (117.7 mm), ordem de aperto e folgas.
- **Inglês / LEMON Manuals & Operation CHARM:** Análise de estrutura de esquemas elétricos, diagramas de sincronismo e tabelas de fluidos de mais de 10.000 modelos (1960–2025).
- **Alemão / VAG ElsaWin:** Especificações de aperto angular quádruplo para cabeçotes EA211 TSI (40 Nm + 90° + 90° + 90°) e ferramentas de sincronismo T10340 e T10494.
- **Japonês / Toyota TIS:** Dados do conjunto híbrido 2ZR-FXE (Corolla/Prius), torques de 49 Nm + 90° + 45° e circuito de arrefecimento dedicado do inversor de alta tensão.
- **Russo / Kolhosniki & CarDiagn:** Pinagens de conectores OBD2 e linhas diferenciais UDS CAN.

### 30.2 Base de Dados Estruturada (`server/app/databases/workshop_repair_manuals.json`)
Catálogo com **8 veículos fundamentais**, estruturado em:
1. **Fluidos e Capacidades:** Óleo do motor (litragem, viscosidade e norma OEM), fluido de freio, fluido de arrefecimento do motor e inversor híbrido, transmissões (manual, automática, CVT e transeixo e-CVT) e gás refrigerante A/C.
2. **Torques de Aperto (Motor & Cabeçote):** Cabeçote com etapas em graus e limites de reuso de parafusos, mancais, bielas, velas, bombas de alta pressão e polias.
3. **Sincronismo de Ponto & Distribuição:** Procedimentos passo a passo com referências de ferramentas de fasagem e alvos angulares para validação no osciloscópio (correlação CKP/CMP).
4. **Boletins Técnicos & Defeitos Frequentes:** Falhas crônicas mapeadas com causas-raiz e ações recomendadas de reparo (ex: diluição de correia banhada a óleo no GM CSS Prime, cooler de bateria híbrida obstruído no Corolla, solenoide N205 no EA211 e reguladora MPROP no M9R).
5. **Pinagem e Esquema Elétrico Rápido:** Conector OBD2, sensores de pressão de rail, wastegate e linhas de comunicação.

### 30.3 Endpoint de API Dedicado (`/api/manuals`)
- Registrado em `server/app/routers/system.py` sob a rota `GET /api/manuals`.
- Suporta retorno do catálogo completo ou filtragem instantânea por veículo via `?vehicle_id={id}`.

---

## 31. Refatoração, Repaginação Visual e Otimização da Interface Web

Com a expansão de múltiplos subsistemas (Sniffer CAN, Osciloscópio com Formas de Onda Padrão, Scanner OBD-II com UDS e Manuais de Reparação AutoData), realizamos um debug completo e uma repaginação visual focada em fluidez, ergonomia mecânica e redução de ruído visual.

### 31.1 Repaginação da Barra de Navegação e Abas (`styles.css` & `index.html`)
- **Estilo Pílula com Efeito Vidro Fosco (*Glassmorphism*):** Substituídas as abas pesadas anteriores por botões arredondados em formato de pílula flutuante com `backdrop-filter: blur(12px)` e fundo translúcido `rgba(13, 16, 23, 0.95)`.
- **Micro-interações Suaves:** Transições em curvas bezier (`cubic-bezier(0.4, 0, 0.2, 1)`), com elevação sutil (`translateY(-1px)`) no hover e bordas em néon ciano com brilho suave na aba ativa.
- **Badges Modernizados:** Contadores de pacotes CAN, status de osciloscópio e marcas de sistema agora utilizam badges com cantos totalmente arredondados (`border-radius: 99px`) e tipografia monoespaçada limpa.

### 31.2 Reorganização Estrutural do Osciloscópio
- **Divisão em Duas Linhas Claras na Toolbar:**
  - **Linha Superior (Contexto de Teste):** Fonte de sinal (Demo vs Hardware Real), Prova Rápida Automotiva, Seletor de Sinal Padrão de Fábrica (Known Good), Botão Comparar e Botão Critérios ℹ️, e botões de fluxo (Run/Stop e Limpar).
  - **Linha Inferior (Controles Elétricos de Bancada):** Ativação de canais CH1 e CH2, seletores de V/div e sliders de offset, base de tempo (T/div), tipo e limiar de Trigger, e ajuste fino de dentes de sincronismo.
- **Eliminação de Poluição Visual:** Agrupamentos limpos em caixas individuais translúcidas com bordas sutis (`border: 1px solid rgba(255, 255, 255, 0.05)`).

### 31.3 Grid Responsivo e Fluido no Scanner OBD-II
- **Barra de Ações Rápidas em Grid Adaptável:**
  - Substituído o alinhamento flex desordenado por um grid CSS responsivo (`grid-template-columns: repeat(auto-fit, minmax(140px, 1fr))`).
  - Cards de ação com ícones limpos e contraste balanceado: Varredura Rápida (Azul), Auditoria CAN (Esmeralda), Emissões I/M (Roxo), Bateria Híbrida (Céu), Laudo PDF (Azul Petróleo), Limpar Falhas (Cinza Neutro) e Abortar (Vermelho).

### 31.4 Debug Global e Validação de Endpoints
- Corrigida duplicidade de regras CSS em `.toolbar-stat`.
- Testados e validados todos os endpoints REST:
  - `GET /health` → HTTP 200 (Container Docker operando normalmente).
  - `GET /api/manuals` → HTTP 200 (8 plataformas com torques, fluidos e sincronismo).
  - `GET /api/oscilloscope/references` → HTTP 200 (12 sinais analógicos/digitais de calibração).
  - `GET /api/vin/decode` e `GET /api/dtc/lookup` → decodificação ISO 3779 e busca local de DTCs operando sem latência.

---

## 32. Módulo de Telemática Avançada & Rastreamento de Frotas AguiaCar (Padrão Teltonika / Traccar / Geotab)

A partir da pesquisa e engenharia reversa de plataformas industriais de telemática e rastreamento de veículos (Traccar, Teltonika AVL, Geotab e protocolos GT06), enriquecemos o módulo **AguiaCar** com recursos corporativos de telemetria preditiva, segurança patrimonial e análise de conduta do condutor (*Eco-Drive & Driver Safety*).

### 32.1 Cerca Virtual Geodésica Circular (Haversine Geofencing)
- **Cálculo de Distância Geodésica:** Implementação da fórmula de Haversine em `fleet_engine.py` para calcular a distância exata em quilômetros entre a coordenada GPS instantânea do veículo e o ponto central configurado para a base operacional / oficina.
- **Detecção de Transição de Estado:** Monitoramento da transição entre estados (`INSIDE` ➔ `OUTSIDE`). Evita saturação e repetição de alertas a cada ping telemático, registrando a saída com disparo de notificação crítica (`🚨 VIOLAÇÃO DE CERCA VIRTUAL (GEOFENCE EXIT)`) e e-mail automático.
- **Configuração Remota Flexível:** Raio ajustável via API e interface web de 1 a 100 km (padrão de 15 km), permitindo habilitar/desabilitar a cerca e alterar as coordenadas centrais via OTA.
- **Renderização em Tempo Real no Leaflet:** Exibição vetorial pontilhada translúcida da cerca (`L.circle`) diretamente sobre o mapa Leaflet com satélite do Google Maps e OpenStreetMap.

### 32.2 Detecção de Condução Agressiva & Colisão (Harsh Driving / G-Force)
- **Extração Inercial de Aceleração Longitudinal:**
  - Suporte a leitura direta de acelerômetro triaxial IMU (`accel_g`) presente no hardware ou cálculo em tempo real a partir da variação de velocidade ($\Delta v / \Delta t$) entre pacotes telemáticos consecutivos.
- **Limiares Normativos Industriais:**
  - **Frenagem Brusca (Harsh Brake):** $G \le -0.50\,\text{G}$ ($-4.90\,\text{m/s}^2$). Alerta preventivo com orientação sobre risco de perda de controle e desgaste prematuro de pastilhas de freio.
  - **Aceleração Brusca (Harsh Accel):** $G \ge +0.35\,\text{G}$ ($+3.43\,\text{m/s}^2$). Alerta preventivo por estresse térmico/mecânico no conjunto de transmissão e embreagem.
  - **Colisão / Impacto Severo (Crash Detection):** $|G| \ge 2.50\,\text{G}$ ($24.5\,\text{m/s}^2$). Alerta emergencial `CRITICO_PARADA` com registro de coordenadas GPS exatas para despacho de socorro.

### 32.3 Score de Condução Dinâmico (Eco-Drive & Safety Score 0-100)
- **Algoritmo de Pontuação:**
  - Pontuação inicial máxima de **100 pontos**.
  - Penalidades imediatas: **-5 pontos** por frenagem brusca, **-3 pontos** por aceleração agressiva e **-30 pontos** por colisão.
  - Recuperação progressiva: **+1 ponto** para cada período de condução contínua e suave acima de 15 km/h.
  - Exibição em tempo real na interface com anel indicador colorido (Verde $\ge 90$, Amarelo $70-89$, Vermelho $< 70$).

### 32.4 Atualizações de Banco de Dados, API & Frontend
- **Banco de Dados SQLite (`database.py`):**
  - Tabela `fleet_vehicles`: inclusão de `driving_score INTEGER DEFAULT 100` e `geofence_status TEXT DEFAULT 'INSIDE'`.
  - Tabela `fleet_configs`: inclusão de `geofence_enabled`, `geofence_lat`, `geofence_lon` e `geofence_radius_km`.
  - Tabela `fleet_telemetry`: inclusão de `accel_g REAL` e `driving_event TEXT`.
- **Rotas REST (`routers/fleet.py`):**
  - Endpoints atualizados: `GET/POST /api/fleet/config/{id}`, `GET /api/fleet/vehicles`, `GET /api/fleet/telemetry/{id}` e `POST /api/fleet/simulate`.
  - Cenários de simulação rápida integrados: `normal`, `overheat`, `cold_abuse`, `dtc`, `disconnect`, `harsh_brake`, `harsh_accel`, `crash` e `geofence_exit`.
---

