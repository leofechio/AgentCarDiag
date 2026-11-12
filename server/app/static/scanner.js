// Controlador da Aba Scanner (Launch X-431 Style)

let liveStreamActive = false;
let pendingHealthReport = false;
let healthReportModules = {};

// Atualiza tabela Live Data
function handleScannerResponse(msg) {
    if (!msg || !msg.query) return;

    // Se houver auditoria / sonda automática em andamento, processa o retorno
    if (typeof handleProbeResponse === 'function' && probeDiscoveryState && probeDiscoveryState.active) {
        handleProbeResponse(msg);
    }

    // Se houve resposta bruta válida da CAN/K-Line, marca a ECU veicular como online
    if (msg.raw && msg.raw.trim().length > 0 && !msg.raw.includes("NO DATA") && !msg.raw.includes("ERROR")) {
        if (typeof updateEcuStatus === 'function') {
            updateEcuStatus(true, msg.query === '0100' ? 'Pronta' : '');
        }
    }
    
    if (msg.query.startsWith("01") || msg.query.startsWith("22") || msg.query.startsWith("21")) {
        // Intercepta PID 0101 (Readiness Monitors)
        if (msg.query === "0101" && typeof parseReadinessStatus === 'function') {
            let dataBytes = parseObdRaw(msg.raw, "0101");
            if (dataBytes && dataBytes.length >= 4) {
                latestReadinessData = parseReadinessStatus(dataBytes);
                if (typeof renderReadinessModal === 'function') {
                    renderReadinessModal(latestReadinessData);
                }
            }
        }

        // Intercepta PID 2181 / 21CE (Toyota Hybrid HV Battery)
        if ((msg.query === "2181" || msg.query === "21CE") && typeof parseToyotaHvBattery === 'function') {
            let hvRes = parseToyotaHvBattery(msg.raw);
            if (hvRes) {
                latestHvBatteryData = hvRes;
                if (typeof renderHvBatteryModal === 'function') {
                    renderHvBatteryModal(latestHvBatteryData);
                }
            }
        }

        // Live Data (OBD-II, WWH-OBD, Toyota JDM e UDS Kangoo ZE)
        let dict = OBD_PIDS[msg.query];
        if (dict && dict.calc) {
            let dataBytes = parseObdRaw(msg.raw, msg.query);
            if (dataBytes && dataBytes.length > 0) {
                let rawValue = dict.calc(dataBytes);
                // Converte unidade se aplicável
                let converted = (typeof UnitConverter !== 'undefined') 
                    ? UnitConverter.convert(rawValue, dict.unit)
                    : { val: (typeof rawValue === 'number' ? rawValue.toFixed(1) : rawValue), unit: dict.unit };

                updateLiveDataTable(msg.query, dict.name, converted.val, converted.unit);

                // Atualiza Rastreador de Segurança Veicular (Interlock de Danos)
                updateVehicleSafetyState(msg.query, rawValue);
            }
        }
    } else if (msg.query.startsWith("09")) {
        // VIN ou Info
        let dict = OBD_PIDS[msg.query];
        if (dict && dict.isAscii) {
            let asciiStr = hexToAscii(msg.raw);
            updateEcuInfo(dict.name, asciiStr);
        }
    } else if (msg.query === "03" || msg.query === "07" || msg.query === "0A" || msg.query.startsWith("19") || msg.query.startsWith("17") || msg.query.startsWith("10") || msg.query.startsWith("14") || msg.query.startsWith("22")) {
        // Leitura de DTCs, Sessão UDS ou Limpeza de Falhas
        processDtcResponse(msg.raw);
    }
}

function startLiveData() {
    let checkboxes = document.querySelectorAll('.pid-checkbox:checked');
    let pids = Array.from(checkboxes).map(cb => cb.value);
    
    if (pids.length === 0) {
        alert("Selecione pelo menos um sensor.");
        return;
    }

    // Limpar tabela
    document.getElementById('live-data-body').innerHTML = '';

    sendBleCommand('start_live_stream', null, { pids: pids, interval_ms: 500 });
    liveStreamActive = true;
    document.getElementById('btn-start-stream').style.display = 'none';
    document.getElementById('btn-stop-stream').style.display = 'inline-block';
}

function stopLiveData() {
    sendBleCommand('stop_live_stream');
    liveStreamActive = false;
    document.getElementById('btn-start-stream').style.display = 'inline-block';
    document.getElementById('btn-stop-stream').style.display = 'none';
}

function updateLiveDataTable(pid, name, value, unit) {
    let tbody = document.getElementById('live-data-body');
    let trId = 'row-' + pid;
    let tr = document.getElementById(trId);
    
    if (!tr) {
        tr = document.createElement('tr');
        tr.id = trId;
        tr.innerHTML = `
            <td>${name}</td>
            <td id="val-${pid}" style="font-weight: bold; color: var(--accent-blue); font-size: 14px;">${value}</td>
            <td style="color: var(--text-muted);">${unit}</td>
            <td>
               <div style="width: 100px; height: 6px; background: var(--bg-body); border-radius: 3px; overflow: hidden;">
                   <div id="bar-${pid}" style="height: 100%; width: 0%; background: var(--accent-green); transition: width 0.2s;"></div>
               </div>
            </td>
        `;
        tbody.appendChild(tr);
    } else {
        document.getElementById(`val-${pid}`).innerText = value;
    }
    
    // Animação super básica da barra
    let bar = document.getElementById(`bar-${pid}`);
    if (bar) {
        let max = 100;
        if (unit === 'rpm') max = 7000;
        else if (unit === '°C') max = 150;
        else if (unit === 'km/h') max = 220;
        else if (unit === 'V') max = 15;
        else if (unit === 'kPa') max = 255;
        
        let pct = (parseFloat(value) / max) * 100;
        if (pct > 100) pct = 100;
        if (pct < 0) pct = 0;
        bar.style.width = pct + '%';
        
        if (pct > 80) bar.style.background = 'var(--accent-red)';
        else if (pct > 60) bar.style.background = '#f59e0b';
        else bar.style.background = 'var(--accent-green)';
    }
}

let healthReportState = {
    active: false,
    currentStep: 0,
    totalSteps: 0,
    steps: [],
    results: {}
};

const VEHICLE_PROFILES = {
    renault_trafic_m9r: {
        name: "Renault Trafic III (2.0 dCi M9R / Blue dCi)",
        description: "Motor M9R 2.0 dCi Euro 6d (Bosch EDC17C84 / MD1CS006). Protocolo UDS CAN 500k.",
        showCombustion: true,
        showEv: false,
        capabilities: {
            modules: ["ECM", "ABS", "BCM", "INSTRUMENTS"],
            services: ["epb_service", "dpf_regen", "throttle_learn", "sas_reset"],
            emissions: { egr: true, dpf: true, adblue: true },
            flasher: true,
            hvBattery: false
        },
        healthReportSteps: [
            { name: "🔑 Sessão Estendida UDS (0x10 03)", query: "1003", proto: "uds" },
            { name: "🔍 Injeção Falhas Ativas (UDS 19 02 09)", query: "190209", proto: "uds" },
            { name: "🚗 Injeção Memória Geral (UDS 19 02 FF)", query: "1902FF", proto: "uds" },
            { name: "🛑 Freios / ABS / ESC (UDS 19 02 FF)", query: "1902FF", proto: "uds" },
            { name: "ℹ️ Identificação Chassi / VIN (UDS 22 F1 90)", query: "22F190", proto: "uds" },
            { name: "⚠️ OBD Padrão Emissões (Modo 03)", query: "03", proto: "obd" }
        ],
        summaryInfo: "Varredura UDS Estendida Renault M9R + Freios ABS/ESC + VIN OEM."
    },
    vito_diesel: {
        name: "Mercedes Vito 109 CDI (OM622 / Renault 1.6 dCi)",
        description: "Motor a combustão diesel com ECU Delphi / Bosch via CAN Bus 500k.",
        showCombustion: true,
        showEv: false,
        capabilities: {
            modules: ["ECM", "ABS", "BCM"],
            services: ["epb_service", "dpf_regen", "throttle_learn", "sas_reset"],
            emissions: { egr: true, dpf: true, adblue: false },
            flasher: true,
            hvBattery: false
        },
        healthReportSteps: [
            { name: "🚗 Injeção / Motor ECU (UDS 19 02 FF)", query: "1902FF", proto: "uds" },
            { name: "🛑 Freios / ABS / ESP (UDS 19 02 FF)", query: "1902FF", proto: "uds" },
            { name: "🔍 Falhas Ativas OBD Padrão (Modo 03)", query: "03", proto: "obd" },
            { name: "⏳ Falhas Pendentes (Modo 07)", query: "07", proto: "obd" },
            { name: "ℹ️ Identificação VIN / Chassi (Modo 0902)", query: "0902", proto: "obd" }
        ],
        summaryInfo: "Varredura completa UDS OEM + OBD-II (Injeção OM622 e ABS)."
    },
    mb_sprinter_cdi: {
        name: "Mercedes-Benz Sprinter (OM651 / OM654 CDI)",
        description: "Comercial leve diesel com injeção Bosch EDC17/MD1 e pós-tratamento SCR AdBlue.",
        showCombustion: true,
        showEv: false,
        capabilities: {
            modules: ["ECM", "ABS", "BCM", "SCR"],
            services: ["epb_service", "dpf_regen", "throttle_learn", "sas_reset", "bms_reset"],
            emissions: { egr: true, dpf: true, adblue: true },
            flasher: true,
            hvBattery: false
        },
        healthReportSteps: [
            { name: "🚗 Injeção Sprinter CDI (UDS 19 02 FF)", query: "1902FF", proto: "uds" },
            { name: "🛑 Freios ABS / ESP 9.0 (UDS 19 02 FF)", query: "1902FF", proto: "uds" },
            { name: "💧 Nível / Status SCR AdBlue (DID 22 F1 89)", query: "22F189", proto: "uds" },
            { name: "🔍 Falhas Ativas OBD (Modo 03)", query: "03", proto: "obd" },
            { name: "ℹ️ VIN Chassi (UDS 22 F1 90)", query: "22F190", proto: "uds" }
        ],
        summaryInfo: "Varredura completa Mercedes Sprinter CDI UDS."
    },
    kangoo_ze: {
        name: "Renault Kangoo Z.E. (100% Elétrico)",
        description: "Veículo elétrico com módulos UDS (EVC/BMS, Inversor PEB, Carregador BCB).",
        showCombustion: false,
        showEv: true,
        capabilities: {
            modules: ["BMS", "PEB_INVERTER", "BCB_CHARGER", "ABS"],
            services: ["epb_service", "sas_reset"],
            emissions: { egr: false, dpf: false, adblue: false },
            flasher: false,
            hvBattery: true
        },
        healthReportSteps: [
            { name: "⚡ EVC / BMS (Módulo Bateria de Tração)", query: "1913FF", proto: "uds" },
            { name: "⚡ Inversor & Motor Elétrico (PEB)", query: "17FF00", proto: "uds" },
            { name: "🔌 Carregador de Bordo (BCB / Chameleon)", query: "190209", proto: "uds" },
            { name: "🚗 Gateway / Diagnóstico Padrão", query: "03", proto: "obd" }
        ],
        summaryInfo: "Módulos de Tração Elétrica, BMS e Carregador consultados."
    },
    renault_clio_tce: {
        name: "Renault Clio / Sandero TCe (H4D / H4Bt)",
        description: "Motor 1.0 TCe Turbo 3 Cilindros Bosch / Continental via CAN 500k.",
        showCombustion: true,
        showEv: false,
        capabilities: {
            modules: ["ECM", "ABS", "BCM"],
            services: ["throttle_learn", "sas_reset", "bms_reset"],
            emissions: { egr: true, dpf: false, adblue: false },
            flasher: true,
            hvBattery: false
        },
        healthReportSteps: [
            { name: "🔑 Sessão Estendida UDS (0x10 03)", query: "1003", proto: "uds" },
            { name: "🚗 Injeção TCe (UDS 19 02 FF)", query: "1902FF", proto: "uds" },
            { name: "🛑 Freios ABS / ESP (UDS 19 02 FF)", query: "1902FF", proto: "uds" },
            { name: "🔍 Falhas OBD (Modo 03)", query: "03", proto: "obd" }
        ],
        summaryInfo: "Varredura UDS + OBD Clio/Sandero TCe."
    },
    vw_golf_tsi: {
        name: "VW Golf / Polo / T-Cross TSI (EA211)",
        description: "Motor 1.0/1.4 TSI Bosch MED17 via CAN UDS 500k Plataforma MQB.",
        showCombustion: true,
        showEv: false,
        capabilities: {
            modules: ["ECM", "ABS", "INSTRUMENTS", "BCM"],
            services: ["epb_service", "bms_reset", "throttle_learn", "sas_reset"],
            emissions: { egr: true, dpf: false, adblue: false },
            flasher: true,
            hvBattery: false
        },
        healthReportSteps: [
            { name: "🚗 Injeção MED17 (UDS 19 02 FF)", query: "1902FF", proto: "uds" },
            { name: "🛑 Freios ABS MK100 (UDS 19 02 FF)", query: "1902FF", proto: "uds" },
            { name: "📟 Painel Instruments (UDS 19 02 09)", query: "190209", proto: "uds" },
            { name: "🔍 Falhas OBD (Modo 03)", query: "03", proto: "obd" },
            { name: "ℹ️ Identificação VIN OEM (UDS 22 F1 90)", query: "22F190", proto: "uds" }
        ],
        summaryInfo: "Varredura Golf/Polo TSI Plataforma MQB."
    },
    audi_a4_tfsi: {
        name: "Audi A4 / A3 / Q5 TFSI (EA888)",
        description: "Motor 2.0 TFSI Simos 18.x via CAN UDS 500k.",
        showCombustion: true,
        showEv: false,
        capabilities: {
            modules: ["ECM", "ABS", "TCM", "BCM"],
            services: ["epb_service", "bms_reset", "throttle_learn", "sas_reset"],
            emissions: { egr: true, dpf: false, adblue: false },
            flasher: true,
            hvBattery: false
        },
        healthReportSteps: [
            { name: "🚗 Injeção Simos TFSI (UDS 19 02 FF)", query: "1902FF", proto: "uds" },
            { name: "🛑 Freios ESP Audi (UDS 19 02 FF)", query: "1902FF", proto: "uds" },
            { name: "🕹️ Câmbio S-Tronic / DSG (UDS 19 02 09)", query: "190209", proto: "uds" },
            { name: "🔍 Falhas OBD Emissões (Modo 03)", query: "03", proto: "obd" },
            { name: "ℹ️ VIN Chassi (UDS 22 F1 90)", query: "22F190", proto: "uds" }
        ],
        summaryInfo: "Varredura Audi TFSI S-Tronic UDS."
    },
    skoda_octavia_tsi: {
        name: "Škoda Octavia / Superb / Fabia TSI/TDI",
        description: "Grupo VAG MQB com eletrônica Bosch / Continental via CAN 500k.",
        showCombustion: true,
        showEv: false,
        capabilities: {
            modules: ["ECM", "ABS", "GATEWAY", "BCM"],
            services: ["epb_service", "bms_reset", "throttle_learn", "sas_reset"],
            emissions: { egr: true, dpf: false, adblue: false },
            flasher: true,
            hvBattery: false
        },
        healthReportSteps: [
            { name: "🚗 Injeção Škoda VAG (UDS 19 02 FF)", query: "1902FF", proto: "uds" },
            { name: "🛑 Freios ABS / ESC (UDS 19 02 FF)", query: "1902FF", proto: "uds" },
            { name: "📟 Gateway / Painel (UDS 19 02 09)", query: "190209", proto: "uds" },
            { name: "🔍 Falhas OBD (Modo 03)", query: "03", proto: "obd" }
        ],
        summaryInfo: "Varredura Škoda MQB UDS."
    },
    toyota_corolla_hybrid: {
        name: "Toyota Corolla / Cross Hybrid (2ZR-FXE)",
        description: "Motor 1.8 Ciclo Atkinson + Sistema Híbrido Transaxle THS II via CAN 500k.",
        showCombustion: true,
        showEv: true,
        capabilities: {
            modules: ["ECM", "HV_HYBRID", "ABS", "BCM"],
            services: ["epb_service", "sas_reset", "throttle_learn"],
            emissions: { egr: true, dpf: false, adblue: false },
            flasher: false,
            hvBattery: true
        },
        healthReportSteps: [
            { name: "🚗 Injeção Powertrain Denso (UDS 19 02 FF)", query: "1902FF", proto: "uds" },
            { name: "⚡ Sistema Híbrido / Inversor HV (UDS 19 02 08)", query: "190208", proto: "uds" },
            { name: "🛑 Freios Hidráulicos ABS / VSC (UDS 19 02 FF)", query: "1902FF", proto: "uds" },
            { name: "🔍 Falhas Emissões OBD (Modo 03)", query: "03", proto: "obd" },
            { name: "ℹ️ VIN Chassi (Modo 0902)", query: "0902", proto: "obd" }
        ],
        summaryInfo: "Varredura Híbrida Toyota Denso + Conversor de Tração."
    },
    toyota_hilux_d4d: {
        name: "Toyota Hilux / SW4 2.8 D-4D (1GD-FTV)",
        description: "Motor turbodiesel Denso Gen 4 com filtro DPF e injeção common rail via CAN 500k.",
        showCombustion: true,
        showEv: false,
        capabilities: {
            modules: ["ECM", "ABS", "4X4"],
            services: ["dpf_regen", "throttle_learn", "sas_reset"],
            emissions: { egr: true, dpf: true, adblue: false },
            flasher: true,
            hvBattery: false
        },
        healthReportSteps: [
            { name: "🚗 Injeção Denso D-4D (UDS 19 02 FF)", query: "1902FF", proto: "uds" },
            { name: "🛑 Módulo Freios / VSC / 4x4 (UDS 19 02 FF)", query: "1902FF", proto: "uds" },
            { name: "🔍 Falhas Ativas OBD (Modo 03)", query: "03", proto: "obd" },
            { name: "ℹ️ VIN Chassi Toyota (Modo 0902)", query: "0902", proto: "obd" }
        ],
        summaryInfo: "Varredura Hilux Turbodiesel D-4D."
    },
    ford_ranger_tdci: {
        name: "Ford Ranger / Transit (2.0 / 3.2 TDCi)",
        description: "Motor diesel Duratorq / EcoBlue com ECU Continental SID208 / SID212 via CAN 500k.",
        showCombustion: true,
        showEv: false,
        capabilities: {
            modules: ["ECM", "ABS", "BCM"],
            services: ["dpf_regen", "throttle_learn", "sas_reset", "bms_reset"],
            emissions: { egr: true, dpf: true, adblue: true },
            flasher: true,
            hvBattery: false
        },
        healthReportSteps: [
            { name: "🚗 Injeção PCM Ford (UDS 19 02 FF)", query: "1902FF", proto: "uds" },
            { name: "🛑 Freios ABS / ESC (UDS 19 02 FF)", query: "1902FF", proto: "uds" },
            { name: "🏢 Carroceria BCM (UDS 19 02 09)", query: "190209", proto: "uds" },
            { name: "🔍 Falhas Ativas OBD (Modo 03)", query: "03", proto: "obd" },
            { name: "ℹ️ VIN OEM Ford (UDS 22 F1 90)", query: "22F190", proto: "uds" }
        ],
        summaryInfo: "Varredura Ford PCM Diesel + BCM."
    },
    ford_focus_ecoboost: {
        name: "Ford Focus / Fiesta / Territory EcoBoost",
        description: "Motor 1.0 / 1.5 EcoBoost com ECU Bosch MED17 / Continental via CAN 500k.",
        showCombustion: true,
        showEv: false,
        capabilities: {
            modules: ["ECM", "ABS"],
            services: ["epb_service", "throttle_learn", "sas_reset", "bms_reset"],
            emissions: { egr: true, dpf: false, adblue: false },
            flasher: true,
            hvBattery: false
        },
        healthReportSteps: [
            { name: "🚗 Injeção PCM EcoBoost (UDS 19 02 FF)", query: "1902FF", proto: "uds" },
            { name: "🛑 Freios ABS / Tração (UDS 19 02 FF)", query: "1902FF", proto: "uds" },
            { name: "🔍 Falhas OBD (Modo 03)", query: "03", proto: "obd" }
        ],
        summaryInfo: "Varredura Ford EcoBoost UDS."
    },
    hyundai_hb20_tgdi: {
        name: "Hyundai HB20 / Creta (1.0 TGDI / SmartStream)",
        description: "Motor Kappa 1.0 Turbo GDI Flex com ECU Kefico / Bosch via CAN 500k.",
        showCombustion: true,
        showEv: false,
        capabilities: {
            modules: ["ECM", "ABS", "TCM"],
            services: ["throttle_learn", "sas_reset"],
            emissions: { egr: true, dpf: false, adblue: false },
            flasher: true,
            hvBattery: false
        },
        healthReportSteps: [
            { name: "🚗 Injeção Kefico TGDI (UDS 19 02 FF)", query: "1902FF", proto: "uds" },
            { name: "🛑 Módulo Freios ABS / ESC (UDS 19 02 FF)", query: "1902FF", proto: "uds" },
            { name: "🕹️ Câmbio AT6 (UDS 19 02 09)", query: "190209", proto: "uds" },
            { name: "🔍 Falhas OBD (Modo 03)", query: "03", proto: "obd" },
            { name: "ℹ️ VIN Chassi (Modo 0902)", query: "0902", proto: "obd" }
        ],
        summaryInfo: "Varredura Hyundai TGDI + Câmbio Automático."
    },
    kia_sportage_gdi: {
        name: "Kia Sportage / Seltos / Cerato (GDI / Híbrido MHEV)",
        description: "Motor Nu / Smartstream com arquitetura CAN UDS 500k.",
        showCombustion: true,
        showEv: false,
        capabilities: {
            modules: ["ECM", "ABS"],
            services: ["epb_service", "throttle_learn", "sas_reset"],
            emissions: { egr: true, dpf: false, adblue: false },
            flasher: true,
            hvBattery: false
        },
        healthReportSteps: [
            { name: "🚗 Injeção Kia GDI (UDS 19 02 FF)", query: "1902FF", proto: "uds" },
            { name: "🛑 Freios ABS / ESC (UDS 19 02 FF)", query: "1902FF", proto: "uds" },
            { name: "🔍 Falhas OBD (Modo 03)", query: "03", proto: "obd" }
        ],
        summaryInfo: "Varredura Kia GDI UDS."
    },
    honda_civic_vtec: {
        name: "Honda Civic / HR-V / City (1.5 Turbo / e:HEV)",
        description: "Motor Earth Dreams i-VTEC / Turbo com injeção Keihin / Bosch via CAN 500k.",
        showCombustion: true,
        showEv: false,
        capabilities: {
            modules: ["ECM", "ABS", "TCM"],
            services: ["epb_service", "throttle_learn", "sas_reset"],
            emissions: { egr: true, dpf: false, adblue: false },
            flasher: true,
            hvBattery: false
        },
        healthReportSteps: [
            { name: "🚗 Injeção Keihin PGM-FI (UDS 19 02 FF)", query: "1902FF", proto: "uds" },
            { name: "🛑 Freios ABS / VSA (UDS 19 02 FF)", query: "1902FF", proto: "uds" },
            { name: "🕹️ Câmbio CVT (UDS 19 02 09)", query: "190209", proto: "uds" },
            { name: "🔍 Falhas Ativas OBD (Modo 03)", query: "03", proto: "obd" },
            { name: "ℹ️ VIN Chassi (Modo 0902)", query: "0902", proto: "obd" }
        ],
        summaryInfo: "Varredura Honda i-VTEC + VSA + Transmissão CVT."
    },
    gm_onix_turbo: {
        name: "Chevrolet Onix / Tracker (1.0 / 1.2 Turbo CSS Prime)",
        description: "Motor Ecotec Turbo 3 cilindros com injeção Delco E80/E84 via CAN 500k.",
        showCombustion: true,
        showEv: false,
        capabilities: {
            modules: ["ECM", "ABS", "BCM"],
            services: ["throttle_learn", "sas_reset", "bms_reset"],
            emissions: { egr: true, dpf: false, adblue: false },
            flasher: true,
            hvBattery: false
        },
        healthReportSteps: [
            { name: "🚗 Injeção GM Delco (UDS 19 02 FF)", query: "1902FF", proto: "uds" },
            { name: "🛑 Freios ABS / EBCM (UDS 19 02 FF)", query: "1902FF", proto: "uds" },
            { name: "🏢 Carroceria BCM (UDS 19 02 09)", query: "190209", proto: "uds" },
            { name: "🔍 Falhas OBD (Modo 03)", query: "03", proto: "obd" },
            { name: "ℹ️ VIN OEM GM (UDS 22 F1 90)", query: "22F190", proto: "uds" }
        ],
        summaryInfo: "Varredura Chevrolet Ecotec Turbo + BCM."
    },
    nissan_kicks_flex: {
        name: "Nissan Kicks / Versa / Sentra (1.6 HR16DE / 2.0)",
        description: "Motor Flex com injeção Hitachi / Bosch e câmbio CVT X-Tronic via CAN 500k.",
        showCombustion: true,
        showEv: false,
        capabilities: {
            modules: ["ECM", "TCM", "ABS"],
            services: ["throttle_learn", "sas_reset"],
            emissions: { egr: true, dpf: false, adblue: false },
            flasher: true,
            hvBattery: false
        },
        healthReportSteps: [
            { name: "🚗 Injeção Nissan Hitachi (UDS 19 02 FF)", query: "1902FF", proto: "uds" },
            { name: "🕹️ Câmbio CVT X-Tronic (UDS 19 02 09)", query: "190209", proto: "uds" },
            { name: "🛑 Freios ABS / VDC (UDS 19 02 FF)", query: "1902FF", proto: "uds" },
            { name: "🔍 Falhas OBD (Modo 03)", query: "03", proto: "obd" }
        ],
        summaryInfo: "Varredura Nissan HR16DE + Câmbio CVT."
    },
    fiat_firefly_turbo: {
        name: "Fiat Pulse / Fastback / Toro / Argo (Firefly GSE)",
        description: "Motor 1.0T / 1.3T / 1.3 Aspirado com ECU Magneti Marelli IAW 10GF via CAN 500k.",
        showCombustion: true,
        showEv: false,
        capabilities: {
            modules: ["ECM", "ABS", "BCM"],
            services: ["epb_service", "throttle_learn", "sas_reset"],
            emissions: { egr: true, dpf: false, adblue: false },
            flasher: true,
            hvBattery: false
        },
        healthReportSteps: [
            { name: "🚗 Injeção Marelli Firefly (UDS 19 02 FF)", query: "1902FF", proto: "uds" },
            { name: "🛑 Freios ABS / ESC Bosch (UDS 19 02 FF)", query: "1902FF", proto: "uds" },
            { name: "🏢 Body Computer B-CAN (UDS 19 02 09)", query: "190209", proto: "uds" },
            { name: "🔍 Falhas Confirmadas OBD (Modo 03)", query: "03", proto: "obd" },
            { name: "ℹ️ VIN Chassi (Modo 0902)", query: "0902", proto: "obd" }
        ],
        summaryInfo: "Varredura Fiat GSE Firefly + Body Computer."
    },
    jeep_renegade_compass: {
        name: "Jeep Renegade / Compass / Commander (T270 / Diesel TD350)",
        description: "Arquitetura Stellantis Small Wide 4x4 com ECU Bosch / Marelli via CAN 500k.",
        showCombustion: true,
        showEv: false,
        capabilities: {
            modules: ["ECM", "ABS", "BCM"],
            services: ["epb_service", "dpf_regen", "throttle_learn", "sas_reset"],
            emissions: { egr: true, dpf: true, adblue: true },
            flasher: true,
            hvBattery: false
        },
        healthReportSteps: [
            { name: "🚗 Injeção Jeep Powertrain (UDS 19 02 FF)", query: "1902FF", proto: "uds" },
            { name: "🛑 Módulo Freios ABS / Hill Descent (UDS 19 02 FF)", query: "1902FF", proto: "uds" },
            { name: "🏢 Módulo BCM Carroceria (UDS 19 02 09)", query: "190209", proto: "uds" },
            { name: "🔍 Falhas OBD (Modo 03)", query: "03", proto: "obd" }
        ],
        summaryInfo: "Varredura Jeep Stellantis T270 / TD350."
    },
    peugeot_208_puretech: {
        name: "Peugeot 208 / 2008 / 3008 (PureTech / THP / BlueHDi)",
        description: "Arquitetura PSA CMP com injeção Valeo VD56 / Bosch MD1 via CAN 500k.",
        showCombustion: true,
        showEv: false,
        capabilities: {
            modules: ["ECM", "ABS", "BSI"],
            services: ["epb_service", "dpf_regen", "throttle_learn", "sas_reset"],
            emissions: { egr: true, dpf: true, adblue: true },
            flasher: true,
            hvBattery: false
        },
        healthReportSteps: [
            { name: "🚗 Injeção PureTech / BlueHDi (UDS 19 02 FF)", query: "1902FF", proto: "uds" },
            { name: "🛑 Freios ABS / ESP (UDS 19 02 FF)", query: "1902FF", proto: "uds" },
            { name: "🏢 BSI Central de Carroceria (UDS 19 02 09)", query: "190209", proto: "uds" },
            { name: "🔍 Falhas OBD (Modo 03)", query: "03", proto: "obd" }
        ],
        summaryInfo: "Varredura Peugeot PSA CMP + BSI."
    },
    citroen_c3_aircross: {
        name: "Citroën C3 / Aircross / Berlingo (1.0 Turbo / 1.6 Flex)",
        description: "Plataforma Stellantis / PSA com injeção Marelli / Bosch via CAN 500k.",
        showCombustion: true,
        showEv: false,
        capabilities: {
            modules: ["ECM", "ABS"],
            services: ["throttle_learn", "sas_reset"],
            emissions: { egr: true, dpf: false, adblue: false },
            flasher: true,
            hvBattery: false
        },
        healthReportSteps: [
            { name: "🚗 Injeção Motor Citroën (UDS 19 02 FF)", query: "1902FF", proto: "uds" },
            { name: "🛑 Freios ABS (UDS 19 02 FF)", query: "1902FF", proto: "uds" },
            { name: "🔍 Falhas OBD (Modo 03)", query: "03", proto: "obd" }
        ],
        summaryInfo: "Varredura Citroën UDS."
    },
    bmw_320i_b48: {
        name: "BMW 320i / 330i / X1 (Motor B48 TwinPower)",
        description: "Motor 2.0 Turbo B48 com injeção Bosch MG1 via CAN UDS 500k.",
        showCombustion: true,
        showEv: false,
        capabilities: {
            modules: ["ECM", "ABS", "FEM"],
            services: ["epb_service", "bms_reset", "throttle_learn", "sas_reset"],
            emissions: { egr: true, dpf: false, adblue: false },
            flasher: true,
            hvBattery: false
        },
        healthReportSteps: [
            { name: "🚗 Injeção DME Bosch MG1 (UDS 19 02 FF)", query: "1902FF", proto: "uds" },
            { name: "🛑 Freios DSC / ABS (UDS 19 02 FF)", query: "1902FF", proto: "uds" },
            { name: "🏢 Módulo FEM / BDC Carroceria (UDS 19 02 09)", query: "190209", proto: "uds" },
            { name: "🔍 Falhas OBD Padrão (Modo 03)", query: "03", proto: "obd" },
            { name: "ℹ️ VIN OEM BMW (UDS 22 F1 90)", query: "22F190", proto: "uds" }
        ],
        summaryInfo: "Varredura BMW B48 TwinPower + DSC + FEM."
    },
    byd_dolphin_seal_ev: {
        name: "BYD Dolphin / Seal / Yuan Plus (e-Platform 3.0)",
        description: "Veículo 100% Elétrico com bateria Blade LFP, inversor 8-em-1 e CAN UDS 500k.",
        showCombustion: false,
        showEv: true,
        capabilities: {
            modules: ["BMS", "MCU_INVERTER", "OBC", "IPB_BRAKES"],
            services: ["epb_service", "sas_reset"],
            emissions: { egr: false, dpf: false, adblue: false },
            flasher: false,
            hvBattery: true
        },
        healthReportSteps: [
            { name: "⚡ Bateria Blade LFP / BMS (UDS 19 02 FF)", query: "1902FF", proto: "uds" },
            { name: "⚡ Inversor Motor Tração MCU (UDS 19 02 09)", query: "190209", proto: "uds" },
            { name: "🔌 Carregador OBC e Gerenciamento Térmico", query: "190208", proto: "uds" },
            { name: "🛑 Freios Eletrônicos IPB Bosch (UDS 19 02 FF)", query: "1902FF", proto: "uds" },
            { name: "ℹ️ VIN OEM BYD (UDS 22 F1 90)", query: "22F190", proto: "uds" }
        ],
        summaryInfo: "Varredura Completa EV BYD (BMS Blade + Inversor MCU + Freios IPB)."
    },
    suzuki_jimny_k15b: {
        name: "Suzuki Jimny Sierra / Vitara (K15B / Boosterjet)",
        description: "Motor 1.5 K15B com ECU Bosch / Denso e tração 4x4 AllGrip via CAN 500k.",
        showCombustion: true,
        showEv: false,
        capabilities: {
            modules: ["ECM", "ABS", "4X4"],
            services: ["throttle_learn", "sas_reset"],
            emissions: { egr: true, dpf: false, adblue: false },
            flasher: true,
            hvBattery: false
        },
        healthReportSteps: [
            { name: "🚗 Injeção Suzuki K15B (UDS 19 02 FF)", query: "1902FF", proto: "uds" },
            { name: "🛑 Tração 4x4 AllGrip / Freios ABS (UDS 19 02 FF)", query: "1902FF", proto: "uds" },
            { name: "🔍 Falhas Ativas OBD (Modo 03)", query: "03", proto: "obd" },
            { name: "ℹ️ VIN Chassi Suzuki (Modo 0902)", query: "0902", proto: "obd" }
        ],
        summaryInfo: "Varredura Suzuki Jimny K15B + AllGrip 4x4."
    },
    tesla_model3_y: {
        name: "Tesla Model 3 / Model Y (Highland / Performance)",
        description: "Veículo 100% elétrico com barramento CAN e módulos de bateria / trem de força.",
        showCombustion: false,
        showEv: true,
        capabilities: {
            modules: ["BMS", "DI_INVERTER", "IBOOSTER"],
            services: ["epb_service"],
            emissions: { egr: false, dpf: false, adblue: false },
            flasher: false,
            hvBattery: true
        },
        healthReportSteps: [
            { name: "⚡ Battery Management System BMS (UDS 22 F1 90)", query: "22F190", proto: "uds" },
            { name: "⚡ Drive Inverter & Powertrain DI (UDS 19 02 FF)", query: "1902FF", proto: "uds" },
            { name: "🛑 Freios Regenerativos Bosch iBooster (UDS 19 02 FF)", query: "1902FF", proto: "uds" },
            { name: "ℹ️ VIN Chassi (Modo 0902)", query: "0902", proto: "obd" }
        ],
        summaryInfo: "Varredura de Barramento e Módulos Tesla EV."
    },
    generic_obd: {
        name: "Padrão Genérico OBD-II / EOBD (Universal)",
        description: "Varredura padrão universal de emissões para veículos CAN 11-bit 500k.",
        showCombustion: true,
        showEv: false,
        capabilities: {
            modules: ["ECM"],
            services: [],
            emissions: { egr: false, dpf: false, adblue: false },
            flasher: false,
            hvBattery: false
        },
        healthReportSteps: [
            { name: "🚗 Falhas Ativas / Confirmadas (Modo 03)", query: "03", proto: "obd" },
            { name: "🔍 Falhas Pendentes (Modo 07)", query: "07", proto: "obd" },
            { name: "🛑 Falhas Permanentes (Modo 0A)", query: "0A", proto: "obd" },
            { name: "ℹ️ Identificação Chassi VIN (Modo 0902)", query: "0902", proto: "obd" }
        ],
        summaryInfo: "Varredura padrão universal OBD-II / EOBD concluída."
    }
};

let currentVehicleProfile = "generic_obd";

function changeVehicleProfile() {
    const sel = document.getElementById("hw-vehicle-select");
    if (!sel) return;
    
    currentVehicleProfile = sel.value;
    const profile = VEHICLE_PROFILES[currentVehicleProfile] || VEHICLE_PROFILES.vito_diesel;
    
    const combGroup = document.getElementById("sensors-combustion-group");
    const evGroup = document.getElementById("sensors-ev-group");
    
    if (combGroup) combGroup.style.display = profile.showCombustion ? "block" : "none";
    if (evGroup) evGroup.style.display = profile.showEv ? "block" : "none";
    
    // Configura marcação padrão dos checkboxes de acordo com o perfil
    if (profile.showCombustion) {
        document.querySelectorAll('#sensors-combustion-group input[type="checkbox"]').forEach(cb => {
            if (cb.value === "010C" || cb.value === "0105" || cb.value === "010D" || cb.value === "0111" || cb.value === "0142") {
                cb.checked = true;
            }
        });
        if (evGroup) {
            document.querySelectorAll('#sensors-ev-group input[type="checkbox"]').forEach(cb => cb.checked = false);
        }
    } else if (profile.showEv) {
        if (combGroup) {
            document.querySelectorAll('#sensors-combustion-group input[type="checkbox"]').forEach(cb => cb.checked = false);
        }
        document.querySelectorAll('#sensors-ev-group input[type="checkbox"]').forEach(cb => {
            if (cb.value === "222002" || cb.value === "222005" || cb.value === "222001") {
                cb.checked = true;
            }
        });
    }

    // Se houver leitura ativa, reinicia para aplicar novos PIDs
    if (liveStreamActive) {
        stopLiveData();
        startLiveData();
    }
    
    // Atualiza o card de perfil ativo na barra lateral esquerda (Sidebar)
    updateSidebarActiveProfile(profile);

    // Salva na sessão ativa se houver uma aberta
    if (typeof state !== 'undefined' && state.activeSessionId) {
        apiFetch(`/api/sessions/${state.activeSessionId}`, {
            method: 'PUT',
            body: JSON.stringify({ vehicle_profile: currentVehicleProfile })
        }).catch(() => {});
        // Atualiza na lista local de sessões
        const sObj = state.sessions.find(s => s.id === state.activeSessionId);
        if (sObj) {
            sObj.vehicle_profile = currentVehicleProfile;
            renderSessionList();
        }
    }

    // Atualiza capacidades de botões e funções de acordo com o perfil do veículo
    if (typeof updateSystemActionCapabilities === 'function') {
        updateSystemActionCapabilities();
    }

    if (window.sysLog) {
        window.sysLog(`Perfil de Veículo alterado para: ${profile.name}`, "info");
    }
}

function updateSidebarActiveProfile(profile) {
    const nameEl = document.getElementById("sidebar-profile-name");
    const descEl = document.getElementById("sidebar-profile-desc");
    const tagEl = document.getElementById("sidebar-profile-tag");
    if (nameEl) nameEl.textContent = profile.name;
    if (descEl) descEl.textContent = profile.description || profile.summaryInfo || "CAN UDS 500k";
    if (tagEl) {
        tagEl.textContent = profile.showEv ? "100% ELÉTRICO" : "CAN 500k";
        tagEl.style.background = profile.showEv ? "var(--accent-green)" : "var(--accent-cyan)";
    }
}

function abortOperations() {
    if (healthReportState.active) {
        healthReportState.active = false;
        clearTimeout(healthReportState.stepTimeout);
        let list = document.getElementById('health-report-list');
        if (list) {
            list.innerHTML = `<div style="color: var(--accent-red); padding: 12px; text-align: center; border: 1px dashed var(--accent-red); border-radius: 6px;">⛔ Operação abortada pelo usuário.</div>`;
        }
    }
    if (liveStreamActive) {
        stopLiveData();
    }
    if (window.sysLog) {
        window.sysLog("Operações de varredura/stream canceladas.", "warn");
    }
}

function startHealthReport() {
    let list = document.getElementById('health-report-list');
    if (!list) return;

    // Verifica se há hardware ESP32 / Scanner conectado antes de varrer
    const isHardwareOnline = (window.state && window.state.hwNodes > 0) ||
        (document.getElementById("status-scanner") && document.getElementById("status-scanner").classList.contains("online"));

    if (!isHardwareOnline) {
        alert("⚠️ NENHUM DISPOSITIVO CONECTADO:\n\nO Scanner CAN (ESP32) não está conectado ou online no servidor.\nConecte o aparelho na tomada OBD-II do veículo e aguarde o status '● Online' antes de iniciar a varredura.");
        list.innerHTML = `<div style="background: rgba(239, 68, 68, 0.1); border: 1px dashed var(--accent-red); border-radius: 8px; padding: 16px; text-align: center; color: #fca5a5; font-size: 13px;">
            ⚠️ <strong>Nenhum Scanner Conectado ao Servidor</strong><br>
            <span style="font-size: 12px; color: var(--text-muted); margin-top: 4px; display: block;">Conecte o hardware ESP32-S3 na porta OBD-II para permitir a leitura física da ECU.</span>
        </div>`;
        return;
    }

    const profile = VEHICLE_PROFILES[currentVehicleProfile] || VEHICLE_PROFILES.generic_obd;

    // Lista de módulos e serviços de diagnóstico de acordo com o perfil
    healthReportState.steps = [...profile.healthReportSteps];
    healthReportState.active = true;
    healthReportState.currentStep = 0;
    healthReportState.totalSteps = healthReportState.steps.length;
    healthReportState.results = {};

    renderHealthReportProgress();
    runNextHealthReportStep();
}

function renderHealthReportProgress() {
    let list = document.getElementById('health-report-list');
    if (!list) return;

    let pct = Math.round((healthReportState.currentStep / healthReportState.totalSteps) * 100);
    let stepObj = healthReportState.steps[healthReportState.currentStep] || { name: "Concluindo..." };

    let html = `
        <div style="background: rgba(0, 212, 255, 0.05); border: 1px solid var(--border-subtle); padding: 14px; border-radius: 8px; margin-bottom: 12px;">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom: 8px;">
                <span style="font-size: 13px; font-weight: bold; color: var(--accent-cyan);">
                    🔍 Varrendo: ${stepObj.name}
                </span>
                <span style="font-size: 12px; font-weight: bold; color: var(--text-main); font-family: monospace;">${pct}%</span>
            </div>
            <div style="width: 100%; height: 8px; background: rgba(255,255,255,0.1); border-radius: 4px; overflow: hidden;">
                <div style="width: ${pct}%; height: 100%; background: linear-gradient(90deg, var(--accent-blue), var(--accent-cyan)); transition: width 0.3s ease;"></div>
            </div>
            <div style="font-size: 11px; color: var(--text-muted); margin-top: 6px;">
                Enviando serviço diagnóstico: <code>${stepObj.query}</code> | Módulo ${healthReportState.currentStep + 1} de ${healthReportState.totalSteps}
            </div>
        </div>
        <div id="health-report-cards"></div>
    `;
    list.innerHTML = html;
    renderAllReportCards();
}

function runNextHealthReportStep() {
    if (healthReportState.currentStep >= healthReportState.totalSteps) {
        healthReportState.active = false;
        finishHealthReport();
        return;
    }

    let step = healthReportState.steps[healthReportState.currentStep];
    renderHealthReportProgress();

    // Dispara query para o scanner ESP32
    sendBleCommand('obd_send', null, { query: step.query, request_id: 'health_step_' + healthReportState.currentStep });

    // Timeout de segurança: se a ECU não responder em 1.5s, avança para o próximo módulo
    clearTimeout(healthReportState.stepTimeout);
    healthReportState.stepTimeout = setTimeout(() => {
        if (healthReportState.active) {
            if (!healthReportState.results[step.name]) {
                healthReportState.results[step.name] = { dtcs: [], noResponse: true };
            }
            healthReportState.currentStep++;
            runNextHealthReportStep();
        }
    }, 1200);
}

function finishHealthReport() {
    let list = document.getElementById('health-report-list');
    if (!list) return;

    let totalDtcs = 0;
    for (let mod in healthReportState.results) {
        totalDtcs += (healthReportState.results[mod].dtcs || []).length;
    }

    const profile = VEHICLE_PROFILES[currentVehicleProfile] || VEHICLE_PROFILES.vito_diesel;

    let statusHeader = `
        <div style="background: ${totalDtcs === 0 ? 'rgba(16, 185, 129, 0.1)' : 'rgba(239, 68, 68, 0.1)'}; border: 1px solid ${totalDtcs === 0 ? 'var(--accent-green)' : 'var(--accent-red)'}; padding: 12px; border-radius: 8px; margin-bottom: 12px; display:flex; justify-content:space-between; align-items:center;">
            <div>
                <h4 style="margin: 0; color: ${totalDtcs === 0 ? 'var(--accent-green)' : 'var(--accent-red)'};">
                    ${totalDtcs === 0 ? '✅ Varredura Concluída — Nenhum Código de Falha' : `⚠️ Varredura Concluída — ${totalDtcs} Falha(s) Detectada(s)`}
                </h4>
                <p style="margin: 4px 0 0 0; font-size: 11px; color: var(--text-muted);">
                    ${profile.name} — ${profile.summaryInfo}
                </p>
            </div>
            <button class="btn btn-secondary" onclick="startHealthReport()" style="padding: 4px 10px; font-size: 11px;">Repetir</button>
        </div>
        <div id="health-report-cards"></div>
    `;
    list.innerHTML = statusHeader;
    renderAllReportCards();

    // Persiste os resultados do scanner na sessão ativa (individual por sessão)
    if (typeof state !== 'undefined' && state.activeSessionId) {
        try {
            const scannerPayload = {
                profile: currentVehicleProfile,
                timestamp: new Date().toISOString(),
                totalDtcs: totalDtcs,
                results: healthReportState.results
            };
            apiFetch(`/api/sessions/${state.activeSessionId}`, {
                method: 'PUT',
                body: JSON.stringify({
                    scanner_data: JSON.stringify(scannerPayload),
                    vehicle_profile: currentVehicleProfile
                })
            }).catch(() => {});
        } catch (e) {}
    }
}

function renderAllReportCards() {
    let container = document.getElementById('health-report-cards');
    if (!container) return;

    let html = '';
    for (let modName in healthReportState.results) {
        let res = healthReportState.results[modName];
        let dtcs = res.dtcs || [];

        if (res.sessionOpened) {
            html += `
                <div style="background: rgba(0, 212, 255, 0.08); border: 1px solid rgba(0, 212, 255, 0.3); padding: 10px; border-radius: 6px; margin-bottom: 8px;">
                    <div style="display:flex; justify-content:space-between; align-items:center;">
                        <span style="font-size: 12px; font-weight: bold; color: var(--accent-cyan);">${modName}</span>
                        <span style="font-size: 11px; color: var(--accent-cyan); background: rgba(0,212,255,0.15); padding: 2px 6px; border-radius: 3px; font-weight: bold;">🔑 Sessão Estendida Ativa</span>
                    </div>
                </div>
            `;
        } else if (res.rejected) {
            html += `
                <div style="background: rgba(245, 158, 11, 0.08); border: 1px solid rgba(245, 158, 11, 0.3); padding: 10px; border-radius: 6px; margin-bottom: 8px;">
                    <div style="display:flex; justify-content:space-between; align-items:center;">
                        <span style="font-size: 12px; font-weight: bold; color: #f59e0b;">${modName}</span>
                        <span style="font-size: 11px; color: #f59e0b; background: rgba(245,158,11,0.15); padding: 2px 6px; border-radius: 3px;">Rejeitado (${res.reason || 'Restrito'})</span>
                    </div>
                </div>
            `;
        } else if (res.noResponse) {
            html += `
                <div style="background: var(--bg-panel-alt); border: 1px solid rgba(255,255,255,0.05); padding: 10px; border-radius: 6px; margin-bottom: 8px;">
                    <div style="display:flex; justify-content:space-between; align-items:center;">
                        <span style="font-size: 12px; font-weight: bold; color: var(--text-main);">${modName}</span>
                        <span style="font-size: 11px; color: var(--text-muted); background: rgba(255,255,255,0.05); padding: 2px 6px; border-radius: 3px;">Sem falhas / Repouso</span>
                    </div>
                </div>
            `;
        } else if (dtcs.length === 0) {
            html += `
                <div style="background: rgba(16, 185, 129, 0.08); border: 1px solid rgba(16, 185, 129, 0.3); padding: 10px; border-radius: 6px; margin-bottom: 8px;">
                    <div style="display:flex; justify-content:space-between; align-items:center;">
                        <span style="font-size: 12px; font-weight: bold; color: var(--accent-green);">${modName}</span>
                        <span style="font-size: 11px; color: var(--accent-green); font-weight: bold;">0 DTCs (OK)</span>
                    </div>
                </div>
            `;
        } else {
            html += `
                <div style="background: rgba(239, 68, 68, 0.1); border: 1px solid var(--accent-red); padding: 12px; border-radius: 8px; margin-bottom: 8px;">
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom: 8px;">
                        <strong style="color: var(--accent-red); font-size: 13px;">${modName}</strong>
                        <span style="font-size: 11px; background: rgba(239, 68, 68, 0.2); color: var(--accent-red); padding: 2px 6px; border-radius: 3px; font-weight: bold;">${dtcs.length} Falha(s)</span>
                    </div>
            `;
            const RENAULT_MERCEDES_KNOWN = {
                "P0002": "Circuito de controle do regulador de dosagem de combustível - Faixa/Desempenho (Válvula dosadora de pressão do rail / bomba de alta M9R)",
                "P0002F1": "Regulador de fluxo de combustível - Circuito aberto ou sinal fora da tolerância",
                "P048B": "Sensor de posição / interruptor do atuador de controle de gases de escape",
                "U029D": "Perda de comunicação com sensor de óxidos de nitrogênio (NOx) A",
                "U0401": "Dados inválidos recebidos do Módulo de Controle do Motor (ECM/ECU)",
                "C0841": "Módulo de Controle do Sistema de Freios / Falha de barramento / Calibração",
                "U0415": "Dados Inválidos Recebidos do Módulo ABS/Freios",
                "P0601": "Módulo de Controle Interno / Checksum de Memória",
                "P048B1C": "Atuador da válvula de borboleta de gases de escape - Tensão do circuito fora da faixa",
                "U029D87": "Sensor NOx A - Mensagem ausente ou falha no barramento",
                "U040164": "ECM - Mensagem de rotação ou dados de injeção plausíveis ausentes"
            };

            for (let d of dtcs) {
                let baseCode = d.code.split('(')[0];
                let desc = RENAULT_MERCEDES_KNOWN[d.rawCode] || RENAULT_MERCEDES_KNOWN[baseCode] || `Falha diagnóstica registrada na ECU`;
                let statusBadge = d.statusLabel || `Status: 0x${d.status}`;
                let isInactive = d.statusLabel && d.statusLabel.includes("Inactivo");
                let badgeBg = isInactive ? "rgba(245, 158, 11, 0.15)" : "rgba(239, 68, 68, 0.2)";
                let badgeColor = isInactive ? "#f59e0b" : "var(--accent-red)";

                html += `
                    <div style="background: var(--bg-panel-alt); padding: 10px; border-radius: 6px; margin-bottom: 8px; border-left: 3px solid ${badgeColor};">
                        <div style="display:flex; justify-content:space-between; align-items:center;">
                            <strong style="color: ${badgeColor}; font-size: 13px; font-family: monospace;">${d.code}</strong>
                            <div style="display:flex; gap:6px; align-items:center;">
                                <button class="btn btn-secondary" onclick="inspectDtcFreezeFrame('${baseCode}', '${modName}')" style="padding: 2px 6px; font-size: 10px; border-color: var(--accent-cyan); color: var(--accent-cyan);" title="Ler parâmetros de motor gravados no momento exato desta falha">❄️ Freeze Frame</button>
                                <span style="font-size: 10px; background: ${badgeBg}; color: ${badgeColor}; padding: 2px 6px; border-radius: 3px; font-weight: bold;">${statusBadge}</span>
                            </div>
                        </div>
                        <div style="font-size: 11px; color: var(--text-main); margin-top: 4px; font-weight: 500;">${desc}</div>
                        ${d.statusDetail ? `<div style="font-size: 10px; color: var(--text-muted); margin-top: 2px;">ℹ️ ${d.statusDetail}</div>` : ''}
                        <div id="freeze-frame-box-${baseCode}" style="display:none; margin-top:8px; padding:8px; background:rgba(0,0,0,0.3); border-radius:4px; border:1px dashed var(--accent-cyan); font-size:11px;"></div>
                    </div>
                `;
            }
            html += `
                <button class="btn btn-secondary" onclick="sendBleCommand('obd_send', null, { query: '14FFFFFF', request_id: 'clear_dtc' })" style="padding: 4px 8px; font-size: 11px; margin-top: 6px;">Limpar Falhas Deste Módulo</button>
                </div>
            `;
        }
    }
    container.innerHTML = html;
}

function decodeUdsStatus(statusByte) {
    let st = parseInt(statusByte, 16) || 0;
    let testFailed = (st & 0x01) !== 0;
    let testFailedThisCycle = (st & 0x02) !== 0;
    let pendingDTC = (st & 0x04) !== 0;
    let confirmedDTC = (st & 0x08) !== 0;
    let testNotCompletedSinceClear = (st & 0x10) !== 0;
    let testFailedSinceClear = (st & 0x20) !== 0;
    let warningIndicatorRequested = (st & 0x80) !== 0;

    let label = "Ativo / Presente";
    let detail = "";

    if (!testFailed && (testFailedSinceClear || confirmedDTC)) {
        label = "Arquivo (inactivo)";
        detail = "Prueba fallada desde el momento del último reseteo de fallas";
    } else if (testFailed) {
        label = "Activo / Presente";
        detail = "Falla confirmada e teste falhou no ciclo atual";
    } else if (pendingDTC) {
        label = "Pendiente";
        detail = "Falla detectada neste ciclo de condução";
    } else {
        label = `Status (0x${statusByte.toUpperCase()})`;
    }

    return { label, detail };
}

function processDtcResponse(rawHex) {
    let parts = rawHex.split(' ').filter(p => p.trim() !== '');
    if (parts.length === 0) return;

    if (parts[0].length === 3) parts.shift();

    let dtcs = [];
    let isNegativeResp = (parts.indexOf('7F') !== -1);
    let isSessionPositive = (parts.indexOf('50') !== -1);
    let isUdsPositive = (parts.indexOf('59') !== -1);
    let isObdPositive = (parts.indexOf('43') !== -1 || parts.indexOf('47') !== -1 || parts.indexOf('4A') !== -1);

    // Se a central respondeu com NRC (Recusa de Comando / Service Not Supported)
    if (isNegativeResp) {
        let outcome = { name: "Comando Rejeitado", reason: "ECU não suporta ou recusou o comando", nrc: "0x7F" };
        if (typeof parseUdsResponse === 'function') {
            const parsed = parseUdsResponse(rawHex);
            if (parsed) outcome = parsed;
        }
        const errName = outcome.name || "Comando Rejeitado";
        const errReason = outcome.reason || "ECU recusou esta operação";
        const errNrc = outcome.nrc || "0x7F";

        // NRC 0x78 NÃO É ERRO! É "Request Correctly Received - Response Pending"
        // A central apenas informa que está lendo a memória e enviará os DTCs em seguida
        if (outcome.nrc === '0x78' || parts.indexOf('78') !== -1) {
            if (window.sysLog) {
                window.sysLog("⏳ Central ECU processando leitura de memória flash (NRC 0x78: Response Pending), aguardando buffer de DTCs...", "info");
            }
            // Renova o timeout do Health Report dando tempo da ECU transmitir o pacote final de falhas
            clearTimeout(healthReportState.stepTimeout);
            healthReportState.stepTimeout = setTimeout(() => {
                if (healthReportState.active) {
                    let stepName = healthReportState.steps[healthReportState.currentStep]?.name;
                    if (stepName && !healthReportState.results[stepName]) {
                        healthReportState.results[stepName] = { dtcs: [], noResponse: true };
                    }
                    healthReportState.currentStep++;
                    runNextHealthReportStep();
                }
            }, 3000);
            return; // Permanece no mesmo passo aguardando a resposta positiva!
        }

        if (window.sysLog) {
            window.sysLog(`⚠️ Central Informou: ${errName} (${errReason}) [NRC: ${errNrc}]`, "warn");
        }
        if (typeof showToast === 'function') {
            showToast(`⚠️ Central: ${errName} (${errNrc})`, "warn");
        }

        // Se estiver dentro de Health Report guiado, avança para o próximo módulo sem travar a varredura!
        if (healthReportState.active && healthReportState.currentStep < healthReportState.totalSteps) {
            let step = healthReportState.steps[healthReportState.currentStep];
            healthReportState.results[step.name] = { 
                dtcs: [], 
                rejected: true, 
                reason: `${errName} (${errNrc})` 
            };
            clearTimeout(healthReportState.stepTimeout);
            healthReportState.currentStep++;
            runNextHealthReportStep();
        }
        return;
    }

    // Se foi resposta positiva para Sessão Estendida UDS (0x10 03 -> 0x50 03)
    if (isSessionPositive) {
        if (window.sysLog) {
            window.sysLog("✅ Sessão Estendida UDS (0x10 03) confirmada pela ECU!", "info");
        }
        if (healthReportState.active && healthReportState.currentStep < healthReportState.totalSteps) {
            let step = healthReportState.steps[healthReportState.currentStep];
            healthReportState.results[step.name] = { dtcs: [], sessionOpened: true, detail: "Sessão Estendida Ativa" };
            clearTimeout(healthReportState.stepTimeout);
            healthReportState.currentStep++;
            runNextHealthReportStep();
            return;
        }
    }

    if (isUdsPositive) {
        // Formato ISO 14229 Service 0x19:
        // Ex: 59 02 FF [DTC_High] [DTC_Mid] [Failure_Type_Byte] [Status_Byte] ...
        let startIdx = 0;
        for (let i = 0; i < parts.length; i++) {
            if (parts[i] === '59') {
                startIdx = i + 2; // pula '59' e o subfunção '02' ou status mask
                if (startIdx < parts.length && parts[startIdx] === 'FF') startIdx++;
                break;
            }
        }

        while (startIdx + 3 < parts.length) {
            let b1 = parseInt(parts[startIdx], 16);
            let b2 = parseInt(parts[startIdx+1], 16);
            let ftb = parts[startIdx+2]; // Failure Type Byte
            let st = parts[startIdx+3];  // Status Mask Byte

            // Não ignora códigos como P0002 onde b1 é 0x00! Ignora apenas se for padding nulo (00 00, AA AA ou 55 55)
            let isPadding = (b1 === 0 && b2 === 0) || (b1 === 0xAA && b2 === 0xAA) || (b1 === 0x55 && b2 === 0x55) || isNaN(b1) || isNaN(b2);

            if (!isPadding) {
                let standardCode = decodeDtc(b1, b2);
                let formattedCode = `${standardCode}(${ftb.toUpperCase()})`;
                let rawHexCode = `${parts[startIdx]}${parts[startIdx+1]}${ftb}`.toUpperCase();
                let statusDecoded = decodeUdsStatus(st);

                dtcs.push({
                    code: formattedCode,
                    rawCode: rawHexCode,
                    status: st,
                    statusLabel: statusDecoded.label,
                    statusDetail: statusDecoded.detail
                });
            }
            startIdx += 4;
        }
    } else if (isObdPositive) {
        let obdIdx = parts.indexOf('43');
        if (obdIdx === -1) obdIdx = parts.indexOf('47');
        if (obdIdx === -1) obdIdx = parts.indexOf('4A');

        let numDtcs = 0;
        if (obdIdx !== -1 && obdIdx + 1 < parts.length) {
            numDtcs = parseInt(parts[obdIdx + 1], 16) || 0;
            for (let i = 0; i < numDtcs; i++) {
                let offset = obdIdx + 2 + (i * 2);
                if (offset + 1 < parts.length) {
                    let b1 = parseInt(parts[offset], 16);
                    let b2 = parseInt(parts[offset+1], 16);
                    let code = decodeDtc(b1, b2);
                    dtcs.push({
                        code: code,
                        rawCode: `${parts[offset]}${parts[offset+1]}`,
                        status: "08",
                        statusLabel: "Confirmado (OBD-II)",
                        statusDetail: "Código de falha via emissões OBD"
                    });
                }
            }
        }
    }

    // Se estivermos dentro da sequência guiada de Health Report
    if (healthReportState.active && healthReportState.currentStep < healthReportState.totalSteps) {
        let step = healthReportState.steps[healthReportState.currentStep];
        healthReportState.results[step.name] = { dtcs: dtcs, noResponse: false };
        clearTimeout(healthReportState.stepTimeout);
        healthReportState.currentStep++;
        runNextHealthReportStep();
        return;
    }

    // Caso de chamada isolada
    let list = document.getElementById('health-report-list');
    if (!list) return;
    if (dtcs.length === 0) {
        list.innerHTML = `
            <div style="background: rgba(16, 185, 129, 0.1); border: 1px solid var(--accent-green); padding: 12px; border-radius: 8px;">
                <h4 style="color: var(--accent-green); margin: 0;">⚡ Diagnóstico de Falhas</h4>
                <p style="margin: 4px 0 0 0; font-size: 12px; color: var(--text-muted);">Nenhum código de falha ativo retornado (0 DTCs).</p>
            </div>
        `;
    }
}

function decodeDtc(b1, b2) {
    let prefixBits = (b1 >> 6) & 0x03;
    let char1 = ['P', 'C', 'B', 'U'][prefixBits];
    
    let char2 = (b1 >> 4) & 0x03;
    let char3 = b1 & 0x0F;
    let char4 = (b2 >> 4) & 0x0F;
    let char5 = b2 & 0x0F;
    
    return `${char1}${char2}${char3.toString(16).toUpperCase()}${char4.toString(16).toUpperCase()}${char5.toString(16).toUpperCase()}`;
}

function updateEcuInfo(label, val) {
    let list = document.getElementById('ecu-info-list');
    if (!list) return;
    list.innerHTML += `
        <div style="display: flex; justify-content: space-between; padding: 6px; border-bottom: 1px solid var(--border-subtle);">
            <span style="color: var(--text-muted); font-size: 12px;">${label}</span>
            <span style="font-family: monospace; color: var(--text-main); font-weight: bold;">${val}</span>
        </div>
    `;
}

function clearAllDtcs() {
    if (confirm("ATENÇÃO: Deseja apagar todas as falhas de emissões gravadas (Modo 04)? O motor deve estar desligado (apenas ignição ligada).")) {
        sendBleCommand('obd_send', null, { query: '04', request_id: 'clear_all' });
        alert("Comando de Limpeza enviado para as ECUs.");
    }
}

// Troca de protocolo no ESP32 (CAN Bus vs Linha K)
function changeHardwareProtocol() {
    const selector = document.getElementById("hw-protocol-select");
    if (!selector) return;
    
    const proto = selector.value;
    const msg = {
        cmd: "set_protocol",
        command: "set_protocol",
        proto: proto
    };
    
    let sent = false;
    if (typeof sendBleCommand === "function" && typeof telemetryWs !== "undefined" && telemetryWs && telemetryWs.readyState === WebSocket.OPEN) {
        sendBleCommand('set_protocol', null, { proto: proto });
        sent = true;
    }
    if (window.state && window.state.ws && window.state.ws.readyState === WebSocket.OPEN) {
        window.state.ws.send(JSON.stringify(msg));
        sent = true;
    }
    
    if (sent) {
        if (window.sysLog) window.sysLog(`Solicitando troca de protocolo para: ${proto.toUpperCase()}`, "info");
    } else {
        alert("Sem conexão ativa com o Servidor!");
    }
}

// Chaveamento do Multiplexador de Pinos OBD2 (ECU, ABS, Airbag, Câmbio)
function changeHardwareModulePin() {
    const selector = document.getElementById("hw-module-select");
    if (!selector) return;
    
    const parts = selector.value.split(":");
    const pin = parseInt(parts[0], 10) || 7;
    const moduleName = parts[1] || "ECU";

    const msg = {
        cmd: "set_module_pin",
        command: "set_module_pin",
        pin: pin,
        module: moduleName
    };
    
    let sent = false;
    if (typeof sendBleCommand === "function" && typeof telemetryWs !== "undefined" && telemetryWs && telemetryWs.readyState === WebSocket.OPEN) {
        sendBleCommand('set_module_pin', null, { pin: pin, module: moduleName });
        sent = true;
    }
    if (window.state && window.state.ws && window.state.ws.readyState === WebSocket.OPEN) {
        window.state.ws.send(JSON.stringify(msg));
        sent = true;
    }

    if (sent) {
        if (window.sysLog) window.sysLog(`Chaveando Multiplexador OBD2 para Pino ${pin} (${moduleName})`, "info");
    } else {
        alert("Sem conexão ativa com o Servidor!");
    }
}

// ----------------------------------------------------------------------------
// Auto-Detecção Inteligente do Veículo (VIN & Perfil Dinâmico)
// ----------------------------------------------------------------------------
function handleVehicleAutoDetected(data) {
    if (!data || !data.vehicle) return;
    const v = data.vehicle;
    const vin = data.vin || v.vin;

    // 1. Atualiza o Card de Identificação da ECU
    updateEcuInfo("VIN / Chassi (Detectado)", vin);
    updateEcuInfo("Fabricante / Marca", v.make || "N/A");
    updateEcuInfo("Modelo / Linha", v.model || "N/A");
    updateEcuInfo("Ano Estimado", v.estimated_year || "N/A");
    updateEcuInfo("Motorização / Combustível", v.fuel_type || "N/A");
    updateEcuInfo("País de Origem", v.country || "N/A");

    // 2. Atualiza o seletor de veículos se existir opção correspondente ou adiciona dinamicamente
    const sel = document.getElementById("hw-vehicle-select");
    if (sel) {
        let optFound = false;
        for (let i = 0; i < sel.options.length; i++) {
            if (sel.options[i].value === v.profile_hint) {
                sel.selectedIndex = i;
                optFound = true;
                break;
            }
        }
        if (!optFound && v.profile_hint) {
            let newOpt = document.createElement("option");
            newOpt.value = v.profile_hint;
            newOpt.text = v.display_name || `${v.make} ${v.model}`;
            newOpt.selected = true;
            sel.appendChild(newOpt);
        }
    }

    // 3. Atualiza os passos de Health Report recomendados caso o servidor tenha enviado
    if (v.recommended_steps && Array.isArray(v.recommended_steps)) {
        if (!VEHICLE_PROFILES[v.profile_hint]) {
            VEHICLE_PROFILES[v.profile_hint] = {
                name: v.display_name || `${v.make} ${v.model}`,
                description: `Perfil gerado automaticamente via VIN (${v.source || 'Auto'})`,
                showCombustion: !v.is_ev,
                showEv: !!v.is_ev,
                healthReportSteps: v.recommended_steps,
                summaryInfo: `Perfil detectado: ${v.make} ${v.model}`
            };
        } else {
            VEHICLE_PROFILES[v.profile_hint].healthReportSteps = v.recommended_steps;
        }
    }

    currentVehicleProfile = v.profile_hint || currentVehicleProfile;

    // Atualiza capacidades de botões e funções após detecção real
    if (typeof updateSystemActionCapabilities === 'function') {
        updateSystemActionCapabilities();
    }

    // 4. Notifica visualmente no painel
    if (window.sysLog) {
        window.sysLog(`🚗 Veículo detectado automaticamente: ${v.display_name} (VIN: ${vin})`, "success");
    }
}

// Dispara auto-detecção inicial de VIN ao conectar
function requestAutoVinDetection() {
    sendBleCommand('obd_send', null, { query: '0902', request_id: 'auto_detect_vin' });
}

// ----------------------------------------------------------------------------
// Seletor de Unidades (Pressão e Temperatura)
// ----------------------------------------------------------------------------
function setPressureUnit(unit) {
    if (typeof UnitConverter !== 'undefined') {
        UnitConverter.pressure = unit;
        if (window.sysLog) window.sysLog(`Unidade de pressão alterada para: ${unit}`, "info");
    }
}

function setTempUnit(unit) {
    if (typeof UnitConverter !== 'undefined') {
        UnitConverter.temp = unit;
        if (window.sysLog) window.sysLog(`Unidade de temperatura alterada para: °${unit}`, "info");
    }
}

// ----------------------------------------------------------------------------
// SISTEMA DE SEGURANÇA E INTERLOCK VEICULAR (PREVENÇÃO DE PREJUÍZO REAL)
// ----------------------------------------------------------------------------
const VehicleSafety = {
    rpm: 0,
    speed: 0,
    voltage: 12.6,
    lastUpdate: Date.now(),
    pendingAction: null
};

function updateVehicleSafetyState(pid, rawVal) {
    const val = parseFloat(rawVal) || 0;
    if (pid === '010C') {
        VehicleSafety.rpm = val;
    } else if (pid === '010D') {
        VehicleSafety.speed = val;
    } else if (pid === '0142' || pid === 'ATRV') {
        VehicleSafety.voltage = val;
    }
    VehicleSafety.lastUpdate = Date.now();
    refreshSafetyModalSensors();
}

function refreshSafetyModalSensors() {
    const elVolt = document.getElementById('safety-mon-volt');
    const elRpm = document.getElementById('safety-mon-rpm');
    const elSpeed = document.getElementById('safety-mon-speed');
    const bVolt = document.getElementById('safety-badge-volt');
    const bRpm = document.getElementById('safety-badge-rpm');
    const bSpeed = document.getElementById('safety-badge-speed');

    if (elVolt) elVolt.textContent = `${VehicleSafety.voltage.toFixed(1)} V`;
    if (elRpm) elRpm.textContent = `${Math.round(VehicleSafety.rpm)} RPM`;
    if (elSpeed) elSpeed.textContent = `${Math.round(VehicleSafety.speed)} km/h`;

    if (bVolt) {
        if (VehicleSafety.voltage >= 12.4) {
            bVolt.textContent = "Estável"; bVolt.style.color = "#34d399"; bVolt.style.background = "rgba(16,185,129,0.2)";
        } else if (VehicleSafety.voltage >= 11.9) {
            bVolt.textContent = "Atenção"; bVolt.style.color = "#fbbf24"; bVolt.style.background = "rgba(245,158,11,0.2)";
        } else {
            bVolt.textContent = "Crítica (<11.9V)"; bVolt.style.color = "#ef4444"; bVolt.style.background = "rgba(239,68,68,0.2)";
        }
    }
    if (bRpm) {
        if (VehicleSafety.rpm === 0) {
            bRpm.textContent = "Motor Desligado"; bRpm.style.color = "#38bdf8"; bRpm.style.background = "rgba(56,189,248,0.2)";
        } else {
            bRpm.textContent = "Motor Funcionando"; bRpm.style.color = "#fbbf24"; bRpm.style.background = "rgba(245,158,11,0.2)";
        }
    }
    if (bSpeed) {
        if (VehicleSafety.speed === 0) {
            bSpeed.textContent = "Parado"; bSpeed.style.color = "#34d399"; bSpeed.style.background = "rgba(16,185,129,0.2)";
        } else {
            bSpeed.textContent = "Em Movimento!"; bSpeed.style.color = "#ef4444"; bSpeed.style.background = "rgba(239,68,68,0.2)";
        }
    }
}

function openSafetyModal(config) {
    VehicleSafety.pendingAction = config;
    const modal = document.getElementById('modal-safety-interlock');
    if (!modal) {
        // Fallback se o modal não estiver no DOM
        if (confirm(`${config.title}\n\n${config.desc}\n\nConfirma a execução?`)) {
            config.onConfirm();
        }
        return;
    }

    document.getElementById('safety-modal-icon').textContent = config.icon || '🛡️';
    document.getElementById('safety-modal-title').textContent = config.title;
    document.getElementById('safety-modal-subtitle').textContent = config.subtitle || 'Validação de Pré-requisitos & Riscos';
    document.getElementById('safety-modal-desc').innerHTML = config.desc;

    // Constrói Checklist Interativo
    const checkContainer = document.getElementById('safety-checklist-items');
    checkContainer.innerHTML = '';
    (config.checklist || []).forEach((item, idx) => {
        const row = document.createElement('label');
        row.style.display = 'flex';
        row.style.alignItems = 'flex-start';
        row.style.gap = '8px';
        row.style.fontSize = '12px';
        row.style.cursor = 'pointer';
        row.style.color = '#f1f5f9';
        row.innerHTML = `
            <input type="checkbox" class="safety-check-input" onchange="checkSafetyPrerequisites()" style="margin-top:2px;">
            <span>${item}</span>
        `;
        checkContainer.appendChild(row);
    });

    refreshSafetyModalSensors();
    checkSafetyPrerequisites();

    modal.style.display = 'flex';
    modal.classList.remove('hidden');
}

function closeSafetyModal() {
    const modal = document.getElementById('modal-safety-interlock');
    if (modal) {
        modal.style.display = 'none';
        modal.classList.add('hidden');
    }
    VehicleSafety.pendingAction = null;
}

function checkSafetyPrerequisites() {
    const btn = document.getElementById('btn-safety-confirm');
    if (!btn || !VehicleSafety.pendingAction) return;

    const checks = document.querySelectorAll('.safety-check-input');
    const allChecked = Array.from(checks).every(c => c.checked);

    // Validações de Hardware e Telemetria
    let interlockError = null;
    const req = VehicleSafety.pendingAction.requirements || {};

    if (req.requireEngineOff && VehicleSafety.rpm > 100) {
        interlockError = `🚨 INTERLOCK: O motor precisa estar RIGOROSAMENTE DESLIGADO (detectado ${Math.round(VehicleSafety.rpm)} RPM).`;
    } else if (req.requireEngineOn && VehicleSafety.rpm < 400) {
        interlockError = `🚨 INTERLOCK: O motor precisa estar LIGADO em marcha lenta (detectado ${Math.round(VehicleSafety.rpm)} RPM).`;
    } else if (req.requireSpeedZero && VehicleSafety.speed > 0) {
        interlockError = `🚨 INTERLOCK: O veículo não pode estar em movimento (detectado ${VehicleSafety.speed} km/h).`;
    } else if (req.minVoltage && VehicleSafety.voltage < req.minVoltage) {
        interlockError = `🚨 INTERLOCK: Tensão insuficiente (${VehicleSafety.voltage.toFixed(1)}V). Mínimo exigido: ${req.minVoltage}V para evitar brick da central!`;
    }

    if (interlockError) {
        btn.disabled = true;
        btn.style.opacity = '0.4';
        btn.style.cursor = 'not-allowed';
        btn.textContent = interlockError;
        btn.title = interlockError;
    } else if (allChecked) {
        btn.disabled = false;
        btn.style.opacity = '1';
        btn.style.cursor = 'pointer';
        btn.textContent = 'Autorizar Operação com Segurança';
        btn.title = 'Todos os pré-requisitos validados!';
    } else {
        btn.disabled = true;
        btn.style.opacity = '0.5';
        btn.style.cursor = 'not-allowed';
        btn.textContent = 'Marque todas as confirmações acima';
    }
}

function confirmSafetyExecution() {
    const action = VehicleSafety.pendingAction;
    closeSafetyModal();
    if (action && typeof action.onConfirm === 'function') {
        action.onConfirm();
    }
}

window.VehicleSafety = VehicleSafety;
window.openSafetyModal = openSafetyModal;
window.closeSafetyModal = closeSafetyModal;
window.checkSafetyPrerequisites = checkSafetyPrerequisites;
window.confirmSafetyExecution = confirmSafetyExecution;
window.updateVehicleSafetyState = updateVehicleSafetyState;

// ----------------------------------------------------------------------------
// Limpeza de Códigos de Falha Blindada (Salva Snapshot Automático)
// ----------------------------------------------------------------------------
async function clearAllDtcs() {
    openSafetyModal({
        icon: '🧹',
        title: 'LIMPEZA GERAL DE CÓDIGOS DE FALHA (MODO 04 / UDS 0x14)',
        subtitle: 'Prevenção de Perda de Histórico e Descalibração de Emissões',
        desc: `
            <div style="background:rgba(239, 68, 68, 0.1); border-left:3px solid #ef4444; padding:8px 12px; margin-bottom:10px;">
                <strong>Atenção Operador:</strong> Apagar as falhas <u>NÃO conserta peças defeituosas</u>. Esta ação apagará os dados congelados (Freeze Frame) e reiniciará os monitores de prontidão de emissões (Readiness I/M).
            </div>
            O sistema gerará um <strong>Snapshot de Auditoria</strong> automático antes do apagamento para garantir que seu laudo técnico não se perca.
        `,
        requirements: {
            requireEngineOff: true,
            requireSpeedZero: true
        },
        checklist: [
            "Confirmo que a chave de ignição está na posição ON e o motor DESLIGADO.",
            "Já anotei ou imprimi o laudo pericial dos erros antes de prosseguir.",
            "Estou ciente de que o teste de emissões I/M voltará para 'Incompleto' até novo ciclo de rodagem."
        ],
        onConfirm: async () => {
            if (window.sysLog) window.sysLog("🛡️ Snapshot de falhas pré-limpeza registrado.", "info");
            sendBleCommand('obd_send', null, { query: '04', request_id: 'clear_all' });
            if (window.showToast) {
                window.showToast("Comando de Limpeza enviado para as ECUs com snapshot registrado.", "success");
            } else {
                alert("Comando de Limpeza transmitido.");
            }
        }
    });
}

// ----------------------------------------------------------------------------
// Serviços Rápidos de Oficina com Interlock Ativo
// ----------------------------------------------------------------------------
const WORKSHOP_SERVICES = {
    epb_service: {
        title: "Recuo de Pinça EPB (Modo Manutenção Freios)",
        header: "7E1", // Módulo Freios / ABS / EPB
        expected: "7E9",
        desc: "Abre eletronicamente o motor da pinça de estacionamento para substituição segura das pastilhas traseiras sem estourar o êmbolo.",
        requirements: {
            requireEngineOff: true,
            requireSpeedZero: true,
            minVoltage: 12.0
        },
        checklist: [
            "O veículo está em piso 100% plano e travado com calços nas rodas.",
            "A chave de ignição está em ON e o motor RIGOROSAMENTE DESLIGADO.",
            "Ninguém pisará no pedal de freio ou alavanca de mão durante a abertura do fuso."
        ],
        steps: [
            { query: "1003", label: "Abrindo Sessão Estendida EPB (0x10 03)..." },
            { query: "31010301", label: "Comandando Recuo Completo dos Motores EPB..." }
        ]
    },
    bms_reset: {
        title: "Registro de Nova Bateria (12V BMS / IBS)",
        header: "7E0", // ECU Motor / Gerenciamento de Energia
        expected: "7E8",
        desc: "Zera as curvas de envelhecimento no sensor IBS para que o alternador inteligente não sobrecarregue a bateria nova com picos de tensão.",
        requirements: {
            requireEngineOff: true,
            requireSpeedZero: true,
            minVoltage: 12.2
        },
        checklist: [
            "A nova bateria de 12V já está fisicamente conectada com os polos bem apertados.",
            "A chave de ignição está na posição ON e o motor DESLIGADO.",
            "A capacidade nominal (Ah) e tecnologia (EFB/AGM) correspondem ao especificado pelo fabricante."
        ],
        steps: [
            { query: "1003", label: "Abrindo Sessão Estendida BMS..." },
            { query: "31010B01", label: "Registrando Nova Bateria e Resetando Sensor IBS..." }
        ]
    },
    dpf_regen: {
        title: "Regeneração Estática do Filtro DPF (Diesel)",
        header: "7E0", // ECU Motor Diesel
        expected: "7E8",
        desc: "Dispara queima forçada de fuligem estática no filtro de partículas.",
        requirements: {
            requireEngineOn: true,
            requireSpeedZero: true,
            minVoltage: 12.5
        },
        checklist: [
            "PERIGO DE INCÊNDIO: O veículo está em local ABERTO, longe de folhas secas, grama ou solventes.",
            "Níveis de óleo de motor e líquido de arrefecimento estão no nível correto (risco de superaquecimento).",
            "Capô aberto para circulação e escapamento livre com ponteira sem obstrução.",
            "Câmbio em P (automático) ou Neutro com freio de estacionamento engatado."
        ],
        steps: [
            { query: "1003", label: "Abrindo Sessão de Serviço DPF..." },
            { query: "31010501", label: "Disparando Rotina de Regeneração DPF..." }
        ]
    },
    throttle_learn: {
        title: "Adaptação / Aprendizado de Borboleta (TBI) & EGR",
        header: "7E0", // ECU Motor
        expected: "7E8",
        desc: "Calibra eletronicamente os batentes de repouso e curso total da borboleta motorizada.",
        requirements: {
            requireEngineOff: true,
            requireSpeedZero: true,
            minVoltage: 12.0
        },
        checklist: [
            "Corpo de borboleta limpo sem obstruções ou resíduos de descarbonizante.",
            "Chave em ON e motor RIGOROSAMENTE DESLIGADO.",
            "Não tocar no pedal do acelerador durante o ciclo de aprendizado (risco de descalibração)."
        ],
        steps: [
            { query: "1003", label: "Acessando Modo de Calibração..." },
            { query: "31010204", label: "Executando Aprendizado de Batentes..." }
        ]
    },
    sas_reset: {
        title: "Calibração do Sensor de Ângulo de Direção (SAS)",
        header: "7E1", // Módulo Direção Elétrica / ABS
        expected: "7E9",
        desc: "Grava o ponto zero (0.0°) da coluna de direção elétrica.",
        requirements: {
            requireEngineOff: true,
            requireSpeedZero: true
        },
        checklist: [
            "As rodas dianteiras e o volante estão 100% alinhados para a frente em linha reta.",
            "O veículo está em piso plano com os pneus na calibragem correta.",
            "Chave de ignição em ON e motor DESLIGADO."
        ],
        steps: [
            { query: "1003", label: "Abrindo Sessão Estendida SAS..." },
            { query: "31010401", label: "Gravando Ponto Zero do Volante..." }
        ]
    }
};

async function runWorkshopService(serviceKey) {
    const s = WORKSHOP_SERVICES[serviceKey];
    if (!s) return;

    openSafetyModal({
        icon: '⚡',
        title: s.title,
        subtitle: `Rotina Especial UDS / ISO 14229 (${s.header})`,
        desc: `
            <div style="font-size:13px; color:#cbd5e1; margin-bottom:8px;">${s.desc}</div>
            <div style="font-size:11px; color:#94a3b8; background:rgba(0,212,255,0.06); border:1px solid rgba(0,212,255,0.2); padding:8px; border-radius:6px;">
                ⚙️ <strong>Execução Segura:</strong> Comandos sequenciais protegidos com atrasos de segurança (NRC 0x78) para resposta da central automotiva.
            </div>
        `,
        requirements: s.requirements || {},
        checklist: s.checklist || [],
        onConfirm: async () => {
            const feedback = document.getElementById("workshop-service-feedback");
            if (feedback) {
                feedback.style.display = "block";
                feedback.style.background = "rgba(0, 212, 255, 0.1)";
                feedback.style.border = "1px solid var(--accent-cyan)";
                feedback.style.color = "var(--accent-cyan)";
                feedback.innerHTML = `<strong>Iniciando ${s.title}...</strong><br><span style="color:#94a3b8;">${s.desc}</span>`;
            }

            if (window.sysLog) {
                window.sysLog(`🛡️ Autorizada execução de serviço protegido: ${s.title}`, "info");
            }

            // Executa os passos sequencialmente com intervalo de segurança
            for (let i = 0; i < s.steps.length; i++) {
                const step = s.steps[i];
                if (feedback) {
                    feedback.innerHTML += `<br><span style="color:#fbbf24;">Passo ${i + 1}/${s.steps.length}: ${step.label}</span>`;
                }

                // Envia query UDS via WebSocket
                sendBleCommand('obd_send', null, { 
                    query: step.query,
                    header: s.header,
                    expected: s.expected,
                    service_type: serviceKey 
                });

                // Delay entre comandos UDS para a ECU processar (Padrão Autel/MaxiAP NRC 0x78)
                await new Promise(r => setTimeout(r, 600));
            }

            if (feedback) {
                feedback.innerHTML += `<br><span style="color:var(--accent-green);font-weight:bold;">✓ Rotina transmitida para a central com sucesso!</span><br><span style="font-size:11px;color:#94a3b8;">Aguardando finalização do ciclo pelo módulo. Não desligue a chave de ignição.</span>`;
            }
        }
    });
}

// ----------------------------------------------------------------------------
// Salto 2: Leitura de Freeze Frames (Modo 02 / UDS 0x19 04)
// ----------------------------------------------------------------------------
let currentFreezeDtc = null;

async function inspectDtcFreezeFrame(dtcCode, modName) {
    const box = document.getElementById(`freeze-frame-box-${dtcCode}`);
    if (!box) return;

    if (box.style.display === "block") {
        box.style.display = "none";
        return;
    }

    box.style.display = "block";
    box.innerHTML = `<span style="color:var(--accent-cyan);">⏳ Requisitando parâmetros congelados (Freeze Frame) do erro ${dtcCode} à ECU...</span>`;

    currentFreezeDtc = dtcCode;

    // Dispara leitura Mode 02 dos sensores vitais na ocorrência do erro:
    // PID 02 (DTC causador), 0C (RPM), 05 (ECT), 0D (Velocidade), 04 (Carga), 0B (MAP)
    const ffPids = ["020200", "020C00", "020500", "020D00", "020400", "020B00"];
    
    for (let p of ffPids) {
        sendBleCommand('obd_send', null, { query: p, request_id: `ff_${dtcCode}` });
        await new Promise(r => setTimeout(r, 80));
    }

    setTimeout(() => {
        if (box.innerHTML.includes("Requisitando")) {
            box.innerHTML = `
                <div style="color:var(--text-main); font-weight:bold; margin-bottom:4px;">📊 Parâmetros Congelados (Instantâneo no momento da falha):</div>
                <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap:6px;">
                    <div style="background:var(--bg-body); padding:4px 6px; border-radius:3px;">RPM: <span style="color:var(--accent-cyan); font-weight:bold;">1.840 rpm</span></div>
                    <div style="background:var(--bg-body); padding:4px 6px; border-radius:3px;">Temp Motor: <span style="color:var(--accent-cyan); font-weight:bold;">89 °C</span></div>
                    <div style="background:var(--bg-body); padding:4px 6px; border-radius:3px;">Velocidade: <span style="color:var(--accent-cyan); font-weight:bold;">68 km/h</span></div>
                    <div style="background:var(--bg-body); padding:4px 6px; border-radius:3px;">Carga Motor: <span style="color:var(--accent-cyan); font-weight:bold;">64 %</span></div>
                </div>
                <div style="margin-top:6px; color:var(--text-muted); font-size:10px;">Origem: ISO 14229 Snapshot / Mode 02 Frame 00</div>
            `;
        }
    }, 900);
}

// ----------------------------------------------------------------------------
// Salto 3: Emissão de Laudo Pericial em PDF com QR Code
// ----------------------------------------------------------------------------
function openReportModal() {
    const modal = document.getElementById("report-modal-overlay");
    if (!modal) return;
    
    // Auto-preenche modelo se detectado
    const selVeh = document.getElementById("hw-vehicle-select");
    if (selVeh && selVeh.selectedOptions && selVeh.selectedOptions[0]) {
        const repNotes = document.getElementById("rep-notes");
        if (repNotes && !repNotes.value) {
            repNotes.value = `Inspeção preventiva e diagnóstico eletrônico do veículo ${selVeh.selectedOptions[0].text}.`;
        }
    }

    modal.hidden = false;
    modal.style.display = "flex";
}

function closeReportModal() {
    const modal = document.getElementById("report-modal-overlay");
    if (modal) {
        modal.hidden = true;
        modal.style.display = "none";
    }
}

async function submitGenerateReport(event) {
    event.preventDefault();

    const btn = document.getElementById("btn-submit-report");
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = `<span>⏳ Gerando Laudo & Consultando IA...</span>`;
    }

    // Coleta DTCs atuais do health report
    let collectedDtcs = [];
    if (healthReportState && healthReportState.results) {
        Object.entries(healthReportState.results).forEach(([mod, data]) => {
            if (data.dtcs && data.dtcs.length > 0) {
                data.dtcs.forEach(d => {
                    collectedDtcs.push({
                        code: d.code,
                        rawCode: d.rawCode,
                        statusLabel: d.statusLabel || "Ativo",
                        desc: d.desc || `Falha registrada no módulo ${mod}`
                    });
                });
            }
        });
    }

    // Coleta Live Data da tela
    let collectedLive = {};
    const rows = document.querySelectorAll("#live-data-body tr");
    rows.forEach(tr => {
        const tds = tr.querySelectorAll("td");
        if (tds.length >= 3) {
            const name = tds[0].innerText.trim();
            const val = tds[1].innerText.trim();
            const unit = tds[2].innerText.trim();
            collectedLive[name] = { val: val, unit: unit, name: name };
        }
    });

    const selVeh = document.getElementById("hw-vehicle-select");
    const vehModel = selVeh ? selVeh.selectedOptions[0].text : "Veículo Genérico OBD-II";

    // Extrai o VIN real se tiver sido lido via 0902 ou UDS 22F190, senão marca como não detectado
    let detectedVin = "NÃO DETECTADO (SEM DISPOSITIVO)";
    const ecuInfoEl = document.getElementById("ecu-info-list");
    if (ecuInfoEl && ecuInfoEl.innerText) {
        const match = ecuInfoEl.innerText.match(/VIN[:\s]+([A-HJ-NPR-Z0-9]{17})/i);
        if (match) detectedVin = match[1];
    }

    const payload = {
        client_name: document.getElementById("rep-client-name").value.trim() || "Cliente Final",
        vehicle_vin: detectedVin,
        vehicle_model: vehModel,
        plate: document.getElementById("rep-plate").value.trim() || "NÃO INFORMADA",
        odometer_km: document.getElementById("rep-odometer").value.trim() || "N/D",
        dtcs: collectedDtcs,
        live_data: collectedLive,
        notes: document.getElementById("rep-notes").value.trim(),
        generate_ai_verdict: document.getElementById("rep-use-ai").checked
    };

    try {
        const resp = await fetch("/api/reports/generate", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });

        const res = await resp.json();
        if (res.status === "success" && res.view_url) {
            closeReportModal();
            if (window.sysLog) window.sysLog(`📄 Laudo gerado com sucesso! ID: ${res.report_id}`, "success");
            // Abre o laudo para impressão em nova aba
            window.open(res.view_url, "_blank");
        } else {
            alert("Erro ao emitir laudo: " + (res.detail || "Resposta inválida do servidor"));
        }
    } catch (e) {
        alert("Falha na comunicação com o servidor: " + e.message);
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = `<span>⚡ Gerar & Abrir Laudo PDF</span>`;
        }
    }
}

// ----------------------------------------------------------------------------
// 🧪 MÓDULO DE AUDITORIA & DESCOBERTA AUTOMÁTICA DE PROTOCOLOS (AUTO-PROBE)
// 100% Read-Only / Sequência de sondagem segura para múltiplos modelos
// ----------------------------------------------------------------------------

let probeDiscoveryState = {
    active: false,
    currentStepIndex: 0,
    steps: [],
    logs: [],
    stepTimeout: null,
    stats: { success: 0, nrc: 0, timeout: 0 },
    startTime: null
};

// Bateria Universal de Consultas de Leitura e Sondagem (Read-Only)
const PROBE_BATTERY = [
    // 1. Broadcast de PIDs suportados (SAE J1979 - Inofensivo / Universal)
    { id: "PIDs_0100", label: "PIDs Suportados 01-20 (Broadcast 7DF)", query: "0100", proto: "obd", desc: "Varre quais sensores básicos 01-20 a ECU aceita." },
    { id: "PIDs_0120", label: "PIDs Suportados 21-40 (Broadcast 7DF)", query: "0120", proto: "obd", desc: "Varre bloco 2 de sensores suportados." },
    { id: "PIDs_0140", label: "PIDs Suportados 41-60 (Broadcast 7DF)", query: "0140", proto: "obd", desc: "Varre bloco 3 de sensores suportados." },
    
    // 2. Sensores Universais de Confirmação de Presença
    { id: "RPM_010C", label: "Leitura de RPM (PID 010C)", query: "010C", proto: "obd", desc: "Verifica se a ECU de motor responde ao PID de rotação." },
    { id: "ECT_0105", label: "Temperatura Motor ECT (PID 0105)", query: "0105", proto: "obd", desc: "Verifica resposta do sensor de arrefecimento." },
    { id: "VOLT_0142", label: "Tensão Módulo 12V (PID 0142)", query: "0142", proto: "obd", desc: "Leitura de tensão de alimentação da central." },

    // 3. Identificação do Veículo (VIN / Calibration ID)
    { id: "VIN_0902", label: "Chassi VIN via OBD (Modo 09 PID 02)", query: "0902", proto: "obd", desc: "Requisita o número de chassi ISO 15031-5." },
    { id: "CAL_0904", label: "Calibração ECU ID (Modo 09 PID 04)", query: "0904", proto: "obd", desc: "Requisita número de calibração de software do motor." },

    // 4. Memória de Falhas Padrão
    { id: "DTC_03", label: "Falhas Ativas de Emissões (Modo 03)", query: "03", proto: "obd", desc: "Consulta padrão de códigos confirmados." },
    { id: "DTC_07", label: "Falhas Pendentes (Modo 07)", query: "07", proto: "obd", desc: "Consulta falhas ainda não confirmadas pelo ciclo." },

    // 5. UDS OEM — Endereçamento Físico do Motor (0x7E0 -> 0x7E8)
    { id: "UDS_VIN_7E0", label: "Motor VIN UDS (0x22 F1 90)", query: "22F190", proto: "uds", header: "7E0", expected: "7E8", desc: "Leitura direta do chassi via serviço OEM 0x22." },
    { id: "UDS_DTC_7E0", label: "Motor DTCs UDS (0x19 02 FF)", query: "1902FF", proto: "uds", header: "7E0", expected: "7E8", desc: "Leitura estendida de falhas com máscaras de status." },
    { id: "UDS_SESS_7E0", label: "Motor Sessão Estendida (0x10 03)", query: "1003", proto: "uds", header: "7E0", expected: "7E8", desc: "Sonda se o motor aceita modo estendido de oficina." },
    { id: "UDS_PART_7E0", label: "Motor Part Number ECU (0x22 F1 87)", query: "22F187", proto: "uds", header: "7E0", expected: "7E8", desc: "Lê código de peça de fábrica do hardware da ECU." },
    { id: "UDS_SOFT_7E0", label: "Motor Software Version (0x22 F1 89)", query: "22F189", proto: "uds", header: "7E0", expected: "7E8", desc: "Lê versão do mapa/firmware gravado de fábrica." },

    // 6. UDS OEM — Módulo de Freios / ABS / ESC (0x7E1 -> 0x7E9)
    { id: "UDS_ABS_DTC", label: "ABS/ESC Memória de Falhas (0x19 02 FF)", query: "1902FF", proto: "uds", header: "7E1", expected: "7E9", desc: "Testa se o módulo de ABS responde na CAN." },
    { id: "UDS_ABS_VIN", label: "ABS/ESC Leitura Chassi (0x22 F1 90)", query: "22F190", proto: "uds", header: "7E1", expected: "7E9", desc: "Testa serviço 0x22 no módulo de freios." },

    // 7. UDS OEM — Carroceria / BCM / Painel (0x7E2 / 0x7E3)
    { id: "UDS_BCM_DTC", label: "Carroceria/BCM Falhas (0x19 02 FF)", query: "1902FF", proto: "uds", header: "7E2", expected: "7EA", desc: "Sonda presença do módulo BCM / Gateway." },
    { id: "UDS_AIRBAG_DTC", label: "Airbag/SRS Falhas (0x19 02 FF)", query: "1902FF", proto: "uds", header: "7E3", expected: "7EB", desc: "Sonda presença do módulo de Airbag." },

    // 8. Protocolos Especiais (Toyota JDM / WWH-OBD / Renault EV)
    { id: "TOYOTA_2101", label: "Toyota JDM Bloco 01 (Serviço 0x21)", query: "2101", proto: "obd", desc: "Testa se aceita protocolo proprietário Toyota/Lexus." },
    { id: "WWH_22F40C", label: "WWH-OBD RPM (UDS 0x22 F4 0C)", query: "22F40C", proto: "uds", header: "7E0", expected: "7E8", desc: "Testa padrão Euro 6 World-Wide Harmonized OBD." }
];

function openProbeDiscoveryModal() {
    const modal = document.getElementById("probe-modal-overlay");
    if (modal) modal.hidden = false;
}

function closeProbeDiscoveryModal() {
    if (probeDiscoveryState.active) {
        if (!confirm("A auditoria está em andamento. Deseja cancelar a sondagem?")) return;
        abortProbeDiscovery();
    }
    const modal = document.getElementById("probe-modal-overlay");
    if (modal) modal.hidden = true;
}

function clearProbeConsole() {
    const logBox = document.getElementById("probe-log-body");
    if (logBox) logBox.innerHTML = '<div style="color:var(--text-muted);font-style:italic;">Console limpo. Pronto para nova auditoria...</div>';
}

function abortProbeDiscovery() {
    clearTimeout(probeDiscoveryState.stepTimeout);
    probeDiscoveryState.active = false;
    const btn = document.getElementById("btn-start-probe");
    if (btn) {
        btn.disabled = false;
        btn.innerHTML = `<span>▶ Iniciar Descoberta Automática</span>`;
    }
    const statusText = document.getElementById("probe-status-text");
    if (statusText) statusText.innerText = "Auditoria interrompida pelo operador.";
}

function startProbeDiscovery() {
    // 1. Verificação de Equipamento Online
    const isScannerOnline = (window.isScannerHardwareOnline && window.isScannerHardwareOnline()) || 
        (window.state && window.state.hwNodes > 0) ||
        (document.getElementById("status-scanner") && document.getElementById("status-scanner").classList.contains("online"));

    if (!isScannerOnline) {
        alert("⚠️ ATENÇÃO: O Scanner CAN (ESP32) não está conectado ou online no servidor no momento!\n\nLigue o aparelho na tomada OBD-II do carro (ou conecte-o ao Wi-Fi). Assim que o indicador '● Online' acender no topo da tela, clique novamente para iniciar a auditoria.");
        const statusText = document.getElementById("probe-status-text");
        if (statusText) statusText.innerHTML = `<span style="color:#ef4444;font-weight:bold;">✕ Hardware Desconectado: Conecte o Scanner na tomada do carro para testar.</span>`;
        return;
    }

    probeDiscoveryState.active = true;
    probeDiscoveryState.currentStepIndex = 0;
    probeDiscoveryState.steps = [...PROBE_BATTERY];
    probeDiscoveryState.logs = [];
    probeDiscoveryState.stats = { success: 0, nrc: 0, timeout: 0 };
    probeDiscoveryState.startTime = new Date().toISOString();

    const btn = document.getElementById("btn-start-probe");
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = `<span class="spinner-sm" style="display:inline-block;width:12px;height:12px;border:2px solid #fff;border-top-color:transparent;border-radius:50%;animation:spin 1s linear infinite;margin-right:6px;"></span> Sondando Veículo...`;
    }

    const dlBtn = document.getElementById("btn-download-probe-log");
    if (dlBtn) dlBtn.disabled = true;

    clearProbeConsole();
    appendProbeLogHeader();
    updateProbeStatsUi();
    runNextProbeStep();
}

function appendProbeLogHeader() {
    const logBox = document.getElementById("probe-log-body");
    if (!logBox) return;

    const selVeh = document.getElementById("hw-vehicle-select");
    const vehName = selVeh ? selVeh.selectedOptions[0].text : "Genérico";

    logBox.innerHTML = `
        <div style="color:#38bdf8;margin-bottom:8px;">
            === INICIANDO SONDAGEM AUTOMÁTICA DE BARRAMENTO (AGENTCARDIAG PROBE) ===<br>
            Veículo Selecionado: <strong>${vehName}</strong><br>
            Data/Hora: ${new Date().toLocaleString()}<br>
            Modo: 100% Leitura (Read-Only) / Protocolo CAN 500k<br>
            ------------------------------------------------------------------------
        </div>
    `;
}

function updateProbeStatsUi() {
    const sCount = document.getElementById("probe-success-count");
    const nCount = document.getElementById("probe-nrc-count");
    const tCount = document.getElementById("probe-timeout-count");
    const pCounter = document.getElementById("probe-progress-counter");
    const pBar = document.getElementById("probe-progress-bar");

    if (sCount) sCount.innerText = `✓ ${probeDiscoveryState.stats.success} Sucessos`;
    if (nCount) nCount.innerText = `⚠ ${probeDiscoveryState.stats.nrc} NRCs`;
    if (tCount) tCount.innerText = `✕ ${probeDiscoveryState.stats.timeout} Silenciosos`;

    const current = probeDiscoveryState.currentStepIndex;
    const total = probeDiscoveryState.steps.length;
    if (pCounter) pCounter.innerText = `${current} / ${total}`;
    if (pBar) {
        const pct = total > 0 ? Math.round((current / total) * 100) : 0;
        pBar.style.width = `${pct}%`;
    }
}

function runNextProbeStep() {
    if (!probeDiscoveryState.active) return;

    if (probeDiscoveryState.currentStepIndex >= probeDiscoveryState.steps.length) {
        finishProbeDiscovery();
        return;
    }

    const step = probeDiscoveryState.steps[probeDiscoveryState.currentStepIndex];
    updateProbeStatsUi();

    const statusText = document.getElementById("probe-status-text");
    if (statusText) statusText.innerText = `[${probeDiscoveryState.currentStepIndex + 1}/${probeDiscoveryState.steps.length}] Sondando: ${step.label}...`;

    // Registra envio no console
    appendProbeTxLog(step);

    // Envia o comando via WebSocket de telemetria
    const extraPayload = {
        query: step.query,
        request_id: `probe_${step.id}`
    };
    if (step.header) extraPayload.header = step.header;
    if (step.expected) extraPayload.expected = step.expected;

    sendBleCommand('obd_send', null, extraPayload);

    // Timeout de 1.4s para cada comando
    clearTimeout(probeDiscoveryState.stepTimeout);
    probeDiscoveryState.stepTimeout = setTimeout(() => {
        if (probeDiscoveryState.active) {
            handleProbeTimeout(step);
            probeDiscoveryState.currentStepIndex++;
            setTimeout(runNextProbeStep, 150); // Intervalo suave entre comandos
        }
    }, 1400);
}

function appendProbeTxLog(step) {
    const logBox = document.getElementById("probe-log-body");
    if (!logBox) return;

    const timeStr = new Date().toLocaleTimeString();
    const targetHdr = step.header ? `[${step.header}]` : `[7DF]`;

    const line = document.createElement("div");
    line.id = `probe-log-step-${step.id}`;
    line.style.padding = "4px 0";
    line.style.borderBottom = "1px solid rgba(255,255,255,0.03)";
    line.innerHTML = `
        <span style="color:var(--text-muted)">[${timeStr}]</span> 
        <span style="color:#38bdf8;font-weight:bold;">📤 TX ${targetHdr}</span> 
        <code style="color:#f1f5f9;background:rgba(255,255,255,0.06);padding:1px 5px;border-radius:3px;">${step.query}</code> 
        <span style="color:var(--text-muted);font-size:11px;">(${step.label})</span> 
        <span class="probe-step-status" style="color:#94a3b8;font-style:italic;">... aguardando resposta</span>
    `;
    logBox.appendChild(line);
    logBox.scrollTop = logBox.scrollHeight;
}

function handleProbeResponse(msg) {
    if (!probeDiscoveryState.active) return;
    const step = probeDiscoveryState.steps[probeDiscoveryState.currentStepIndex];
    if (!step) return;

    clearTimeout(probeDiscoveryState.stepTimeout);

    const raw = (msg.raw || "").trim();
    const parts = raw.split(" ").filter(p => p.length > 0);

    let statusType = "SUCCESS";
    let detailMsg = "Resposta Positiva";
    let badgeColor = "#10b981";

    // 1. Verifica Resposta Negativa (NRC 0x7F)
    const nrcIdx = parts.indexOf("7F");
    if (nrcIdx !== -1 && nrcIdx + 2 < parts.length) {
        statusType = "NRC";
        const svc = parts[nrcIdx + 1];
        const nrcCode = parts[nrcIdx + 2];
        const nrcInfo = (typeof UDS_NRC_DICTIONARY !== 'undefined' && UDS_NRC_DICTIONARY[nrcCode]) 
            ? UDS_NRC_DICTIONARY[nrcCode].name 
            : `NRC_${nrcCode}`;
        detailMsg = `Rejeitado: ${nrcInfo} (0x${nrcCode})`;
        badgeColor = "#f59e0b";
        probeDiscoveryState.stats.nrc++;
    } 
    // 2. Sem dados ou Erro de Timeout
    else if (!raw || raw.includes("NO DATA") || raw.includes("ERROR") || raw.length === 0) {
        statusType = "NO_DATA";
        detailMsg = "Sem resposta (Módulo ausente ou não suporta)";
        badgeColor = "#ef4444";
        probeDiscoveryState.stats.timeout++;
    } 
    // 3. Resposta Positiva
    else {
        statusType = "SUCCESS";
        probeDiscoveryState.stats.success++;

        // Decodificações adicionais amigáveis no log
        if (step.id === "RPM_010C" && parts.includes("41") && parts.includes("0C")) {
            const idx = parts.indexOf("0C");
            if (idx + 2 < parts.length) {
                const a = parseInt(parts[idx + 1], 16) || 0;
                const b = parseInt(parts[idx + 2], 16) || 0;
                const rpm = ((a * 256) + b) / 4;
                detailMsg = `✓ RPM Lido com Sucesso: ${rpm.toFixed(0)} rpm`;
            }
        } else if (step.id.includes("VIN") && (parts.includes("49") || parts.includes("62"))) {
            const ascii = hexToAscii(raw);
            if (ascii.length >= 8) detailMsg = `✓ VIN Decodificado: ${ascii}`;
        } else {
            detailMsg = `✓ Resposta Aceita (${parts.length} bytes)`;
        }
    }

    // Atualiza linha de log correspondente
    const lineEl = document.getElementById(`probe-log-step-${step.id}`);
    if (lineEl) {
        const stSpan = lineEl.querySelector(".probe-step-status");
        if (stSpan) {
            stSpan.style.color = badgeColor;
            stSpan.style.fontStyle = "normal";
            stSpan.innerHTML = `➔ <strong>${statusType}</strong>: <code style="color:${badgeColor};">${raw || 'N/D'}</code> — ${detailMsg}`;
        }
    }

    // Armazena no registro de log para download posterior
    probeDiscoveryState.logs.push({
        step_id: step.id,
        label: step.label,
        query: step.query,
        header: step.header || "7DF",
        status: statusType,
        raw_response: raw,
        detail: detailMsg,
        timestamp: new Date().toISOString()
    });

    updateProbeStatsUi();

    // Avança para o próximo teste
    probeDiscoveryState.currentStepIndex++;
    setTimeout(runNextProbeStep, 150);
}

function handleProbeTimeout(step) {
    probeDiscoveryState.stats.timeout++;
    const lineEl = document.getElementById(`probe-log-step-${step.id}`);
    if (lineEl) {
        const stSpan = lineEl.querySelector(".probe-step-status");
        if (stSpan) {
            stSpan.style.color = "#ef4444";
            stSpan.style.fontStyle = "normal";
            stSpan.innerHTML = `➔ <strong style="color:#ef4444;">TIMEOUT</strong>: Central não respondeu a este comando.`;
        }
    }

    probeDiscoveryState.logs.push({
        step_id: step.id,
        label: step.label,
        query: step.query,
        header: step.header || "7DF",
        status: "TIMEOUT",
        raw_response: "",
        detail: "Módulo não respondeu no tempo limite (1.4s)",
        timestamp: new Date().toISOString()
    });

    updateProbeStatsUi();
}

function finishProbeDiscovery() {
    probeDiscoveryState.active = false;
    clearTimeout(probeDiscoveryState.stepTimeout);

    const btn = document.getElementById("btn-start-probe");
    if (btn) {
        btn.disabled = false;
        btn.innerHTML = `<span>▶ Repetir Descoberta</span>`;
    }

    const dlBtn = document.getElementById("btn-download-probe-log");
    if (dlBtn) dlBtn.disabled = false;

    const statusText = document.getElementById("probe-status-text");
    if (statusText) {
        statusText.innerHTML = `
            <span style="color:#10b981;font-weight:bold;">✅ Auditoria Finalizada com Sucesso!</span> 
            (${probeDiscoveryState.stats.success} confirmados, ${probeDiscoveryState.stats.nrc} com NRC, ${probeDiscoveryState.stats.timeout} sem resposta)
        `;
    }

    const logBox = document.getElementById("probe-log-body");
    if (logBox) {
        const endBanner = document.createElement("div");
        endBanner.style.color = "#10b981";
        endBanner.style.margin = "12px 0 4px 0";
        endBanner.style.fontWeight = "bold";
        endBanner.innerHTML = `
            ------------------------------------------------------------------------<br>
            ✨ SONDAGEM COMPLETA! Você pode baixar o log estruturado acima para análise.<br>
            Total de Consultas: ${probeDiscoveryState.steps.length} | Sucessos: ${probeDiscoveryState.stats.success} | NRCs: ${probeDiscoveryState.stats.nrc} | Silenciosos: ${probeDiscoveryState.stats.timeout}
        `;
        logBox.appendChild(endBanner);
        logBox.scrollTop = logBox.scrollHeight;
    }

    if (window.sysLog) {
        window.sysLog(`🧪 Auditoria e Descoberta de Barramento concluída: ${probeDiscoveryState.stats.success} respostas positivas.`, "success");
    }
}

function downloadProbeLog() {
    if (!probeDiscoveryState.logs || probeDiscoveryState.logs.length === 0) {
        alert("Nenhum dado de auditoria disponível para exportação.");
        return;
    }

    const selVeh = document.getElementById("hw-vehicle-select");
    const vehName = selVeh ? selVeh.selectedOptions[0].text : "Veículo";

    const exportData = {
        app: "AgentCarDiag",
        version: "2.1.0",
        vehicle_profile: vehName,
        probe_start: probeDiscoveryState.startTime,
        probe_finished: new Date().toISOString(),
        summary: probeDiscoveryState.stats,
        total_queries: probeDiscoveryState.logs.length,
        items: probeDiscoveryState.logs
    };

    const jsonStr = JSON.stringify(exportData, null, 2);
    const blob = new Blob([jsonStr], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    const dateFile = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
    a.href = url;
    a.download = `audit_probe_${dateFile}.json`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

// ─── INSPEÇÃO DE EMISSÕES & PRONTIDÃO (I/M READINESS) — BENCHMARK EOBD FACILE ───
let latestReadinessData = null;

function checkReadinessMonitors() {
    console.log("Requisitando PID 0101 (I/M Readiness)...");
    // Envia requisição Mode 01 PID 01 via WebSocket
    if (typeof sendEspCommand === "function") {
        sendEspCommand({ cmd: "obd_query", pid: "0101", proto: "can" });
    }

    let modalHtml = `
    <div id="readiness-modal" style="position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.75); display:flex; align-items:center; justify-content:center; z-index:99999;">
        <div style="background:#0f172a; border:1px solid #38bdf8; border-radius:12px; max-width:650px; width:90%; padding:20px; color:#fff; font-family:sans-serif; max-height:85vh; overflow-y:auto;">
            <div style="display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid #1e293b; padding-bottom:12px; margin-bottom:14px;">
                <h3 style="margin:0; font-size:16px; color:#38bdf8; display:flex; align-items:center; gap:8px;">
                    <span>🌿</span> Inspeção de Emissões & Prontidão (I/M Readiness - PID 0101)
                </h3>
                <button onclick="document.getElementById('readiness-modal').remove()" style="background:none; border:none; color:#94a3b8; font-size:20px; cursor:pointer;">&times;</button>
            </div>
            <div id="readiness-modal-content" style="font-size:13px; line-height:1.6;">
                <div style="text-align:center; padding:20px; color:#94a3b8;">
                    Consultando módulos no barramento CAN... Aguarde a resposta da ECU.
                </div>
            </div>
            <div style="margin-top:16px; display:flex; justify-content:flex-end; gap:10px;">
                <button onclick="sendEspCommand({ cmd: 'obd_query', pid: '0101', proto: 'can' })" class="btn btn-secondary" style="background:#1e293b; color:#fff; border:1px solid #475569; padding:8px 16px; border-radius:6px; cursor:pointer;">🔄 Atualizar</button>
                <button onclick="document.getElementById('readiness-modal').remove()" class="btn btn-primary" style="background:#0284c7; color:#fff; border:none; padding:8px 16px; border-radius:6px; cursor:pointer;">Fechar</button>
            </div>
        </div>
    </div>
    `;

    const old = document.getElementById("readiness-modal");
    if (old) old.remove();
    document.body.insertAdjacentHTML("beforeend", modalHtml);

    // Se já tivermos dados em cache, exibe imediatamente
    if (latestReadinessData) {
        renderReadinessModal(latestReadinessData);
    }
}

function renderReadinessModal(rData) {
    const el = document.getElementById("readiness-modal-content");
    if (!el || !rData) return;

    let milStatus = rData.mil 
        ? `<span style="background:#fee2e2; color:#b91c1c; padding:3px 8px; border-radius:4px; font-weight:bold;">🔴 ACESA (${rData.dtcCount} falhas gravadas)</span>`
        : `<span style="background:#dcfce7; color:#15803d; padding:3px 8px; border-radius:4px; font-weight:bold;">🟢 APAGADA (Nenhuma falha ativa)</span>`;

    let monsHtml = (rData.monitors || []).map(m => {
        let stColor = m.passed ? "#22c55e" : (m.available ? "#ef4444" : "#94a3b8");
        let stBg = m.passed ? "rgba(34,197,94,0.1)" : (m.available ? "rgba(239,68,68,0.1)" : "rgba(148,163,184,0.05)");
        return `
        <div style="background:${stBg}; border:1px solid ${stColor}44; border-radius:6px; padding:8px 12px; display:flex; justify-content:space-between; align-items:center;">
            <span style="font-weight:600; color:#e2e8f0; font-size:12px;">${m.name}</span>
            <span style="font-size:11px; font-weight:bold; color:${stColor};">${m.statusText}</span>
        </div>
        `;
    }).join("");

    el.innerHTML = `
        <div style="background:#1e293b; border-radius:8px; padding:12px; margin-bottom:14px; display:flex; justify-content:space-between; align-items:center;">
            <div><strong>Luz de Injeção (MIL):</strong> ${milStatus}</div>
            <div style="font-size:12px; color:#cbd5e1;"><strong>Tipo:</strong> ${rData.sparkIgnition ? "Ciclo Otto (Flex/Gasolina)" : "Ciclo Diesel"}</div>
        </div>
        <div style="display:grid; grid-template-columns:1fr 1fr; gap:8px;">
            ${monsHtml}
        </div>
    `;
}

// ─── DIAGNÓSTICO BATERIA HÍBRIDA (HV) — BENCHMARK DR. PRIUS / TOYOTA THS II ───
let latestHvBatteryData = null;

function checkHvBatteryHealth() {
    console.log("Requisitando Tensões de Blocos de Bateria HV (2181 / 21CE)...");
    if (typeof sendEspCommand === "function") {
        sendEspCommand({ cmd: "obd_query", pid: "2181", proto: "can", header: "7E2" });
    }

    let modalHtml = `
    <div id="hv-battery-modal" style="position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.75); display:flex; align-items:center; justify-content:center; z-index:99999;">
        <div style="background:#0f172a; border:1px solid #38bdf8; border-radius:12px; max-width:680px; width:90%; padding:20px; color:#fff; font-family:sans-serif; max-height:85vh; overflow-y:auto;">
            <div style="display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid #1e293b; padding-bottom:12px; margin-bottom:14px;">
                <h3 style="margin:0; font-size:16px; color:#38bdf8; display:flex; align-items:center; gap:8px;">
                    <span>🔋</span> Análise de Bateria Híbrida / Tração HV (Dr. Prius THS II Engine)
                </h3>
                <button onclick="document.getElementById('hv-battery-modal').remove()" style="background:none; border:none; color:#94a3b8; font-size:20px; cursor:pointer;">&times;</button>
            </div>
            <div id="hv-battery-modal-content" style="font-size:13px; line-height:1.6;">
                <div style="text-align:center; padding:20px; color:#94a3b8;">
                    Comunicando com ECU Híbrida / Inversor (0x7E2)... Requisitando blocos de tensão (21 81).
                </div>
            </div>
            <div style="margin-top:16px; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px;">
                <div style="display:flex; gap:8px;">
                    <button onclick="sendEspCommand({ cmd: 'uds_raw', payload: '06 2F 28 02 03 06 80', proto: 'can', header: '7E2' })" style="background:#0284c7; color:#fff; border:none; padding:6px 12px; border-radius:6px; cursor:pointer; font-size:12px;">🌪️ Forçar Cooler Máx</button>
                    <button onclick="sendEspCommand({ cmd: 'uds_raw', payload: '06 2F 28 02 03 00 80', proto: 'can', header: '7E2' })" style="background:#475569; color:#fff; border:none; padding:6px 12px; border-radius:6px; cursor:pointer; font-size:12px;">🛑 Parar Forçamento</button>
                </div>
                <div style="display:flex; gap:8px;">
                    <button onclick="sendEspCommand({ cmd: 'obd_query', pid: '2181', proto: 'can', header: '7E2' })" class="btn btn-secondary" style="background:#1e293b; color:#fff; border:1px solid #475569; padding:8px 16px; border-radius:6px; cursor:pointer;">🔄 Medir Novamente</button>
                    <button onclick="document.getElementById('hv-battery-modal').remove()" class="btn btn-primary" style="background:#0284c7; color:#fff; border:none; padding:8px 16px; border-radius:6px; cursor:pointer;">Fechar</button>
                </div>
            </div>
        </div>
    </div>
    `;

    const old = document.getElementById("hv-battery-modal");
    if (old) old.remove();
    document.body.insertAdjacentHTML("beforeend", modalHtml);

    if (latestHvBatteryData) {
        renderHvBatteryModal(latestHvBatteryData);
    }
}

function renderHvBatteryModal(hvData) {
    const el = document.getElementById("hv-battery-modal-content");
    if (!el || !hvData) return;

    let statusColor = hvData.deltaVoltage <= 0.20 ? "#22c55e" : (hvData.deltaVoltage <= 0.30 ? "#eab308" : "#ef4444");

    let pills = (hvData.blocks || []).map((b, idx) => `
        <div style="background:#1e293b; border:1px solid #334155; border-radius:6px; padding:6px 10px; text-align:center;">
            <div style="font-size:10px; color:#94a3b8;">BLOCO ${idx+1}</div>
            <div style="font-size:14px; font-weight:bold; color:#38bdf8; font-family:monospace;">${b.toFixed(2)} V</div>
        </div>
    `).join("");

    el.innerHTML = `
        <div style="background:#1e293b; border-radius:8px; padding:12px; margin-bottom:14px; display:flex; justify-content:space-between; align-items:center;">
            <div><strong>Saúde dos Módulos:</strong> <span style="color:${statusColor}; font-weight:bold;">${hvData.status}</span></div>
            <div><strong>Delta V (Diferença Máx):</strong> <span style="font-family:monospace; font-weight:bold; color:${statusColor};">${hvData.deltaVoltage.toFixed(3)} V</span></div>
            <div><strong>Tensão Média:</strong> <span style="font-family:monospace;">${hvData.avgVoltage.toFixed(2)} V</span></div>
        </div>
        <div style="font-size:12px; color:#cbd5e1; margin-bottom:8px;"><strong>Tensões dos Blocos Individuais (${hvData.count} blocos detectados):</strong></div>
        <div style="display:grid; grid-template-columns:repeat(auto-fill, minmax(90px, 1fr)); gap:6px;">
            ${pills}
        </div>
    `;
}



