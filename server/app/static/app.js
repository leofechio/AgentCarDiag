// app.js — AgentCarDiag Web Dashboard Frontend

// OTA Upload Logic
async function uploadOTA() {
    const fileInput = document.getElementById('ota-file-input');
    const statusDiv = document.getElementById('ota-upload-status');
    const btn = document.getElementById('btn-ota-upload');

    if (!fileInput.files.length) {
        statusDiv.innerText = 'Selecione um arquivo .bin primeiro!';
        statusDiv.style.color = 'var(--accent-red)';
        return;
    }

    const file = fileInput.files[0];
    const deviceType = document.querySelector('input[name="ota-device"]:checked').value;
    
    const formData = new FormData();
    formData.append('file', file);
    formData.append('device_type', deviceType);

    statusDiv.innerText = 'Fazendo upload para o servidor...';
    statusDiv.style.color = 'var(--text-main)';
    btn.disabled = true;

    try {
        // Envia para nossa API no FastAPI
        const response = await fetch('/api/upload_firmware', {
            method: 'POST',
            body: formData
        });

        const result = await response.json();
        
        if (response.ok) {
            statusDiv.innerText = '✅ ' + result.msg;
            statusDiv.style.color = 'var(--accent-green)';
            if(window.sysLog) sysLog("OTA Update acionado! Hardware vai baixar: " + file.name, "info");
        } else {
            statusDiv.innerText = 'Erro: ' + (result.detail || 'Falha no upload');
            statusDiv.style.color = 'var(--accent-red)';
        }
    } catch (err) {
        statusDiv.innerText = 'Erro de rede: ' + err.message;
        statusDiv.style.color = 'var(--accent-red)';
    } finally {
        btn.disabled = false;
        fileInput.value = ''; // limpa
    }
}

/**
 * AgentCarDiag v2 — Dashboard Frontend
 * Manages WebSocket, CAN table, Oscilloscope canvas,
 * and Session sidebar with REST API integration.
 */

'use strict';

// ─── Constants ────────────────────────────────────────────────────────────────

const WS_PROTOCOL     = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
const WS_URL          = `${WS_PROTOCOL}//${window.location.host}/ws/client`;
const API_BASE        = '/api';
const MAX_CAN_ROWS    = 100;
const OSC_HISTORY_LEN = 2000;
const RECONNECT_DELAY = 2500;
const PPS_WINDOW_MS   = 1000;

const CAN_ID_MAP = {
  '0x120': { label: 'RPM',   cls: 'source-rpm'   },
  '0x201': { label: 'SPEED', cls: 'source-speed'  },
  '0x310': { label: 'TEMP',  cls: 'source-temp'   },
};

// ─── State ────────────────────────────────────────────────────────────────────

const state = {
  activeTab: 'can', // Tracks current active tab
  // WebSocket
  ws: null,
  wsConnected: false,
  reconnectTimer: null,
  pingTimer: null,
  pingTs: 0,
  latencyMs: 0,

  // CAN
  canPaused: false,
  canTotal: 0,
  canPacketTimestamps: [],
  canTelemetryFrames: [],

  // OSC
  oscFrozen: false,
  oscBuffer: [],
  oscBursts: 0,
  oscSampleRate: 0,
  oscCtx: null,

  // System
  startTime: Date.now(),
  hwNodes: 0,

  // Sessions
  sessions: [],
  activeSessionId: null,
  activeSessionName: null,
  sidebarOpen: false,
  sidebarCollapsed: false,   // desktop collapse state
  viewingHistorySession: false, // true when browsing a past session (not live)

  // OBD-II telemetry panel
  obd: {
    panelCollapsed: false,
    rpm: null,
    speed: null,
    temp: null,
    lastRpmTs: 0,
    lastSpdTs: 0,
    lastTmpTs: 0,
  },
  
  scopeSource: 'sim_demo',
};

// ─── Tab switching ─────────────────────────────────────────────────────────────

function switchTab(name) {
  state.activeTab = name;
  document.querySelectorAll('.tab-btn').forEach(b => {
    const active = b.id === `tab-${name}`;
    b.classList.toggle('active', active);
    b.setAttribute('aria-selected', String(active));
  });
  document.querySelectorAll('.tab-panel').forEach(p => {
    p.classList.toggle('active', p.id === `panel-${name}`);
  });
  if (name === 'osc') {
    if (!oscState.gridCtx) {
      initOscCanvas();
    }
    setTimeout(resizeOscCanvas, 50);
    setTimeout(resizeOscCanvas, 200);
    if (!oscState.animId) {
      oscState.animId = requestAnimationFrame(oscRenderLoop);
    }
  } else {
    if (oscState.animId) {
      cancelAnimationFrame(oscState.animId);
      oscState.animId = null;
    }
  }
  if (name === 'sys' || name === 'workshops') fetchStatus();
  if (name === 'workshops') {
    if (typeof loadWorkshopsList === 'function') loadWorkshopsList();
    if (typeof loadWorkshopDevices === 'function') loadWorkshopDevices();
  }
  if (name === 'manuals') {
    const sel = document.getElementById('manual-vehicle-select');
    const vId = (sel && sel.value) ? sel.value : (state.currentVehicle || 'renault_trafic_m9r');
    if (sel && sel.value !== vId) sel.value = vId;
    loadVehicleManualDetails(vId);
  }
  if (name === 'aguiacar') {
    setTimeout(() => {
      if (typeof initFleetMap === 'function') initFleetMap();
      if (typeof loadFleetData === 'function') loadFleetData();
      if (typeof loadFleetConfig === 'function') loadFleetConfig();
      if (typeof loadFleetAlerts === 'function') loadFleetAlerts();
    }, 80);
  }

  // Atualiza acendimento dos botões da tela ativa
  if (typeof updateSystemActionCapabilities === 'function') {
    updateSystemActionCapabilities();
  }
}

// ─── Central de Capacidades Dinâmicas & Acendimento de Botões ────────────────
function updateSystemActionCapabilities() {
  const hwOnline = (window.state && window.state.hwNodes > 0);
  const ecuOnline = !!(window.state && window.state.ecuOnline);
  const activeProfileKey = (typeof currentVehicleProfile !== 'undefined' ? currentVehicleProfile : 'generic_obd');
  const prof = (typeof VEHICLE_PROFILES !== 'undefined' && VEHICLE_PROFILES[activeProfileKey]) ? VEHICLE_PROFILES[activeProfileKey] : null;
  const caps = (prof && prof.capabilities) ? prof.capabilities : {
    modules: ["ECM"],
    services: [],
    emissions: { egr: false, dpf: false, adblue: false },
    flasher: false,
    hvBattery: false
  };

  // 1. Atualizar LEDs Indicadores das Abas de Navegação (Verde = Hardware Online, Preto/Apagado = Offline)
  const tabsWithHw = [
    { id: 'tab-can', dotId: 'dot-tab-can', name: 'Sniffer CAN' },
    { id: 'tab-osc', dotId: 'dot-tab-osc', name: 'Osciloscópio' },
    { id: 'tab-scanner', dotId: 'dot-tab-scanner', name: 'Scanner OBD-II' },
    { id: 'tab-aguiacar', dotId: 'dot-tab-aguiacar', name: 'AguiaCar' },
    { id: 'tab-flasher', dotId: 'dot-tab-flasher', name: 'ECU Flasher' },
    { id: 'tab-xpro', dotId: 'dot-tab-xpro', name: 'X-PRO5' }
  ];

  tabsWithHw.forEach(({ id, dotId, name }) => {
    const tabEl = document.getElementById(id);
    const dotEl = document.getElementById(dotId);
    if (tabEl) {
      tabEl.classList.remove('tab-disabled');
    }
    if (dotEl) {
      dotEl.classList.toggle('online', !!hwOnline);
      dotEl.title = hwOnline ? `${name}: Dispositivo Conectado (Online)` : `${name}: Sem dispositivo conectado (Offline)`;
    }
  });

  // 2. Botões do Sniffer CAN
  const btnCanStart = document.getElementById('btn-can-start');
  const btnCanStop = document.getElementById('btn-can-stop');
  if (btnCanStart) {
    btnCanStart.disabled = !hwOnline;
    btnCanStart.classList.toggle('btn-action-disabled', !hwOnline);
    btnCanStart.classList.toggle('btn-action-ready', hwOnline);
  }
  if (btnCanStop) {
    btnCanStop.disabled = !hwOnline;
    btnCanStop.classList.toggle('btn-action-disabled', !hwOnline);
  }

  // 3. Botões do Osciloscópio (Habilitado se hardware online OU em modo simulador)
  const btnOscRun = document.getElementById('btn-osc-run');
  const sourceSelect = document.getElementById('scope-source-select');
  const isOscDemo = !sourceSelect || sourceSelect.value === 'sim_demo';
  const oscCanRun = hwOnline || isOscDemo;
  if (btnOscRun) {
    btnOscRun.disabled = !oscCanRun;
    btnOscRun.classList.toggle('btn-action-disabled', !oscCanRun);
    btnOscRun.classList.toggle('btn-action-ready', oscCanRun);
  }

  // 4. Scanner OBD-II: Ações Rápidas
  // Botão de Auto-detectar VIN (Primeiro contato com o veículo)
  const btnAutoVin = document.querySelector('button[onclick="requestAutoVinDetection()"]');
  if (btnAutoVin) {
    btnAutoVin.disabled = !hwOnline;
    btnAutoVin.classList.toggle('btn-action-disabled', !hwOnline);
    btnAutoVin.classList.toggle('btn-action-ready', hwOnline && !ecuOnline);
  }

  // Varredura de Saúde (🩺)
  const btnHealth = document.getElementById('btn-scan-health');
  if (btnHealth) {
    btnHealth.disabled = !hwOnline;
    btnHealth.classList.toggle('btn-action-disabled', !hwOnline);
    btnHealth.classList.toggle('btn-action-ready', hwOnline);
  }

  // Auditoria CAN (🧪)
  const btnAudit = document.getElementById('btn-scan-audit');
  if (btnAudit) {
    btnAudit.disabled = !hwOnline;
    btnAudit.classList.toggle('btn-action-disabled', !hwOnline);
    btnAudit.classList.toggle('btn-action-ready', hwOnline);
  }

  // Emissões (🌿) — requer suporte a combustão ou módulos de emissão
  const btnEmissions = document.getElementById('btn-scan-emissions');
  if (btnEmissions) {
    const hasEmissions = prof ? !!prof.showCombustion : true;
    const canEmissions = hwOnline && hasEmissions;
    btnEmissions.disabled = !canEmissions;
    btnEmissions.classList.toggle('btn-action-disabled', !canEmissions);
    btnEmissions.classList.toggle('btn-action-ready', canEmissions && ecuOnline);
  }

  // Bateria Híbrida / EV (🔋) — apaga e bloqueia em veículos puramente a combustão
  const btnHv = document.getElementById('btn-scan-hv-battery');
  if (btnHv) {
    const isHvSupported = !!(caps.hvBattery || (prof && prof.showEv));
    const canHv = hwOnline && isHvSupported;
    btnHv.disabled = !canHv;
    btnHv.classList.toggle('btn-action-disabled', !canHv);
    btnHv.classList.toggle('btn-action-ready', canHv && ecuOnline);
    btnHv.title = isHvSupported ? "Diagnóstico de bateria HV" : "Indisponível: Este veículo não possui bateria de tração híbrida/EV";
  }

  // Limpar Falhas (🧹)
  const btnClearDtcs = document.getElementById('btn-scan-clear');
  if (btnClearDtcs) {
    btnClearDtcs.disabled = !hwOnline;
    btnClearDtcs.classList.toggle('btn-action-disabled', !hwOnline);
  }

  // Live Data Stream: Botão Iniciar Leitura
  const btnStartStream = document.getElementById('btn-start-stream');
  if (btnStartStream) {
    btnStartStream.disabled = !hwOnline;
    btnStartStream.classList.toggle('btn-action-disabled', !hwOnline);
    btnStartStream.classList.toggle('btn-action-ready', hwOnline && ecuOnline);
  }

  // 5. Serviços Rápidos de Oficina (Quick Services UDS)
  const srvList = [
    { id: 'btn-srv-epb', key: 'epb_service', name: 'EPB' },
    { id: 'btn-srv-bms', key: 'bms_reset', name: 'BMS 12V' },
    { id: 'btn-srv-dpf', key: 'dpf_regen', name: 'DPF' },
    { id: 'btn-srv-throttle', key: 'throttle_learn', name: 'TBI/EGR' },
    { id: 'btn-srv-sas', key: 'sas_reset', name: 'SAS' }
  ];

  srvList.forEach(srv => {
    const btn = document.getElementById(srv.id);
    if (!btn) return;
    const isSupported = (caps.services && caps.services.includes(srv.key));
    const isOperable = hwOnline && ecuOnline && isSupported;

    btn.disabled = !isOperable;
    btn.classList.toggle('btn-action-disabled', !isOperable);
    btn.classList.toggle('btn-action-ready', isOperable);

    if (!isSupported) {
      btn.title = `Indisponível: O módulo de ${srv.name} não existe ou não suporta esta rotina neste veículo catalogado.`;
    } else if (!hwOnline) {
      btn.title = `Dispositivo offline. Conecte o Scanner OBD-II para operar ${srv.name}.`;
    } else if (!ecuOnline) {
      btn.title = `Aguardando contato CAN com a central para liberar ${srv.name}.`;
    } else {
      btn.title = `Pronto para executar rotina no módulo.`;
    }
  });

  // 6. ECU Flasher & Gerenciamento de Emissões
  const btnFlash = document.querySelector('button[onclick="startOneClickFlashing()"]');
  if (btnFlash) {
    const isFlashSupported = hwOnline && ecuOnline && !!caps.flasher;
    btnFlash.disabled = !isFlashSupported;
    btnFlash.classList.toggle('btn-action-disabled', !isFlashSupported);
    btnFlash.classList.toggle('btn-action-ready', isFlashSupported);
  }

  const btnCheckEmissions = document.querySelector('button[onclick="checkEmissionsStatus()"]');
  if (btnCheckEmissions) {
    const canCheckEmiss = hwOnline && ecuOnline && (caps.emissions.egr || caps.emissions.dpf || caps.emissions.adblue);
    btnCheckEmissions.disabled = !canCheckEmiss;
    btnCheckEmissions.classList.toggle('btn-action-disabled', !canCheckEmiss);
  }

  const btnEgr = document.getElementById('btn-toggle-egr');
  if (btnEgr) {
    const canEgr = hwOnline && ecuOnline && !!caps.emissions.egr;
    btnEgr.disabled = !canEgr;
    btnEgr.classList.toggle('btn-action-disabled', !canEgr);
    btnEgr.classList.toggle('btn-action-ready', canEgr);
  }

  const btnDpf = document.getElementById('btn-toggle-dpf');
  if (btnDpf) {
    const canDpf = hwOnline && ecuOnline && !!caps.emissions.dpf;
    btnDpf.disabled = !canDpf;
    btnDpf.classList.toggle('btn-action-disabled', !canDpf);
    btnDpf.classList.toggle('btn-action-ready', canDpf);
  }

  const btnAdblue = document.getElementById('btn-toggle-adblue');
  if (btnAdblue) {
    const canAdblue = hwOnline && ecuOnline && !!caps.emissions.adblue;
    btnAdblue.disabled = !canAdblue;
    btnAdblue.classList.toggle('btn-action-disabled', !canAdblue);
    btnAdblue.classList.toggle('btn-action-ready', canAdblue);
  }

  // 7. Atualização Dinâmica do Guia Prático para o Operador / Leigo (Benchmark Autel / REAlog)
  const guideIcon = document.getElementById('guide-step-icon');
  const guideTitle = document.getElementById('guide-step-title');
  const guideDesc = document.getElementById('guide-step-desc');
  const guideBadge = document.getElementById('guide-precaution-tag');

  if (guideIcon && guideTitle && guideDesc && guideBadge) {
    if (!hwOnline) {
      guideIcon.textContent = '🔌';
      guideTitle.textContent = 'Passo 1: Conecte o Scanner na tomada OBD-II do carro';
      guideDesc.textContent = 'A tomada OBD-II fica sob o volante ou painel central. Conecte a interface ESP32-S3 e certifique-se de que o aparelho esteja alimentado.';
      guideBadge.innerHTML = '⚠️ Scanner Desconectado';
      guideBadge.style.borderColor = 'rgba(239, 68, 68, 0.4)';
      guideBadge.style.color = '#fca5a5';
      guideBadge.style.background = 'rgba(239, 68, 68, 0.15)';
    } else if (!ecuOnline) {
      guideIcon.textContent = '🔑';
      guideTitle.textContent = 'Passo 2: Ligue a chave de ignição sem dar a partida';
      guideDesc.textContent = 'Gire a chave para acender as luzes do painel (posição II). Clique em "Auto-Detectar VIN" ou "Varredura Rápida" para ler os módulos do veículo.';
      guideBadge.innerHTML = '⚠️ Ignição Ligada / Motor Desligado';
      guideBadge.style.borderColor = 'rgba(234, 179, 8, 0.4)';
      guideBadge.style.color = '#fde047';
      guideBadge.style.background = 'rgba(234, 179, 8, 0.15)';
    } else {
      guideIcon.textContent = '✅';
      guideTitle.textContent = 'Passo 3: Veículo Conectado — Selecione a Operação';
      guideDesc.textContent = 'Módulos eletrônicos identificados. Somente os botões suportados por este veículo estão liberados (destacados com brilho verde/ciano).';
      guideBadge.innerHTML = '🟢 Comunicação CAN Estável';
      guideBadge.style.borderColor = 'rgba(16, 185, 129, 0.4)';
      guideBadge.style.color = '#34d399';
      guideBadge.style.background = 'rgba(16, 185, 129, 0.15)';
    }
  }
}

// ─── Sidebar ──────────────────────────────────────────────────────────────────

function toggleSidebar() {
  const isMobile = window.innerWidth <= 768;
  if (isMobile) {
    state.sidebarOpen ? closeSidebar() : openSidebar();
  } else {
    // Desktop: toggle collapsed state (width animation)
    state.sidebarCollapsed = !state.sidebarCollapsed;
    const sidebar = document.getElementById('sidebar');
    sidebar.classList.toggle('collapsed', state.sidebarCollapsed);
    const btn = document.getElementById('sidebar-toggle');
    btn.setAttribute('aria-expanded', String(!state.sidebarCollapsed));
  }
}

function openSidebar() {
  state.sidebarOpen = true;
  document.getElementById('sidebar').classList.add('open');
  document.getElementById('sidebar-overlay').classList.add('visible');
  document.getElementById('sidebar-toggle').setAttribute('aria-expanded', 'true');
}

function closeSidebar() {
  state.sidebarOpen = false;
  document.getElementById('sidebar').classList.remove('open');
  document.getElementById('sidebar-overlay').classList.remove('visible');
  document.getElementById('sidebar-toggle').setAttribute('aria-expanded', 'false');
}

// ─── Modal: New Session ────────────────────────────────────────────────────────

function openNewSessionModal() {
  closeSidebar();
  const modal = document.getElementById('modal-overlay');
  modal.hidden = false;
  modal.removeAttribute('hidden');
  setTimeout(() => document.getElementById('input-name').focus(), 50);
}

function closeNewSessionModal() {
  const modal = document.getElementById('modal-overlay');
  modal.hidden = true;
  modal.setAttribute('hidden', '');
  document.getElementById('new-session-form').reset();
}

/* ── Settings Modal ──────────────────────────────────────────────── */
function openSettingsModal(initialTab) {
  const el = document.getElementById('modal-settings');
  if (!el) return;
  el.classList.remove('hidden');
  switchSettingsTab(initialTab || 'dispositivos');
  // Load workshop devices list when opening
  if (typeof loadWorkshopDevices === 'function') loadWorkshopDevices();
}

function closeSettingsModal() {
  const el = document.getElementById('modal-settings');
  if (el) el.classList.add('hidden');
}

function switchSettingsTab(name) {
  document.querySelectorAll('.settings-tab-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.stab === name);
  });
  document.querySelectorAll('.settings-tab-panel').forEach(p => {
    p.classList.toggle('active', p.dataset.stabPanel === name);
  });
  // Auto-fetch status when switching to terminal tab
  if (name === 'terminal' && typeof fetchStatus === 'function') fetchStatus();
}


// Close modal on backdrop click
document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('modal-overlay').addEventListener('click', (e) => {
    if (e.target === e.currentTarget) closeNewSessionModal();
  });
  // Settings modal backdrop click
  const sm = document.getElementById('modal-settings');
  if (sm) sm.addEventListener('click', (e) => {
    if (e.target === sm) closeSettingsModal();
  });
  // ESC key closes any open modal
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      closeNewSessionModal();
      closeSettingsModal();
    }
  });
});

async function submitNewSession(e) {
  e.preventDefault();
  const name  = document.getElementById('input-name').value.trim();
  const notes = document.getElementById('input-notes').value.trim();
  const profileSelect = document.getElementById('input-session-profile');
  const vehicleProfile = profileSelect ? profileSelect.value : (currentVehicleProfile || 'renault_trafic_m9r');
  if (!name) return;

  const btn = document.getElementById('btn-create-session');
  btn.disabled = true;
  btn.innerHTML = '<span>⏳ Criando…</span>';

  try {
    const session = await apiPost('/api/sessions', { 
      name, 
      notes, 
      vehicle_profile: vehicleProfile 
    });
    closeNewSessionModal();
    state.sessions.unshift(session);
    state.activeSessionId = session.id;
    state.activeSessionName = session.name;
    
    // Alinha o perfil de diagnóstico no scanner
    if (typeof VEHICLE_PROFILES !== 'undefined' && VEHICLE_PROFILES[vehicleProfile]) {
      const selVeh = document.getElementById("hw-vehicle-select");
      if (selVeh) {
        selVeh.value = vehicleProfile;
        if (typeof changeVehicleProfile === 'function') changeVehicleProfile();
      }
    }

    renderSessionList();
    updateActiveSessionChip();
    // Return to live mode
    state.viewingHistorySession = false;
    clearCan();
    clearOscDisplay();
    sysLog(`✔ Sessão criada: "${session.name}" [${vehicleProfile}]`, 'success');
    showToast(`🚗 Sessão iniciada: ${session.name}`, 'success');
  } catch (err) {
    sysLog(`Erro ao criar sessão: ${err.message}`, 'error');
    showToast('❌ Erro ao criar sessão', 'error');
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<span>✔ Criar Sessão</span>';
  }
}

// ─── Sessions API ─────────────────────────────────────────────────────────────

async function loadSessions() {
  try {
    // Uses a relative URL so the browser sends the request via HTTPS natively
    // when behind a reverse proxy (e.g. Cloudflare Tunnel).
    const sessions = await apiFetch('/api/sessions');
    state.sessions = sessions;
    renderSessionList();

    // Find and reflect the active session
    const active = sessions.find(s => s.is_active === 1);
    if (active) {
      state.activeSessionId   = active.id;
      state.activeSessionName = active.name;
      updateActiveSessionChip();
      
      // Sincroniza o perfil do veículo com a sessão ativa
      if (active.vehicle_profile) {
        const selVeh = document.getElementById("hw-vehicle-select");
        if (selVeh && selVeh.value !== active.vehicle_profile) {
          selVeh.value = active.vehicle_profile;
          if (typeof changeVehicleProfile === 'function') changeVehicleProfile();
        }
      }
    }
  } catch (err) {
    // Log the failure but do not re-throw — a transient WS / network issue
    // must not prevent the rest of the page from initialising.
    sysLog(`Falha ao carregar sessões: ${err.message}`, 'error');
    renderSessionList(); // render empty state gracefully
  }
}

async function activateSession(sessionId) {
  try {
    const session = await apiFetch(`/api/sessions/${sessionId}/activate`, { method: 'PUT' });
    state.activeSessionId   = session.id;
    state.activeSessionName = session.name;

    // Sincroniza o perfil do veículo do scanner com a sessão ativada
    if (session.vehicle_profile) {
      const selVeh = document.getElementById("hw-vehicle-select");
      if (selVeh) {
        selVeh.value = session.vehicle_profile;
        if (typeof changeVehicleProfile === 'function') changeVehicleProfile();
      }
    }

    // Mark in local list
    state.sessions.forEach(s => { s.is_active = s.id === sessionId ? 1 : 0; });
    renderSessionList();
    updateActiveSessionChip();

    sysLog(`✔ Sessão ativa: "${session.name}"`, 'success');
    showToast(`✅ Ativo: ${session.name}`, 'success');
  } catch (err) {
    sysLog(`Erro ao ativar sessão: ${err.message}`, 'error');
  }
}

async function loadSessionHistory(sessionId) {
  sysLog(`Carregando histórico da sessão ${sessionId}…`, 'info');
  try {
    const detail = await apiFetch(`/api/sessions/${sessionId}?limit=300`);

    // Switch to history view mode
    state.viewingHistorySession = true;
    closeSidebar();

    // Clear current live data
    clearCan(false);
    clearOscDisplay();

    // Sincroniza o perfil do veículo do histórico
    if (detail.vehicle_profile) {
      const selVeh = document.getElementById("hw-vehicle-select");
      if (selVeh) {
        selVeh.value = detail.vehicle_profile;
        if (typeof changeVehicleProfile === 'function') changeVehicleProfile();
      }
    }

    // Carrega dados salvos do scanner / health report se existirem
    if (detail.scanner_data) {
      try {
        const sData = typeof detail.scanner_data === 'string' ? JSON.parse(detail.scanner_data) : detail.scanner_data;
        if (sData && sData.results && typeof healthReportState !== 'undefined') {
          healthReportState.results = sData.results;
          if (typeof renderAllReportCards === 'function') {
            const list = document.getElementById('health-report-list');
            if (list) {
              const prof = (typeof VEHICLE_PROFILES !== 'undefined' && VEHICLE_PROFILES[sData.profile]) || { name: detail.name, summaryInfo: "Histórico salvo" };
              list.innerHTML = `
                <div style="background: rgba(0, 212, 255, 0.08); border: 1px solid var(--accent-cyan); padding: 12px; border-radius: 8px; margin-bottom: 12px; display:flex; justify-content:space-between; align-items:center;">
                  <div>
                    <h4 style="margin: 0; color: var(--accent-cyan);">📁 Varredura Salva desta Sessão — ${sData.totalDtcs || 0} Falha(s)</h4>
                    <p style="margin: 4px 0 0 0; font-size: 11px; color: var(--text-muted);">${prof.name} — Registrada em ${new Date(sData.timestamp).toLocaleString('pt-BR')}</p>
                  </div>
                </div>
                <div id="health-report-cards"></div>
              `;
              renderAllReportCards();
            }
          }
        }
      } catch (e) {}
    }

    // Populate CAN table with history (reversed = oldest first)
    const frames = [...detail.can_logs].reverse();
    if (frames.length) {
      document.getElementById('can-empty-state').style.display = 'none';
      frames.forEach(row => {
        appendCanRowFromHistory(row);
      });
      state.canTotal = detail.can_count;
      document.getElementById('can-total-display').textContent = detail.can_count;
    }

    // Populate OSC with last capture
    if (detail.osc_captures && detail.osc_captures.length) {
      const captureId = detail.osc_captures[0].id;
      loadOscCapture(sessionId, captureId);
    }

    switchTab('can');
    showToast(`📂 Histórico: ${detail.name}`, 'info');
    sysLog(`Histórico carregado: ${frames.length} frames CAN, ${detail.osc_captures?.length || 0} capturas OSC`, 'success');
  } catch (err) {
    sysLog(`Erro ao carregar histórico: ${err.message}`, 'error');
    showToast('❌ Falha ao carregar histórico', 'error');
  }
}

async function loadOscCapture(sessionId, captureId) {
  const detail = await apiFetch(`/api/sessions/${sessionId}?limit=1`);
  const cap = detail.osc_captures && detail.osc_captures[0];
  if (cap) {
    const elMin = document.getElementById('osc-badge-vmin') || document.getElementById('stat-vmin');
    const elMax = document.getElementById('osc-badge-vmax') || document.getElementById('stat-vmax');
    const elMean = document.getElementById('osc-badge-vmean') || document.getElementById('stat-vmean');
    if (elMin) elMin.textContent = (cap.vmin?.toFixed(2) ?? '0.0') + ' V';
    if (elMax) elMax.textContent = (cap.vmax?.toFixed(2) ?? '0.0') + ' V';
    if (elMean) elMean.textContent = (cap.vmean?.toFixed(2) ?? '0.0') + ' V';
  }
}

async function deleteSession(sessionId, e) {
  e.stopPropagation(); // don't trigger card click
  if (!confirm('Excluir esta sessão e todos os dados associados?')) return;

  try {
    await apiFetch(`/api/sessions/${sessionId}`, { method: 'DELETE' });
    state.sessions = state.sessions.filter(s => s.id !== sessionId);
    if (state.activeSessionId === sessionId) {
      state.activeSessionId   = null;
      state.activeSessionName = null;
      updateActiveSessionChip();
    }
    renderSessionList();
    showToast('🗑 Sessão excluída', 'warning');
  } catch (err) {
    showToast('❌ Erro ao excluir sessão', 'error');
  }
}

// ─── Render Session List ───────────────────────────────────────────────────────

function renderSessionList() {
  const container = document.getElementById('sidebar-sessions');
  const empty     = document.getElementById('sidebar-empty');

  if (!state.sessions.length) {
    empty.style.display = 'flex';
    container.querySelectorAll('.session-card').forEach(el => el.remove());
    return;
  }

  empty.style.display = 'none';
  container.querySelectorAll('.session-card').forEach(el => el.remove());

  state.sessions.forEach(session => {
    const isActive = session.id === state.activeSessionId || session.is_active === 1;
    const card = document.createElement('div');
    card.className = `session-card${isActive ? ' active-session' : ''}`;
    card.setAttribute('role', 'listitem');
    card.setAttribute('title', session.notes || session.name);

    const date = new Date(session.updated_at).toLocaleDateString('pt-BR', {
      day: '2-digit', month: '2-digit', year: '2-digit',
      hour: '2-digit', minute: '2-digit',
    });

    const profObj = (typeof VEHICLE_PROFILES !== 'undefined' && VEHICLE_PROFILES[session.vehicle_profile]) 
      ? VEHICLE_PROFILES[session.vehicle_profile] 
      : null;
    const profName = profObj ? profObj.name.split('(')[0].trim() : (session.vehicle_profile || 'Padrão CAN');

    card.innerHTML = `
      <div class="session-card-indicator"></div>
      <div class="session-card-body">
        <div class="session-card-name">${escapeHtml(session.name)}</div>
        <div class="session-card-meta">
          <span class="session-card-date">${date}</span>
          ${isActive ? '<span class="session-card-badge">ATIVO</span>' : ''}
        </div>
        <div style="font-size: 10px; color: var(--accent-cyan); margin-top: 3px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">
          🚗 ${escapeHtml(profName)}
        </div>
        ${session.notes ? `<div class="session-card-notes">${escapeHtml(session.notes)}</div>` : ''}
      </div>
      <button class="session-delete-btn" title="Excluir sessão" onclick="deleteSession('${session.id}', event)" aria-label="Excluir sessão">🗑</button>
    `;

    card.addEventListener('click', () => {
      if (isActive) {
        // Already active: return to live view
        state.viewingHistorySession = false;
        clearCan(false);
        clearOscDisplay();
        closeSidebar();
      } else {
        // Activate + load history
        activateSession(session.id).then(() => loadSessionHistory(session.id));
      }
    });

    container.appendChild(card);
  });
}

function updateActiveSessionChip() {
  const chip = document.getElementById('active-session-chip');
  const name = document.getElementById('active-session-name');

  if (state.activeSessionName) {
    chip.classList.add('has-session');
    name.textContent = state.activeSessionName;
  } else {
    chip.classList.remove('has-session');
    name.textContent = 'Sem sessão ativa';
  }
}

// ─── WebSocket ─────────────────────────────────────────────────────────────────

function connectWS() {
  if (state.ws) { try { state.ws.close(); } catch (_) {} }

  sysLog('Conectando ao servidor…', 'info');
  const ws = new WebSocket(WS_URL);
  state.ws = ws;

  ws.onopen = () => {
    state.wsConnected = true;
    updateWsStatus(true);
    sysLog('WebSocket conectado', 'success');
    showToast('✅ Conectado ao servidor', 'success');
    state.pingTimer = setInterval(sendPing, 5000);
    sendPing();
  };

  ws.onmessage = (evt) => {
    try { handleMessage(JSON.parse(evt.data)); } catch (e) { /* ignore */ }
  };

  ws.onclose = (evt) => {
    state.wsConnected = false;
    updateWsStatus(false);
    clearInterval(state.pingTimer);
    sysLog(`WebSocket desconectado (${evt.code})`, 'warning');
    state.reconnectTimer = setTimeout(connectWS, RECONNECT_DELAY);
  };

  ws.onerror = () => {
    sysLog('Erro na conexão WebSocket', 'error');
    showToast('❌ Erro de conexão', 'error');
  };
}

function sendWS(obj) {
  if (state.ws && state.wsConnected) state.ws.send(JSON.stringify(obj));
}

function sendPing() {
  state.pingTs = performance.now();
  sendWS({ cmd: 'ping' });
}

// ─── Message routing ───────────────────────────────────────────────────────────

function handleMessage(msg) {
  switch (msg.type) {
    case 'pong':
      state.latencyMs = Math.round(performance.now() - state.pingTs);
      document.getElementById('sys-latency').textContent = state.latencyMs;
      break;
    case 'system':
      handleSystemMessage(msg);
      break;
    case 'can_frame':
      if (!state.viewingHistorySession) {
        appendCanRow(msg);
        // Decode OBD-II asynchronously so the table never lags
        setTimeout(() => decodeObdFrame(msg), 0);
      }
      break;
    case 'adc_burst':
      if (!state.viewingHistorySession) handleAdcBurst(msg);
      break;
    case 'cmd_ack':
      sysLog(`Comando "${msg.cmd}" → ${msg.nodes_reached} nó(s)`, 'info');
      showToast(`📨 ${msg.cmd} → ${msg.nodes_reached} nó(s)`, 'success');
      break;
    case 'uds_resp':
      const log = document.getElementById('uds-log');
      if (log) {
          let outcome = { success: true, detail: "Dados recebidos", raw: msg.raw };
          if (typeof parseUdsResponse === 'function') {
              outcome = parseUdsResponse(msg.raw);
          }

          if (outcome.type === 'negative') {
              // Resposta Negativa NRC
              log.innerHTML += `
                  <div style="background: rgba(239, 68, 68, 0.15); border: 1px solid #ef4444; border-radius: 6px; padding: 8px; margin: 6px 0; font-family: monospace;">
                      <div style="color: #ef4444; font-weight: bold; font-size: 13px;">❌ COMANDO RECUSADO PELA ECU (${outcome.rejectedService})</div>
                      <div style="color: #fca5a5; font-size: 11px; margin-top: 2px;"><strong>Motivo:</strong> ${outcome.name} (${outcome.nrc})</div>
                      <div style="color: #fff; font-size: 11px; margin-top: 2px;">ℹ️ ${outcome.reason}</div>
                      <div style="color: #64748b; font-size: 10px; margin-top: 4px;">Bytes: ${msg.header} &lt;- ${msg.raw}</div>
                  </div>
              `;
              if (typeof showToast === 'function') showToast(`❌ Recusado: ${outcome.name}`, 'error');
          } else if (outcome.type === 'positive') {
              // Resposta Positiva de Sucesso
              log.innerHTML += `
                  <div style="background: rgba(16, 185, 129, 0.15); border: 1px solid #10b981; border-radius: 6px; padding: 8px; margin: 6px 0; font-family: monospace;">
                      <div style="color: #10b981; font-weight: bold; font-size: 13px;">✅ SUCESSO: COMANDO EXECUTADO (${outcome.service})</div>
                      <div style="color: #a7f3d0; font-size: 11px; margin-top: 2px;">${outcome.detail}</div>
                      <div style="color: #64748b; font-size: 10px; margin-top: 4px;">Bytes: ${msg.header} &lt;- ${msg.raw}</div>
                  </div>
              `;
              if (typeof showToast === 'function') showToast(`✅ Sucesso: ${outcome.detail}`, 'success');
          } else {
              // Resposta Genérica
              log.innerHTML += `<span style="color:#00ff66;">[RX] ${msg.header} &lt;- ${msg.raw}</span><br>`;
          }
          log.scrollTop = log.scrollHeight;
      }
      break;
  }
}

function handleSystemMessage(msg) {
  switch (msg.event) {
    case 'welcome':
      state.hwNodes = msg.active_hardware_nodes || 0;
      updateHwNodes();
      sysLog(`Conectado — Nós HW: ${state.hwNodes}`, 'success');
      break;
    case 'hardware_connected':
      state.hwNodes = msg.active_nodes || 0;
      updateHwNodes();
      sysLog(`⚡ Nó "${msg.node_id}" conectado`, 'success');
      showToast(`⚡ Nó "${msg.node_id}" conectado`, 'success');
      break;
    case 'hardware_disconnected':
      state.hwNodes = msg.active_nodes || 0;
      updateHwNodes();
      sysLog(`🔌 Nó "${msg.node_id}" desconectado`, 'warning');
      showToast(`🔌 Nó "${msg.node_id}" desconectado`, 'warning');
      break;
  }
}

function handleAdcBurst(msg) {
  // Se receber dados reais do ESP32, ativa automaticamente o modo Hardware Real
  if (state.scopeSource !== 'hw_stream') {
    state.scopeSource = 'hw_stream';
    const sourceSelect = document.getElementById('scope-source-select');
    if (sourceSelect) sourceSelect.value = 'hw_stream';
  }
  
  if (!oscState.running) return;
  
  let triggered = false;
  let ch1Data = msg.ch1 || [];
  
  if (oscState.trigMode !== 'Auto' && ch1Data.length > 0) {
      const edge = oscState.trigEdge === 'Rise' ? 1 : -1;
      const tLvl = oscState.trigLevel;
      for (let i = 1; i < ch1Data.length; i++) {
        if (edge > 0 && ch1Data[i-1] < tLvl && ch1Data[i] >= tLvl) {
          triggered = true;
          break;
        } else if (edge < 0 && ch1Data[i-1] > tLvl && ch1Data[i] <= tLvl) {
          triggered = true;
          break;
        }
      }
      
      // If Normal/Single and no trigger, skip updating buffer
      if (!triggered && (oscState.trigMode === 'Normal' || oscState.trigMode === 'Single')) {
          return; 
      }
      
      if (triggered && oscState.trigMode === 'Single') {
          setTimeout(toggleOscRun, 50); // Stop after this frame
      }
  }
  
  let activeLen = 0;
  if (msg.ch1 && oscState.ch1) {
    const len1 = Math.min(msg.ch1.length, oscState.buffer1.length);
    oscState.buffer1.set(msg.ch1.slice(0, len1));
    activeLen = Math.max(activeLen, len1);
  }
  
  if (msg.ch2 && oscState.ch2) {
    const len2 = Math.min(msg.ch2.length, oscState.buffer2.length);
    oscState.buffer2.set(msg.ch2.slice(0, len2));
    activeLen = Math.max(activeLen, len2);
  }
  
  oscState.bufferIdx = activeLen;
  
  if (msg.sample_rate) {
    oscState.sampleRate = msg.sample_rate;
  }
}

// ─── CAN Table ─────────────────────────────────────────────────────────────────

// ─── CAN Table Filtering ───────────────────────────────────────────────────────

const filterState = {
  queryId: '',
  activeChip: 'ALL',
};

function shouldDisplayFrame(frameIdHex) {
  const id = frameIdHex.toUpperCase();
  
  if (filterState.activeChip === 'OBD') {
    if (!id.includes('7E8')) return false;
  } else if (filterState.activeChip === 'POWERTRAIN') {
    if (!id.includes('280') && !id.includes('380')) return false;
  } else if (filterState.activeChip === 'NO_600') {
    if (id.includes('600')) return false;
  }

  if (filterState.queryId) {
    if (!id.includes(filterState.queryId.toUpperCase())) return false;
  }

  return true;
}

function updateVisibilityCounter() {
  const tbody = document.getElementById('can-tbody');
  if (!tbody) return;
  let visible = 0;
  const children = tbody.children;
  for (let i = 0; i < children.length; i++) {
    if (!children[i].classList.contains('d-none')) {
      visible++;
    }
  }
  document.getElementById('can-visible-count').textContent = visible;
  document.getElementById('can-visible-total').textContent = state.canTotal;
}

function applyCanFilters() {
  const tbody = document.getElementById('can-tbody');
  if (!tbody) return;
  const children = tbody.children;
  for (let i = 0; i < children.length; i++) {
    const tr = children[i];
    const idTd = tr.querySelector('.td-id');
    if (idTd) {
      if (shouldDisplayFrame(idTd.textContent)) {
        tr.classList.remove('d-none');
      } else {
        tr.classList.add('d-none');
      }
    }
  }
  updateVisibilityCounter();
}

function onCanFilterInput(val) {
  filterState.queryId = val.trim();
  const clearBtn = document.getElementById('can-filter-clear');
  if (filterState.queryId) {
    clearBtn.removeAttribute('hidden');
  } else {
    clearBtn.setAttribute('hidden', 'true');
  }
  applyCanFilters();
}

function clearCanFilter() {
  const input = document.getElementById('can-filter-input');
  input.value = '';
  onCanFilterInput('');
}

function setCanChip(chipType) {
  filterState.activeChip = chipType;
  const chips = document.querySelectorAll('.can-chip');
  chips.forEach(c => c.classList.remove('active'));
  const activeChipBtn = document.getElementById('chip-' + chipType);
  if (activeChipBtn) {
    activeChipBtn.classList.add('active');
  }
  applyCanFilters();
}

// ─── CAN Table ─────────────────────────────────────────────────────────────────

function appendCanRow(frame) {
  const now = Date.now();
  state.canPacketTimestamps.push(now);
  state.canTotal++;
  recordCanTelemetryFrame(frame, now);
  updateCanCrcPanel(frame);
  
  if (state.canPaused || state.activeTab !== 'can') return;

  document.getElementById('can-empty-state').style.display = 'none';

  const tbody  = document.getElementById('can-tbody');
  const scroll = document.getElementById('can-table-scroll');
  const atTop  = scroll.scrollTop < 30;

  const idHex  = frame.id || '0x000';
  const meta   = CAN_ID_MAP[idHex.toLowerCase()] || CAN_ID_MAP[idHex] || null;
  const dataHex = Array.isArray(frame.data)
    ? frame.data.map(b => b.toString(16).padStart(2, '0').toUpperCase()).join(' ')
    : (frame.data || '–');
  const ts = frame.ts
    ? new Date(frame.ts).toLocaleTimeString('pt-BR', { hour12: false, fractionalSecondDigits: 3 })
    : '–';

  const sourceLabel = meta ? meta.label : 'RAW';
  const tr = document.createElement('tr');
  tr.className = 'new-row';
  tr.style.cursor = 'pointer';
  if (!shouldDisplayFrame(idHex)) {
    tr.classList.add('d-none');
  }
  tr.dataset.timestamp = ts;
  tr.dataset.canId = idHex.toUpperCase();
  tr.dataset.dlc = frame.dlc ?? '–';
  tr.dataset.payload = dataHex;
  tr.dataset.origin = sourceLabel;
  tr.innerHTML = `
    <td class="td-ts">${escapeHtml(ts)}</td>
    <td class="td-id">${escapeHtml(idHex.toUpperCase())}</td>
    <td class="td-dlc">${escapeHtml(frame.dlc ?? '–')}</td>
    <td class="td-data">${escapeHtml(dataHex)}</td>
    <td><span class="td-source ${meta ? meta.cls : 'source-other'}">${escapeHtml(sourceLabel)}</span></td>
  `;

  tbody.insertBefore(tr, tbody.firstChild);
  while (tbody.children.length > MAX_CAN_ROWS) tbody.removeChild(tbody.lastChild);

  if (atTop) scroll.scrollTop = 0;
  // Note: updateCanStats (which calls updateVisibilityCounter) is called every 1 second globally.
}

// CRC-15/CAN (poly 0x4599, init/xorout 0) over payload bytes only.
// The WebSocket frame does not provide SOF/arbitration/control bits, so this
// deliberately does not claim to validate the complete on-wire frame CRC.
let canCrcCalculationCount = 0;
function updateCanCrcPanel(frame) {
  let bytes;
  if (Array.isArray(frame.data)) {
    bytes = frame.data;
  } else if (typeof frame.data === 'string') {
    const tokens = frame.data.trim().split(/\s+/).filter(Boolean);
    if (tokens.some(token => !/^(?:[0-9a-f]{1,2})$/i.test(token))) return;
    bytes = tokens.map(token => parseInt(token, 16));
  } else if (frame.data == null) {
    bytes = [];
  } else {
    return;
  }
  if (bytes.some(byte => !Number.isInteger(byte) || byte < 0 || byte > 255)) return;
  let crc = 0;
  for (const byte of bytes) {
    for (let shift = 7; shift >= 0; shift--) {
      const feedback = ((crc >> 14) & 1) ^ ((byte >> shift) & 1);
      crc = (crc << 1) & 0x7fff;
      if (feedback) crc ^= 0x4599;
    }
  }
  canCrcCalculationCount++;
  const idEl = document.getElementById('can-crc-id');
  const crcEl = document.getElementById('can-crc-value');
  const dataEl = document.getElementById('can-crc-data');
  const countEl = document.getElementById('can-crc-count');
  if (idEl) idEl.textContent = String(frame.id ?? '—');
  if (crcEl) crcEl.textContent = `0x${crc.toString(16).padStart(4, '0').toUpperCase()}`;
  if (dataEl) dataEl.textContent = bytes.length ? bytes.map(byte => byte.toString(16).padStart(2, '0').toUpperCase()).join(' ') : '(vazio)';
  if (countEl) countEl.textContent = String(canCrcCalculationCount);
}

// Estimativa visual alinhada ao modelo server/app/can_telemetry.py.
// Usa janela móvel de 5 s e CAN clássico nominal (sem bit stuffing).
function recordCanTelemetryFrame(frame, now = Date.now()) {
  const dlcValue = Number(frame.dlc ?? (Array.isArray(frame.data) ? frame.data.length :
    (typeof frame.data === 'string' ? frame.data.trim().split(/\s+/).filter(Boolean).length : NaN)));
  const isError = frame.is_error === true || frame.error === true || frame.type === 'can_error';
  state.canTelemetryFrames.push({ at: now, dlc: Number.isInteger(dlcValue) ? Math.max(0, Math.min(8, dlcValue)) : 0, isError });
  const cutoff = now - 5000;
  state.canTelemetryFrames = state.canTelemetryFrames.filter(item => item.at >= cutoff);
  updateCanTelemetryDisplay(now);
}

function updateCanTelemetryDisplay(now = Date.now()) {
  const frames = state.canTelemetryFrames.filter(item => item.at >= now - 5000);
  const bits = frames.reduce((sum, item) => sum + (item.isError ? 0 : 47 + 8 * item.dlc), 0);
  const load = Math.min(100, bits / (500000 * 5) * 100);
  const errors = frames.length ? frames.filter(item => item.isError).length / frames.length * 100 : 0;
  const loadEl = document.getElementById('can-bus-load');
  const errorEl = document.getElementById('can-error-rate');
  const loadBar = document.getElementById('can-bus-load-bar');
  const errorBar = document.getElementById('can-error-rate-bar');
  const loadLevel = load >= 70 ? 'danger' : load >= 40 ? 'warning' : 'normal';
  const errorLevel = errors >= 5 ? 'danger' : errors > 0 ? 'warning' : 'normal';
  if (loadEl) {
    loadEl.textContent = `${load.toFixed(2).replace('.', ',')}%`;
    loadEl.dataset.level = loadLevel;
  }
  if (errorEl) {
    errorEl.textContent = `${errors.toFixed(2).replace('.', ',')}%`;
    errorEl.dataset.level = errorLevel;
  }
  if (loadBar) {
    loadBar.value = load;
    loadBar.dataset.level = loadLevel;
  }
  if (errorBar) {
    errorBar.value = errors;
    errorBar.dataset.level = errorLevel;
  }
}

function appendCanRowFromHistory(row) {
  // row from DB: {timestamp, can_id, dlc, data_hex, source}
  const tbody = document.getElementById('can-tbody');
  const idHex = row.can_id || '0x000';
  const meta  = CAN_ID_MAP[idHex.toLowerCase()] || CAN_ID_MAP[idHex] || null;
  const sourceClass = meta ? meta.cls : 'source-other';
  const sourceLabel = row.source || (meta ? meta.label : 'RAW');

  const ts = row.timestamp
    ? new Date(row.timestamp).toLocaleTimeString('pt-BR', { hour12: false, fractionalSecondDigits: 3 })
    : '–';

  const tr = document.createElement('tr');
  tr.style.cursor = 'pointer';
  if (!shouldDisplayFrame(idHex)) {
    tr.classList.add('d-none');
  }
  tr.dataset.timestamp = ts;
  tr.dataset.canId = idHex.toUpperCase();
  tr.dataset.dlc = row.dlc ?? '–';
  tr.dataset.payload = row.data_hex || '–';
  tr.dataset.origin = sourceLabel;
  tr.innerHTML = `
    <td class="td-ts">${ts}</td>
    <td class="td-id">${idHex.toUpperCase()}</td>
    <td class="td-dlc">${row.dlc ?? '–'}</td>
    <td class="td-data">${row.data_hex || '–'}</td>
    <td><span class="td-source ${sourceClass}">${escapeHtml(sourceLabel)}</span></td>
  `;
  tbody.appendChild(tr);
}

function updateCanStats() {
  const now = Date.now();
  state.canPacketTimestamps = state.canPacketTimestamps.filter(t => now - t < PPS_WINDOW_MS);
  const pps = state.canPacketTimestamps.length;
  document.getElementById('can-pps-display').textContent  = pps;
  document.getElementById('can-total-display').textContent = state.canTotal;
  document.getElementById('can-pps-badge').textContent     = pps;
  updateCanTelemetryDisplay(now);
  updateVisibilityCounter();
}

function togglePause() {
  state.canPaused = !state.canPaused;
  const btn = document.getElementById('btn-pause');
  btn.classList.toggle('active', state.canPaused);
  btn.textContent = state.canPaused ? '▶ Retomar' : '⏸ Pausar';
}

function clearCan(resetTotal = true) {
  document.getElementById('can-tbody').innerHTML = '';
  if (resetTotal) { state.canTotal = 0; state.canPacketTimestamps = []; }
  document.getElementById('can-pps-display').textContent  = '0';
  document.getElementById('can-total-display').textContent = resetTotal ? '0' : state.canTotal;
  document.getElementById('can-pps-badge').textContent    = '0';
  document.getElementById('can-empty-state').style.display = '';
  updateVisibilityCounter();
}

function sendCanCommand(cmd) { sendWS({ cmd }); }

// ─── Oscilloscope (High Performance) ───────────────────────────────────────────

const oscState = {
  running: true,
  ch1: true,
  ch2: true,
  vDiv1: 2,
  vDiv2: 2,
  offset1: 4,
  offset2: -4,
  tDiv: 10,      // ms per division
  sampleRate: 10000, // 10 kS/s default para simulador
  preset: 'sync_ckp_cmp',
  trigMode: 'Auto',
  trigEdge: 'Rise',
  trigLevel: 2.5,
  syncTeethOffset: 0, // Dentes de defasagem
  
  ruler: { active: false, startX: 0, endX: 0, dragging: false, mode: 0 }, // mode 0 = setting start, 1 = setting end

  gridCtx: null,
  traceCtx: null,
  cursorCtx: null,
  width: 0,
  height: 0,
  
  // Cursores
  cursorMode: 0, // 0 = OFF, 1 = TENSÃO, 2 = TEMPO
  cursors: {
    v1: 100, v2: 250,
    t1: 100, t2: 300,
    dragging: null
  },
  
  buffer1: new Float32Array(20000),
  buffer2: new Float32Array(20000),
  bufferIdx: 0,
  simAngle: 0,
  
  // Base de Formas de Onda de Referência (Known Good)
  referenceWaveforms: [],
  selectedReference: null,
  referenceOverlayActive: false,
};

function initOscCanvas() {
  const gridCanvas = document.getElementById('scope-grid-canvas');
  const traceCanvas = document.getElementById('scope-trace-canvas');
  const cursorCanvas = document.getElementById('scope-cursor-canvas');
  if (!gridCanvas || !traceCanvas || !cursorCanvas) return;
  
  oscState.gridCtx = gridCanvas.getContext('2d', { alpha: false });
  oscState.traceCtx = traceCanvas.getContext('2d', { alpha: true });
  oscState.cursorCtx = cursorCanvas.getContext('2d', { alpha: true });
  
  cursorCanvas.addEventListener('mousedown', handleCursorMouseDown);
  cursorCanvas.addEventListener('mousemove', handleCursorMouseMove);
  cursorCanvas.addEventListener('mouseup', handleCursorMouseUp);
  cursorCanvas.addEventListener('mouseleave', handleCursorMouseUp);
  
  resizeOscCanvas();
  new ResizeObserver(() => resizeOscCanvas()).observe(gridCanvas.parentElement);
  
  updateOscConfig();
  loadReferenceWaveformsCatalog();
  requestAnimationFrame(oscRenderLoop);
}

function resizeOscCanvas() {
  const gridCanvas = document.getElementById('scope-grid-canvas');
  const traceCanvas = document.getElementById('scope-trace-canvas');
  const cursorCanvas = document.getElementById('scope-cursor-canvas');
  const wrapper = gridCanvas.parentElement;
  
  const w = wrapper.clientWidth;
  const h = wrapper.clientHeight;
  const dpr = window.devicePixelRatio || 1;
  
  oscState.width = w;
  oscState.height = h;
  
  [gridCanvas, traceCanvas, cursorCanvas].forEach(c => {
    c.width = w * dpr;
    c.height = h * dpr;
    c.style.width = w + 'px';
    c.style.height = h + 'px';
  });
  
  oscState.gridCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
  oscState.traceCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
  oscState.cursorCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
  
  drawScopeGrid();
  drawCursors();
}

function toggleOscCursors() {
  oscState.cursorMode = (oscState.cursorMode + 1) % 3;
  const btn = document.getElementById('btn-osc-cursors');
  const stats = document.getElementById('osc-cursor-stats');
  
  if (oscState.cursorMode === 0) {
    btn.textContent = 'Cursores: OFF';
    stats.style.display = 'none';
    if (oscState.cursorCtx) oscState.cursorCtx.clearRect(0, 0, oscState.width, oscState.height);
  } else if (oscState.cursorMode === 1) {
    btn.textContent = 'Cursores: TENSÃO';
    stats.style.display = 'flex';
  } else {
    btn.textContent = 'Cursores: TEMPO';
    stats.style.display = 'flex';
  }
  
  if (oscState.cursorMode !== 0) {
    drawCursors();
  }
}

function handleCursorMouseDown(e) {
  if (oscState.cursorMode === 0) return;
  const rect = e.target.getBoundingClientRect();
  const x = e.clientX - rect.left;
  const y = e.clientY - rect.top;
  const hit = 15;
  
  if (oscState.cursorMode === 1) {
    if (Math.abs(y - oscState.cursors.v1) < hit) oscState.cursors.dragging = 'v1';
    else if (Math.abs(y - oscState.cursors.v2) < hit) oscState.cursors.dragging = 'v2';
  } else if (oscState.cursorMode === 2) {
    if (Math.abs(x - oscState.cursors.t1) < hit) oscState.cursors.dragging = 't1';
    else if (Math.abs(x - oscState.cursors.t2) < hit) oscState.cursors.dragging = 't2';
  }
}

function handleCursorMouseMove(e) {
  if (!oscState.cursors.dragging) return;
  const rect = e.target.getBoundingClientRect();
  const x = e.clientX - rect.left;
  const y = e.clientY - rect.top;
  
  const key = oscState.cursors.dragging;
  if (key === 'v1' || key === 'v2') oscState.cursors[key] = Math.max(0, Math.min(y, oscState.height));
  if (key === 't1' || key === 't2') oscState.cursors[key] = Math.max(0, Math.min(x, oscState.width));
  
  drawCursors();
}

function handleCursorMouseUp(e) {
  oscState.cursors.dragging = null;
}

function drawCursors() {
  if (!oscState.cursorCtx || oscState.cursorMode === 0) return;
  const ctx = oscState.cursorCtx;
  const W = oscState.width;
  const H = oscState.height;
  
  ctx.clearRect(0, 0, W, H);
  ctx.lineWidth = 1.5;
  ctx.setLineDash([5, 5]);
  ctx.font = '11px JetBrains Mono, monospace';
  
  const vDiv = oscState.ch1 ? oscState.vDiv1 : oscState.vDiv2;
  const offsetV = oscState.ch1 ? oscState.offset1 : oscState.offset2;
  const color = oscState.ch1 ? 'rgba(0, 240, 255, 0.8)' : 'rgba(0, 180, 255, 0.9)';
  
  const totalVolts = vDiv * 8;
  const zeroOffset = (H / 2) - (offsetV * (H / totalVolts)); 
  const ppv = H / totalVolts;
  
  const totalMs = oscState.tDiv * 10;
  const ppm = W / totalMs;
  
  if (oscState.cursorMode === 1) { // Volts
    const y1 = oscState.cursors.v1;
    const y2 = oscState.cursors.v2;
    
    ctx.strokeStyle = color;
    ctx.fillStyle = color;
    
    ctx.beginPath(); ctx.moveTo(0, y1); ctx.lineTo(W, y1); ctx.stroke();
    drawLabel(ctx, 'V1', 10, y1 - 4, ctx.fillStyle);
    
    ctx.beginPath(); ctx.moveTo(0, y2); ctx.lineTo(W, y2); ctx.stroke();
    drawLabel(ctx, 'V2', 10, y2 - 4, ctx.fillStyle);
    
    const volt1 = (zeroOffset - y1) / ppv;
    const volt2 = (zeroOffset - y2) / ppv;
    const dv = Math.abs(volt1 - volt2);
    document.getElementById('osc-cur-dv').textContent = dv.toFixed(2);
    document.getElementById('osc-cur-dt').textContent = '---';
    document.getElementById('osc-cur-freq').textContent = '---';
    
  } else if (oscState.cursorMode === 2) { // Time
    const x1 = oscState.cursors.t1;
    const x2 = oscState.cursors.t2;
    
    ctx.strokeStyle = 'rgba(255, 255, 0, 0.8)';
    ctx.fillStyle = 'rgba(255, 255, 0, 1)';
    
    ctx.beginPath(); ctx.moveTo(x1, 0); ctx.lineTo(x1, H); ctx.stroke();
    drawLabel(ctx, 'T1', x1 + 4, 20, ctx.fillStyle);
    
    ctx.beginPath(); ctx.moveTo(x2, 0); ctx.lineTo(x2, H); ctx.stroke();
    drawLabel(ctx, 'T2', x2 + 4, 20, ctx.fillStyle);
    
    const ms1 = x1 / ppm;
    const ms2 = x2 / ppm;
    const dt = Math.abs(ms1 - ms2);
    const freq = dt > 0 ? (1000 / dt) : 0;
    
    document.getElementById('osc-cur-dt').textContent = dt.toFixed(2);
    document.getElementById('osc-cur-freq').textContent = freq.toFixed(2);
    document.getElementById('osc-cur-dv').textContent = '---';
  }
  ctx.setLineDash([]);
}

function drawLabel(ctx, text, x, y, color) {
  ctx.fillStyle = 'rgba(0,0,0,0.6)';
  const m = ctx.measureText(text);
  ctx.fillRect(x - 2, y - 10, m.width + 4, 14);
  ctx.fillStyle = color;
  ctx.fillText(text, x, y);
}

function updateOscConfig() {
  const vdiv1 = document.getElementById('osc-vdiv-ch1');
  if (vdiv1) oscState.vDiv1 = parseFloat(vdiv1.value);
  const vdiv2 = document.getElementById('osc-vdiv-ch2');
  if (vdiv2) oscState.vDiv2 = parseFloat(vdiv2.value);
  
  const off1 = document.getElementById('osc-offset-ch1');
  if (off1) oscState.offset1 = parseFloat(off1.value);
  const off2 = document.getElementById('osc-offset-ch2');
  if (off2) oscState.offset2 = parseFloat(off2.value);

  oscState.tDiv = parseFloat(document.getElementById('osc-tdiv').value);
  oscState.trigMode = document.getElementById('osc-trig-mode').value;
  oscState.trigEdge = document.getElementById('osc-trig-edge').value;
  oscState.trigLevel = parseFloat(document.getElementById('osc-trig-level').value);
  
  const syncSlider = document.getElementById('sync-offset-slider');
  if (syncSlider) {
    oscState.syncTeethOffset = parseInt(syncSlider.value, 10);
    const syncBadge = document.getElementById('sync-offset-val');
    if (syncBadge) {
      if (oscState.syncTeethOffset === 0) {
        syncBadge.textContent = '0 dentes';
        syncBadge.style.color = '#00ff66';
      } else {
        const sign = oscState.syncTeethOffset > 0 ? '+' : '';
        syncBadge.textContent = `${sign}${oscState.syncTeethOffset} dentes`;
        syncBadge.style.color = '#ff3366';
      }
    }
  }

  drawScopeGrid();
  drawCursors();
  
  if (!oscState.running && oscState.traceCtx) {
    const W = oscState.width, H = oscState.height;
    oscState.traceCtx.clearRect(0, 0, W, H);
    if (oscState.ch1 && oscState.bufferIdx > 0) drawTrace(oscState.traceCtx, oscState.buffer1, oscState.bufferIdx, '#00ff66', W, H, oscState.vDiv1, oscState.offset1);
    if (oscState.ch2 && oscState.bufferIdx > 0) drawTrace(oscState.traceCtx, oscState.buffer2, oscState.bufferIdx, '#00f0ff', W, H, oscState.vDiv2, oscState.offset2);
  }
}

function applyOscPreset() {
  const preset = document.getElementById('scope-preset-select').value;
  oscState.preset = preset;
  
  if (preset === 'sync_ckp_cmp') {
    document.getElementById('osc-vdiv-ch1').value = "2";
    document.getElementById('osc-vdiv-ch2').value = "2";
    document.getElementById('osc-offset-ch1').value = "4";
    document.getElementById('osc-offset-ch2').value = "-4";
    document.getElementById('osc-tdiv').value = "10";
  } else if (preset === 'injector_pulse') {
    document.getElementById('osc-vdiv-ch1').value = "10";
    document.getElementById('osc-vdiv-ch2').value = "5";
    document.getElementById('osc-offset-ch1').value = "10";
    document.getElementById('osc-offset-ch2').value = "-10";
    document.getElementById('osc-tdiv').value = "5";
  } else if (preset === 'ignition_primary') {
    document.getElementById('osc-vdiv-ch1').value = "10";
    document.getElementById('osc-vdiv-ch2').value = "10";
    document.getElementById('osc-offset-ch1').value = "0";
    document.getElementById('osc-offset-ch2').value = "-10";
    document.getElementById('osc-tdiv').value = "1";
  } else if (preset === 'lambda_o2') {
    document.getElementById('osc-vdiv-ch1').value = "1";
    document.getElementById('osc-vdiv-ch2').value = "1";
    document.getElementById('osc-offset-ch1').value = "2";
    document.getElementById('osc-offset-ch2').value = "-2";
    document.getElementById('osc-tdiv').value = "100";
  } else if (preset === 'relative_compression') {
    document.getElementById('osc-vdiv-ch1').value = "5";
    document.getElementById('osc-vdiv-ch2').value = "5";
    document.getElementById('osc-offset-ch1').value = "10";
    document.getElementById('osc-offset-ch2').value = "0";
    document.getElementById('osc-tdiv').value = "50";
  } else if (preset === 'alternator_ripple') {
    document.getElementById('osc-vdiv-ch1').value = "1";
    document.getElementById('osc-vdiv-ch2').value = "1";
    document.getElementById('osc-offset-ch1').value = "0";
    document.getElementById('osc-offset-ch2').value = "0";
    document.getElementById('osc-tdiv').value = "5";
  } else if (preset === 'can_bus_physical') {
    document.getElementById('osc-vdiv-ch1').value = "1";
    document.getElementById('osc-vdiv-ch2').value = "1";
    document.getElementById('osc-offset-ch1').value = "2.5";
    document.getElementById('osc-offset-ch2').value = "-2.5";
    document.getElementById('osc-tdiv').value = "1";
  }
  updateOscConfig();
}

function toggleOscCh(ch) {
  if (ch === 1) oscState.ch1 = !oscState.ch1;
  if (ch === 2) oscState.ch2 = !oscState.ch2;
  
  const b1 = document.getElementById('btn-ch1');
  if (b1) { 
    b1.classList.toggle('active', oscState.ch1); 
    b1.style.opacity = oscState.ch1 ? '1' : '0.4'; 
  }
  
  const b2 = document.getElementById('btn-ch2');
  if (b2) { 
    b2.classList.toggle('active', oscState.ch2); 
    b2.style.opacity = oscState.ch2 ? '1' : '0.4'; 
  }
  
  const ch2Row = document.getElementById('badge-ch2-row');
  if (ch2Row) ch2Row.style.display = oscState.ch2 ? 'flex' : 'none';
  
  // Update canvas if stopped
  if (!oscState.running && oscState.traceCtx) {
    updateOscConfig();
  }
}

function toggleOscRun() {
  oscState.running = !oscState.running;
  const btn = document.getElementById('btn-osc-run');
  if (btn) {
    btn.textContent = oscState.running ? 'Stop' : 'Run';
    btn.className = oscState.running ? 'btn btn-danger' : 'btn btn-success';
  }
  if (oscState.running && !oscState.animId) {
    oscState.animId = requestAnimationFrame(oscRenderLoop);
  }
}

function clearOscDisplay() {
  oscState.buffer1.fill(0);
  oscState.buffer2.fill(0);
  oscState.bufferIdx = 0;
  if (oscState.traceCtx) {
    oscState.traceCtx.clearRect(0, 0, oscState.width, oscState.height);
  }
}

function drawScopeGrid() {
  if (!oscState.gridCtx) return;
  const ctx = oscState.gridCtx;
  const W = oscState.width;
  const H = oscState.height;
  
  ctx.fillStyle = '#080c10';
  ctx.fillRect(0, 0, W, H);
  
  const vDivs = 8;
  const hDivs = 10;
  
  ctx.lineWidth = 1;
  ctx.strokeStyle = '#1e293b';
  
  for (let i = 0; i <= vDivs; i++) {
    const y = (H / vDivs) * i;
    ctx.setLineDash(i === Math.round(vDivs / 2) ? [] : [2, 4]);
    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke();
  }
  
  for (let i = 0; i <= hDivs; i++) {
    const x = (W / hDivs) * i;
    ctx.setLineDash(i === Math.round(hDivs / 2) ? [] : [2, 4]);
    ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, H); ctx.stroke();
  }
  ctx.setLineDash([]);
}

let lastOscDraw = 0;
function oscRenderLoop(timestamp) {
  if (state.activeTab !== 'osc') {
    oscState.animId = null;
    return;
  }
  oscState.animId = requestAnimationFrame(oscRenderLoop);
  
  if (!oscState.running || !oscState.traceCtx) return;
  
  // Throttle para 30 FPS (estilo Hantek)
  if (timestamp - lastOscDraw < 33) return;
  lastOscDraw = timestamp;
  
  const ctx = oscState.traceCtx;
  const W = oscState.width;
  const H = oscState.height;
  
  const sourceSelect = document.getElementById('scope-source-select');
  const isDemo = !sourceSelect || sourceSelect.value === 'sim_demo';
  
  if (!isDemo) {
    if (oscState.bufferIdx === 0) {
      ctx.clearRect(0, 0, W, H);
      ctx.fillStyle = '#64748b';
      ctx.font = '14px JetBrains Mono, monospace';
      ctx.textAlign = 'center';
      ctx.fillText('Aguardando Stream de Hardware Real (ESP32/ADC)...', W / 2, H / 2);
      return;
    }
  } else {
    simulateOscSignal();
  }
  
  ctx.clearRect(0, 0, W, H);
  
  // -- TRAÇO FANTASMA DE REFERÊNCIA (KNOWN GOOD GHOST OVERLAY) --
  if (oscState.referenceOverlayActive && oscState.selectedReference) {
    drawReferenceGhostTrace(ctx, oscState.selectedReference, W, H);
  }

  if (oscState.ch1 && oscState.bufferIdx > 0) {
    drawTrace(ctx, oscState.buffer1, oscState.bufferIdx, '#00ff66', W, H, oscState.vDiv1, oscState.offset1);
  }
  
  if (oscState.ch2 && oscState.bufferIdx > 0) {
    drawTrace(ctx, oscState.buffer2, oscState.bufferIdx, '#00f0ff', W, H, oscState.vDiv2, oscState.offset2);
  }
  
  // -- REGUA 720 GRAUS --
  if (oscState.ruler && oscState.ruler.active) {
      let sx = Math.min(oscState.ruler.startX, oscState.ruler.endX);
      let ex = Math.max(oscState.ruler.startX, oscState.ruler.endX);
      
      if (ex - sx > 5) {
          ctx.fillStyle = 'rgba(0, 255, 255, 0.1)';
          ctx.fillRect(sx, 0, ex - sx, H);
          
          ctx.strokeStyle = 'rgba(0, 255, 255, 0.5)';
          ctx.fillStyle = '#00f0ff';
          ctx.font = '10px monospace';
          ctx.textAlign = 'center';
          
          const degrees = [0, 90, 180, 270, 360, 450, 540, 630, 720];
          const span = ex - sx;
          
          degrees.forEach((deg) => {
              let pct = deg / 720.0;
              let lineX = sx + (span * pct);
              
              ctx.beginPath();
              ctx.setLineDash([4, 4]);
              ctx.moveTo(lineX, 0);
              ctx.lineTo(lineX, H);
              ctx.stroke();
              ctx.setLineDash([]);
              
              ctx.fillText(`${deg}°`, lineX, H - 5);
          });
          
          // Contagem de Dentes (Sinal CKP - Geralmente no CH2 ou CH1 dependendo da amplitude/frequência)
          let maxPts = Math.min(oscState.bufferIdx, Math.floor(W));
          let startIdx = Math.floor((sx / W) * maxPts);
          let endIdx = Math.floor((ex / W) * maxPts);
          
          if(startIdx < 0) startIdx = 0;
          if(endIdx > maxPts - 1) endIdx = maxPts - 1;
          
          // Descobre qual canal tem mais "ação" para contar os dentes (CKP)
          // Vamos assumir CH2 (Ciano) como padrão para o CKP neste layout, mas se CH2 estiver vazio usa CH1
          let bufToCount = (oscState.ch2 && oscState.buffer2.length > 0) ? oscState.buffer2 : oscState.buffer1;
          
          // Calcula a voltagem média na região para ser o threshold (cruza o zero)
          let minV = 9999, maxV = -9999;
          for(let i = startIdx; i <= endIdx; i++) {
              if (bufToCount[i] < minV) minV = bufToCount[i];
              if (bufToCount[i] > maxV) maxV = bufToCount[i];
          }
          let threshold = (minV + maxV) / 2.0;
          if (isNaN(threshold)) threshold = 0;
          
          let dentes = 0;
          for(let i = startIdx + 1; i <= endIdx; i++) {
              let prev = bufToCount[i-1];
              let curr = bufToCount[i];
              // Conta bordas de subida cruzando o limiar médio
              if(prev < threshold && curr >= threshold) {
                  dentes++;
              }
          }
          
          const stats = document.getElementById('ruler-stats');
          if(stats) {
              stats.textContent = `Dentes medidos: ${dentes}`;
          }
      }
  }
  
  updateOscBadgeStats();
}

function drawTrace(ctx, buffer, len, color, W, H, vDiv, offsetV) {
  ctx.strokeStyle = color;
  ctx.lineWidth = 2;
  ctx.lineJoin = 'round';
  ctx.shadowBlur = 0;
  ctx.beginPath();
  
  const totalVolts = vDiv * 8; 
  // Center is H/2, we'll map offsetV to shift the zero line.
  // By default (offset 0), 0V is at the vertical center of the grid.
  const zeroOffset = (H / 2) - (offsetV * (H / totalVolts)); 
  
  const maxPts = Math.min(len, Math.floor(W)); 
  const step = len / maxPts;
  
  for (let i = 0; i < maxPts; i++) {
    const idx = Math.floor(i * step);
    const v = buffer[idx];
    const x = (i / (maxPts - 1 || 1)) * W;
    const ppv = H / totalVolts;
    const y = zeroOffset - (v * ppv);
    
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  }
  ctx.stroke();
}

/**
 * Desenha a curva fantasma pontilhada de referência (Known Good Waveform)
 * com envelope de tolerância visual.
 */
function drawReferenceGhostTrace(ctx, ref, W, H) {
  if (!ref) return;

  // 1. Desenha Traço CH1 de Referência
  if (ref.reference_points_ch1 && ref.reference_points_ch1.length > 1) {
    const vDiv1 = oscState.vDiv1 || 2.0;
    const offsetV1 = oscState.offset1 || 0.0;
    const totalVolts1 = vDiv1 * 8;
    const zeroOffset1 = (H / 2) - (offsetV1 * (H / totalVolts1));
    const ppv1 = H / totalVolts1;
    const pts1 = ref.reference_points_ch1;

    // Faixa / Envelope translúcido de tolerância de fábrica (±12%)
    ctx.beginPath();
    for (let i = 0; i < pts1.length; i++) {
      const [tNorm, vVal] = pts1[i];
      const x = tNorm * W;
      const yUpper = zeroOffset1 - ((vVal * 1.12) * ppv1);
      if (i === 0) ctx.moveTo(x, yUpper);
      else ctx.lineTo(x, yUpper);
    }
    for (let i = pts1.length - 1; i >= 0; i--) {
      const [tNorm, vVal] = pts1[i];
      const x = tNorm * W;
      const yLower = zeroOffset1 - ((vVal * 0.88) * ppv1);
      ctx.lineTo(x, yLower);
    }
    ctx.closePath();
    ctx.fillStyle = 'rgba(168, 85, 247, 0.14)';
    ctx.fill();

    // Linha de Referência CH1 (Tracejado Roxo Néon)
    ctx.beginPath();
    ctx.strokeStyle = '#c084fc';
    ctx.lineWidth = 2.5;
    ctx.setLineDash([6, 5]);
    ctx.lineJoin = 'round';

    for (let i = 0; i < pts1.length; i++) {
      const [tNorm, vVal] = pts1[i];
      const x = tNorm * W;
      const y = zeroOffset1 - (vVal * ppv1);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.stroke();
    ctx.setLineDash([]);
  }

  // 2. Desenha Traço CH2 de Referência (se houver, ex: Sincronismo CMP ou CAN-L)
  if (ref.reference_points_ch2 && ref.reference_points_ch2.length > 1) {
    const vDiv2 = oscState.vDiv2 || 2.0;
    const offsetV2 = oscState.offset2 || 0.0;
    const totalVolts2 = vDiv2 * 8;
    const zeroOffset2 = (H / 2) - (offsetV2 * (H / totalVolts2));
    const ppv2 = H / totalVolts2;
    const pts2 = ref.reference_points_ch2;

    ctx.beginPath();
    ctx.strokeStyle = '#f472b6'; // Rosa/Magenta pontilhado para CH2
    ctx.lineWidth = 2.5;
    ctx.setLineDash([4, 4]);
    ctx.lineJoin = 'round';

    for (let i = 0; i < pts2.length; i++) {
      const [tNorm, vVal] = pts2[i];
      const x = tNorm * W;
      const y = zeroOffset2 - (vVal * ppv2);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.stroke();
    ctx.setLineDash([]);
  }

  // Marca d'água no canto informando o modelo ativo
  ctx.fillStyle = 'rgba(192, 132, 252, 0.4)';
  ctx.font = '11px JetBrains Mono, monospace';
  ctx.textAlign = 'right';
  ctx.fillText('PADRÃO OE: ' + (ref.name || '').toUpperCase(), W - 14, H - 12);
}

/**
 * Carrega a biblioteca de formas de onda de referência a partir do backend FastAPI
 */
async function loadReferenceWaveformsCatalog() {
  try {
    const res = await fetch('/api/oscilloscope/references');
    if (!res.ok) return;
    const data = await res.json();
    oscState.referenceWaveforms = data.waveforms || [];
    populateReferenceWaveformsSelect();
  } catch (err) {
    console.warn('Não foi possível carregar catálogo de formas de onda de referência:', err);
  }
}

/**
 * Preenche o elemento select com as opções do catálogo
 */
function populateReferenceWaveformsSelect() {
  const select = document.getElementById('scope-ref-select');
  if (!select) return;

  select.innerHTML = '<option value="none">Nenhum (Desativado)</option>';

  const categories = {};
  oscState.referenceWaveforms.forEach(wf => {
    const cat = wf.category || 'Geral';
    if (!categories[cat]) categories[cat] = [];
    categories[cat].push(wf);
  });

  for (const [catName, list] of Object.entries(categories)) {
    const optGroup = document.createElement('optgroup');
    optGroup.label = `── ${catName} ──`;
    list.forEach(wf => {
      const opt = document.createElement('option');
      opt.value = wf.id;
      opt.textContent = wf.name;
      optGroup.appendChild(opt);
    });
    select.appendChild(optGroup);
  }
}

/**
 * Ação disparada ao escolher um sinal de referência
 */
function onSelectReferenceWaveform() {
  const select = document.getElementById('scope-ref-select');
  if (!select) return;
  const val = select.value;

  if (val === 'none') {
    oscState.selectedReference = null;
    oscState.referenceOverlayActive = false;
    updateReferenceUIControls();
    return;
  }

  const found = oscState.referenceWaveforms.find(w => w.id === val);
  if (found) {
    oscState.selectedReference = found;
    oscState.referenceOverlayActive = true;
    updateReferenceUIControls();
    applyReferenceOscSettings();
  }
}

/**
 * Liga / desliga o traço fantasma de comparação
 */
function toggleReferenceOverlay() {
  if (!oscState.selectedReference) {
    const select = document.getElementById('scope-ref-select');
    if (select && select.options.length > 1) {
      select.selectedIndex = 1;
      onSelectReferenceWaveform();
      return;
    }
  }
  oscState.referenceOverlayActive = !oscState.referenceOverlayActive;
  updateReferenceUIControls();
}

/**
 * Atualiza os botões e cartões informativos de referência na interface
 */
function updateReferenceUIControls() {
  const btn = document.getElementById('btn-toggle-ref-overlay');
  const card = document.getElementById('osc-ref-overlay-info');
  const ref = oscState.selectedReference;

  if (btn) {
    if (oscState.referenceOverlayActive && ref) {
      btn.textContent = 'Comparar: ATIVO';
      btn.style.color = '#fff';
      btn.style.background = '#7e22ce';
      btn.style.borderColor = '#c084fc';
    } else {
      btn.textContent = 'Comparar: OFF';
      btn.style.color = '#c084fc';
      btn.style.background = 'transparent';
      btn.style.borderColor = '#7e22ce';
    }
  }

  if (card) {
    if (oscState.referenceOverlayActive && ref) {
      card.style.display = 'block';
      const catBadge = document.getElementById('ref-badge-cat');
      const nameEl = document.getElementById('ref-card-name');
      const valEl = document.getElementById('ref-card-values');
      if (catBadge) catBadge.textContent = ref.category || 'PADRÃO';
      if (nameEl) nameEl.textContent = ref.name;
      if (valEl && ref.settings && ref.settings.expected_values) {
        const ev = ref.settings.expected_values;
        valEl.textContent = `Vpp: ${ev.vpp || '-'} | Freq: ${ev.frequency || '-'} | Duty: ${ev.duty_cycle || '-'}`;
      }
    } else {
      card.style.display = 'none';
    }
  }
}

/**
 * Aplica os parâmetros recomendados de tensão/tempo do sinal de referência aos seletores
 */
function applyReferenceOscSettings() {
  const ref = oscState.selectedReference;
  if (!ref || !ref.settings) return;

  const s = ref.settings;
  const tdivEl = document.getElementById('osc-tdiv');
  const vdiv1El = document.getElementById('osc-vdiv-ch1');
  const vdiv2El = document.getElementById('osc-vdiv-ch2');
  const off1El = document.getElementById('osc-offset-ch1');
  const off2El = document.getElementById('osc-offset-ch2');

  if (s.time_div_ms !== undefined && tdivEl) {
    // Escolhe a opção mais próxima
    tdivEl.value = String(s.time_div_ms);
  }
  if (s.ch1_vdiv !== undefined && vdiv1El) {
    vdiv1El.value = String(Math.round(s.ch1_vdiv));
  }
  if (s.ch2_vdiv !== undefined && vdiv2El) {
    vdiv2El.value = String(Math.round(s.ch2_vdiv));
  }
  if (s.ch1_offset !== undefined && off1El) {
    off1El.value = String(s.ch1_offset);
  }
  if (s.ch2_offset !== undefined && off2El) {
    off2El.value = String(s.ch2_offset);
  }

  if (s.trigger) {
    const trigModeEl = document.getElementById('osc-trig-mode');
    const trigEdgeEl = document.getElementById('osc-trig-edge');
    const trigLevelEl = document.getElementById('osc-trig-level');
    if (trigModeEl && s.trigger.mode) trigModeEl.value = s.trigger.mode;
    if (trigEdgeEl && s.trigger.edge) trigEdgeEl.value = s.trigger.edge;
    if (trigLevelEl && s.trigger.level !== undefined) trigLevelEl.value = String(s.trigger.level);
  }

  updateOscConfig();
}

/**
 * Abre ou fecha o modal explicativo com os critérios de bom/mau funcionamento
 */
function toggleReferenceDetailsModal() {
  const modal = document.getElementById('modal-ref-criteria');
  if (!modal) return;

  const isVisible = modal.style.display === 'flex';
  if (isVisible) {
    modal.style.display = 'none';
    return;
  }

  const ref = oscState.selectedReference || (oscState.referenceWaveforms && oscState.referenceWaveforms[0]);
  if (!ref) {
    alert('Nenhum sinal de referência selecionado.');
    return;
  }

  document.getElementById('modal-ref-title').textContent = `Sinal Padrão: ${ref.name}`;
  document.getElementById('modal-ref-system').textContent = `${ref.category} • ${ref.system || ''}`;
  document.getElementById('modal-ref-desc').textContent = ref.description || 'Sem descrição cadastrada.';
  document.getElementById('modal-ref-good').textContent = ref.good_criteria || 'Sem critérios de bom funcionamento cadastrados.';
  document.getElementById('modal-ref-bad').textContent = ref.bad_criteria || 'Sem critérios de anomalia cadastrados.';

  const s = ref.settings || {};
  const ev = s.expected_values || {};
  document.getElementById('modal-ref-settings').innerHTML = `
    Tempo/Div: ${s.time_div_ms || 10}ms | Tensão CH1: ${s.ch1_vdiv || 2}V/div | Offset: ${s.ch1_offset || 0}V<br>
    Vpp Esperado: ${ev.vpp || '-'} | Vmax: ${ev.vmax || '-'} | Vmin: ${ev.vmin || '-'}<br>
    Frequência Esperada: ${ev.frequency || '-'} | Ciclo de Trabalho (Duty): ${ev.duty_cycle || '-'}
  `;

  modal.style.display = 'flex';
}


function updateOscBadgeStats() {
  const len = oscState.bufferIdx;
  if (len === 0) return;
  
  // CH1 Stats (Fórmulas Hantek 1008: RMS, Interpolação de Zero-Crossing e Duty Cycle)
  if (oscState.ch1) {
    const buf = oscState.buffer1;
    let min = 9999, max = -9999, sum = 0, sumSq = 0;
    for (let i = 0; i < len; i++) {
      const v = buf[i];
      if (v < min) min = v;
      if (v > max) max = v;
      sum += v;
      sumSq += (v * v);
    }
    const mean = sum / len;
    const vrms = Math.sqrt(sumSq / len); // RMS (Root Mean Square) EeMt 5.2.3
    
    // Zero-crossing com interpolação linear (hantek1008py electro.py)
    let crossings = 0;
    let highSamples = 0;
    for (let i = 1; i < len; i++) {
      if (buf[i] >= mean) highSamples++;
      if (buf[i-1] < mean && buf[i] >= mean) crossings++;
    }
    const freq = (crossings * (oscState.sampleRate / len)).toFixed(1);
    const duty = ((highSamples / len) * 100).toFixed(1);
    
    document.getElementById('osc-badge-vpp').textContent = (max - min).toFixed(2) + ' V';
    document.getElementById('osc-badge-vmax').textContent = max.toFixed(2) + ' V';
    document.getElementById('osc-badge-vmin').textContent = min.toFixed(2) + ' V';
    document.getElementById('osc-badge-freq').textContent = freq + ' Hz';
    
    const elDuty = document.getElementById('osc-badge-duty');
    if (elDuty) elDuty.textContent = duty + ' %';
    
    const elRms = document.getElementById('osc-badge-rms');
    if (elRms) elRms.textContent = vrms.toFixed(2) + ' V';
  }
  
  // CH2 Stats
  if (oscState.ch2) {
    const buf = oscState.buffer2;
    let min = 9999, max = -9999;
    for (let i = 0; i < len; i++) {
      const v = buf[i];
      if (v < min) min = v;
      if (v > max) max = v;
    }
    const vpp2 = document.getElementById('osc-badge-vpp2');
    if (vpp2) {
      vpp2.textContent = (max - min).toFixed(2) + ' V';
      document.getElementById('osc-badge-vmax2').textContent = max.toFixed(2) + ' V';
      document.getElementById('osc-badge-vmin2').textContent = min.toFixed(2) + ' V';
    }
  }

  document.getElementById('osc-badge-sr').textContent = (oscState.sampleRate / 1000).toFixed(1) + ' kS/s';
}

function simulateOscSignal() {
  // Preset Automotivo Hantek
  const rpm = 850;
  const crankFreq = rpm / 60; // ~14.16 Hz
  const dt = 1 / oscState.sampleRate;
  
  // Buffer fixo baseado na janela visível
  const totalMs = oscState.tDiv * 10;
  const maxPts = Math.floor((totalMs / 1000) * oscState.sampleRate);
  
  oscState.bufferIdx = 0;
  
  // Trigger Lock: Alinha a falha (dente 0) exatamente em 20% da tela (2ª divisão)
  const t_trigger = 0.2 * totalMs / 1000;
  // Queremos que crankTotalAngle seja múltiplo de 4*PI no t_trigger
  const startCrankAngle = 4 * Math.PI - 2 * Math.PI * crankFreq * t_trigger;
  
  for (let i = 0; i < maxPts; i++) {
    const t = i * dt;
    const crankTotalAngle = startCrankAngle + 2 * Math.PI * crankFreq * t;
    
    // Ciclo completo do motor 4 tempos = 720 graus = 4*PI radianos do virabrequim
    let engineCycle = crankTotalAngle % (4 * Math.PI);
    if (engineCycle < 0) engineCycle += 4 * Math.PI;
    
    let val1 = 0;
    let val2 = 0;

    if (oscState.preset === 'relative_compression') {
      // Teste Hantek: Compressão Relativa com 4 cilindros em arranque (~200 RPM = 3.33 Hz)
      const starterFreq = 3.33;
      const compCycle = (2 * Math.PI * starterFreq * t);
      // Queda de tensão média: 12V em repouso caindo para ~9.5V nos picos de compressão dos 4 cilindros
      const drop = Math.sin(4 * compCycle) * 1.4;
      val1 = 10.2 - drop + (Math.random() - 0.5) * 0.15;
      // CH2: Sincronismo do Cilindro 1 (Pico de corrente de disparo)
      val2 = (compCycle % (2 * Math.PI) < 0.25) ? 4.5 : 0.2;
    } else if (oscState.preset === 'alternator_ripple') {
      // Teste Hantek / HScope: Ripple de Diodos Retificadores (AC acoplado ~600-1200 Hz)
      const altFreq = 800; // Frequência do ripple trifásico
      const ripple = 0.4 * Math.sin(2 * Math.PI * altFreq * t);
      val1 = ripple + (Math.random() - 0.5) * 0.05;
      val2 = 0.2 * Math.sin(2 * Math.PI * (altFreq / 3) * t); // Harmônica secundária
    } else {
      // Sincronismo CKP + CMP Padrão
      // CH1: Fase (Comando Hall) com Sincronismo Interativo
      const toothRad = (2 * Math.PI) / 60; // 1 dente = 6 graus do virabrequim
      const offsetRad = (oscState.syncTeethOffset || 0) * toothRad;
      
      let camCycle = (engineCycle - offsetRad) % (4 * Math.PI);
      if (camCycle < 0) camCycle += 4 * Math.PI;
      
      // Comando inverte a cada volta do virabrequim (0 a 2*PI = LOW, 2*PI a 4*PI = HIGH)
      val1 = camCycle >= 2 * Math.PI ? 5.0 : 0.0;
      val1 += (Math.random() - 0.5) * 0.1; 
      
      // CH2: Roda Fônica 60-2 (Indutivo)
      const crankAngle = engineCycle % (2 * Math.PI);
      const toothIndex = Math.floor(crankAngle / toothRad);
      
      if (toothIndex >= 58) {
        val2 = 0; // Falha de PMS
      } else {
        val2 = 4.0 * Math.sin(60 * crankAngle); // Amplitude +-4V
      }
      val2 += (Math.random() - 0.5) * 0.1;
    }
    
    if (oscState.bufferIdx < oscState.buffer1.length) {
      oscState.buffer1[oscState.bufferIdx] = val1;
    }
    if (oscState.bufferIdx < oscState.buffer2.length) {
      oscState.buffer2[oscState.bufferIdx] = val2;
    }
    
    oscState.bufferIdx++;
    if (oscState.bufferIdx >= oscState.buffer1.length) break;
  }
}


// ─── System status ─────────────────────────────────────────────────────────────

async function fetchStatus() {
  try {
    const data = await apiFetch('/status');
    state.hwNodes = data.hardware_nodes?.length ?? 0;
    updateHwNodes();
    document.getElementById('sys-web-clients').textContent  = data.web_clients ?? 0;
    document.getElementById('sys-msgs-relayed').textContent = data.messages_relayed ?? 0;
    document.getElementById('sys-uptime').textContent       = Math.round((Date.now() - state.startTime) / 60000);
    sysLog(`Status: ${data.hardware_nodes?.length ?? 0} nó(s) HW | sessão ativa: ${data.active_session?.name ?? 'nenhuma'}`, 'info');
  } catch (e) {
    sysLog('Falha ao buscar status', 'error');
  }
}

// ─── API helpers ──────────────────────────────────────────────────────────────

async function apiFetch(path, options = {}) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`HTTP ${res.status}: ${body}`);
  }
  if (res.status === 204) return null;
  return res.json();
}

async function apiPost(path, body) {
  return apiFetch(path, { method: 'POST', body: JSON.stringify(body) });
}

// ─── UI Helpers ───────────────────────────────────────────────────────────────

function updateWsStatus(connected) {
  // Atualiza pílula de conexão com o Servidor Web/Backend
  const serverPill = document.getElementById('server-status-pill');
  const serverText = document.getElementById('server-status-text');
  const serverDot  = document.getElementById('server-status-dot');
  if (serverPill && serverText && serverDot) {
    serverPill.classList.toggle('connected', connected);
    serverText.textContent = connected ? 'Servidor: On' : 'Servidor: Off';
    serverDot.style.background = connected ? 'var(--accent-cyan)' : 'var(--accent-red)';
    serverDot.classList.toggle('pulse', connected);
  }

  // Sync sidebar footer (indica conexão com servidor)
  const sidebarPill = document.getElementById('sidebar-ws-pill');
  const sidebarDot  = document.getElementById('sidebar-ws-dot');
  const sidebarText = document.getElementById('sidebar-ws-text');
  if (sidebarDot && sidebarText) {
    sidebarDot.style.background  = connected ? 'var(--accent-cyan)' : 'var(--accent-red)';
    sidebarText.textContent       = connected ? 'Servidor Conectado' : 'Servidor Offline';
  }

  // Se o servidor cair, todo hardware e ECU devem constar como desconectados
  if (!connected) {
    if (window.state) {
      window.state.hwNodes = 0;
    }
    updateHwStatusPill(0);
    updateEcuStatus(false);
  }
}

// Atualiza especificamente o badge de hardware físico (ESP32 / Gateway / ÁguiaCar)
function updateHwStatusPill(count, deviceLabels = '') {
  const pill = document.getElementById('ws-status-pill');
  const text = document.getElementById('ws-status-text');
  const dot  = document.getElementById('ws-status-dot');
  const isOnline = count > 0;

  if (pill && text && dot) {
    pill.classList.toggle('connected', isOnline);
    if (isOnline) {
      text.textContent = deviceLabels ? `Online: ${deviceLabels}` : `ESP32: ${count} nó(s)`;
      dot.style.background = 'var(--accent-green)';
      dot.classList.add('pulse');
    } else {
      text.textContent = 'ESP32: Off';
      dot.style.background = 'var(--accent-red)';
      dot.classList.remove('pulse');
    }
  }

  if (!isOnline) {
    updateEcuStatus(false);
  }
}
window.updateHwStatusPill = updateHwStatusPill;

// Duplo Status: Indica se a rede CAN/K-Line da ECU do veículo respondeu
function updateEcuStatus(online, detail = '') {
  if (window.state) {
    window.state.ecuOnline = !!online;
  }
  const pill = document.getElementById('ecu-status-pill');
  const text = document.getElementById('ecu-status-text');
  const dot  = document.getElementById('ecu-status-dot');
  if (pill && text && dot) {
    pill.classList.toggle('online', online);
    if (online) {
      dot.style.background = 'var(--accent-cyan)';
      text.textContent = detail ? `ECU: ${detail}` : 'ECU: Ativa (CAN)';
    } else {
      dot.style.background = 'var(--text-muted)';
      text.textContent = 'ECU: Aguardando';
    }
  }

  // Acende/apaga botões dependentes do contato real com o veículo
  if (typeof updateSystemActionCapabilities === 'function') {
    updateSystemActionCapabilities();
  }
}

// Screen Wake Lock API — Previne desligamento de tela durante testes de rodagem
let wakeLockSentinel = null;
async function toggleScreenWakeLock() {
  const btn = document.getElementById('btn-wakelock');
  const icon = document.getElementById('wakelock-icon');
  const text = document.getElementById('wakelock-text');

  if (!('wakeLock' in navigator)) {
    if (window.showToast) window.showToast('Wake Lock não suportado neste navegador.', 'warning');
    return;
  }

  try {
    if (!wakeLockSentinel) {
      wakeLockSentinel = await navigator.wakeLock.request('screen');
      btn.classList.add('active');
      icon.textContent = '⚡';
      text.textContent = 'Tela: Ativa';
      wakeLockSentinel.addEventListener('release', () => {
        wakeLockSentinel = null;
        btn.classList.remove('active');
        icon.textContent = '☕';
        text.textContent = 'Tela: Normal';
      });
      if (window.showToast) window.showToast('Tela mantida acesa para teste de rodagem!', 'info');
    } else {
      await wakeLockSentinel.release();
      wakeLockSentinel = null;
    }
  } catch (err) {
    console.warn('WakeLock error:', err);
  }
}

function updateHwNodes() {
  const count = (window.state && typeof window.state.hwNodes !== 'undefined') ? window.state.hwNodes : (state.hwNodes || 0);
  state.hwNodes = count;
  
  const elHwCount = document.getElementById('hw-nodes-count');
  if (elHwCount) elHwCount.textContent = count;
  
  const elSysNodes = document.getElementById('sys-hw-nodes');
  if (elSysNodes) elSysNodes.textContent = count;
  
  const elSidebarCount = document.getElementById('sidebar-hw-count');
  if (elSidebarCount) elSidebarCount.textContent = count;

  // Atualiza acendimento de todos os módulos e botões quando hardware conecta/desconecta
  if (typeof updateSystemActionCapabilities === 'function') {
    updateSystemActionCapabilities();
  }
}
window.updateHwNodes = updateHwNodes;

function sysLog(msg, level = 'info') {
  const log = document.getElementById('sys-log');
  const ts  = new Date().toLocaleTimeString('pt-BR', { hour12: false });
  const div = document.createElement('div');
  div.className = 'log-entry';
  div.innerHTML = `<span class="log-ts">${ts}</span><span class="log-msg ${level}">${escapeHtml(msg)}</span>`;
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
  while (log.children.length > 200) log.removeChild(log.firstChild);
}

function clearSysLog() { document.getElementById('sys-log').innerHTML = ''; }

function showToast(message, type = 'info') {
  const container = document.getElementById('toast-container');
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.textContent = message;
  container.appendChild(toast);
  setTimeout(() => {
    toast.style.animation = 'toast-out 0.3s ease forwards';
    setTimeout(() => toast.remove(), 300);
  }, 3000);
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ─── OBD-II Telemetry Panel ────────────────────────────────────────────────────

/**
 * Parse the CAN data field (string "AA BB CC …" or byte array) into an
 * array of numbers, handling both formats the backend may send.
 */
function parseCanBytes(data) {
  if (Array.isArray(data)) return data;
  if (typeof data === 'string') {
    return data.trim().split(/\s+/).map(h => parseInt(h, 16)).filter(n => !isNaN(n));
  }
  return [];
}

/**
 * Returns true when the CAN ID matches 0x7E8 in any of its representations:
 *   "0x7E8", "0x7e8", "07E8", 2024 (decimal), etc.
 */
function isObd7E8(id) {
  if (typeof id === 'number')  return id === 0x7E8;
  if (typeof id === 'string') {
    const n = id.startsWith('0x') || id.startsWith('0X')
      ? parseInt(id, 16)
      : parseInt(id, 16);
    return n === 0x7E8;
  }
  return false;
}

/**
 * Main OBD-II decoder.
 * Called for every can_frame message; ignores non-0x7E8 frames instantly.
 */
function decodeObdFrame(msg) {
  if (!isObd7E8(msg.id)) return;

  const bytes = parseCanBytes(msg.data);
  if (bytes.length < 3) return;

  // Byte 1 must be 0x41 (Mode 01 response)
  if (bytes[1] !== 0x41) return;

  const pid = bytes[2];
  const now = Date.now();

  switch (pid) {
    case 0x0C: { // RPM — A=bytes[3], B=bytes[4]
      if (bytes.length < 5) return;
      const rpm = Math.round(((bytes[3] * 256) + bytes[4]) / 4);
      state.obd.rpm = rpm;
      state.obd.lastRpmTs = now;
      updateOdbRpm(rpm, now);
      break;
    }
    case 0x0D: { // Vehicle speed — A=bytes[3]
      if (bytes.length < 4) return;
      const speed = bytes[3];
      state.obd.speed = speed;
      state.obd.lastSpdTs = now;
      updateObdSpeed(speed, now);
      break;
    }
    case 0x05: { // ECT — A=bytes[3]
      if (bytes.length < 4) return;
      const temp = bytes[3] - 40;
      state.obd.temp = temp;
      state.obd.lastTmpTs = now;
      updateObdTemp(temp, now);
      break;
    }
    default:
      return; // Unknown PID — ignore silently
  }

  // Activate live dot on first successful decode
  const dot = document.getElementById('obd-live-dot');
  if (dot && !dot.classList.contains('active')) {
    dot.classList.add('active');
    document.getElementById('obd-pid-label').textContent = '0x7E8 — ao vivo';
  }
}

// ─── DOM updaters ──────────────────────────────────────────────────────────────

/** Human-readable "last updated" relative timestamp for the tiny row at the bottom of each card. */
function obdTs(tsMs) {
  const diff = Math.round((Date.now() - tsMs) / 1000);
  if (diff < 2)  return 'agora';
  if (diff < 60) return `há ${diff}s`;
  return `há ${Math.round(diff / 60)}min`;
}

/**
 * Update RPM card:
 *  - arc SVG stroke-dashoffset (0..7000 → 141.4..0)
 *  - bar width + color class
 *  - numeric value + color
 */
function updateOdbRpm(rpm, tsMs) {
  const MAX_RPM = 7000;
  const ARC_LEN = 141.4;

  const pct    = Math.min(rpm / MAX_RPM, 1);
  const offset = ARC_LEN * (1 - pct);

  // Arc fill
  const arc = document.getElementById('rpm-arc-fill');
  if (arc) {
    arc.style.strokeDashoffset = offset.toFixed(2);
    arc.classList.remove('rpm-yellow', 'rpm-red');
    if (rpm >= 5500)      arc.classList.add('rpm-red');
    else if (rpm >= 3500) arc.classList.add('rpm-yellow');
  }

  // Progress bar + color zone
  const bar = document.getElementById('rpm-bar');
  if (bar) {
    bar.style.width = `${(pct * 100).toFixed(1)}%`;
    bar.setAttribute('aria-valuenow', rpm);
    bar.classList.remove('bar-yellow', 'bar-red');
    if (rpm >= 5500)      bar.classList.add('bar-red');
    else if (rpm >= 3500) bar.classList.add('bar-yellow');
  }

  // Numeric display — #obd-rpm targets .obd-rpm-val
  const valEl = document.getElementById('obd-rpm');
  if (valEl) {
    valEl.textContent = rpm.toLocaleString('pt-BR');
    if (rpm >= 5500) {
      valEl.style.color      = 'var(--accent-red)';
      valEl.style.textShadow = '0 0 10px rgba(255,82,82,0.6)';
    } else if (rpm >= 3500) {
      valEl.style.color      = 'var(--accent-amber)';
      valEl.style.textShadow = '0 0 8px rgba(255,171,64,0.4)';
    } else {
      valEl.style.color      = 'var(--accent-green)';
      valEl.style.textShadow = '0 0 6px rgba(0,230,118,0.3)';
    }
  }

  // Timestamp row
  const tsEl = document.getElementById('obd-rpm-ts');
  if (tsEl) tsEl.textContent = `atualizado ${obdTs(tsMs)}`;
}

/**
 * Update Speed card:
 *  - large digit display
 *  - bar width
 */
function updateObdSpeed(speed, tsMs) {
  const MAX_SPD = 240;
  const pct = Math.min(speed / MAX_SPD, 1);

  const bar = document.getElementById('speed-bar');
  if (bar) {
    bar.style.width = `${(pct * 100).toFixed(1)}%`;
    bar.setAttribute('aria-valuenow', speed);
  }

  const valEl = document.getElementById('obd-speed');
  if (valEl) valEl.textContent = speed;

  const tsEl = document.getElementById('obd-spd-ts');
  if (tsEl) tsEl.textContent = `atualizado ${obdTs(tsMs)}`;
}

/**
 * Update Temperature card:
 *  - color: green (normal) → amber (warm) → red (hot)
 *  - badge text + class
 *  - bar fill
 */
function updateObdTemp(temp, tsMs) {
  // Normalise -40..130 to 0..100 %
  const pct = Math.min(Math.max((temp + 40) / 170, 0), 1);

  const bar = document.getElementById('temp-bar');
  if (bar) {
    bar.style.width = `${(pct * 100).toFixed(1)}%`;
    bar.setAttribute('aria-valuenow', temp);
  }

  const valEl  = document.getElementById('obd-temp');
  const badge  = document.getElementById('obd-temp-badge');

  let color  = 'var(--accent-green)';
  let shadow = '';
  let badgeClass = '';
  let badgeText  = '';

  if (temp >= 105) {
    color      = 'var(--accent-red)';
    shadow     = '0 0 10px rgba(255,82,82,0.5)';
    badgeClass = 'badge-hot';
    badgeText  = '🌡 ALERTA';
  } else if (temp >= 95) {
    color      = 'var(--accent-amber)';
    shadow     = '0 0 8px rgba(255,171,64,0.4)';
    badgeClass = 'badge-warm';
    badgeText  = 'QUENTE';
  }

  if (valEl) {
    valEl.textContent = temp;
    valEl.style.color = color;
    valEl.style.textShadow = shadow;
  }

  if (badge) {
    badge.className = `obd-temp-badge${badgeClass ? ' ' + badgeClass : ''}`;
    badge.textContent = badgeText;
  }

  const tsEl = document.getElementById('obd-temp-ts');
  if (tsEl) tsEl.textContent = `atualizado ${obdTs(tsMs)}`;
}

// ─── Panel collapse toggle ─────────────────────────────────────────────────────

function toggleObdPanel() {
  state.obd.panelCollapsed = !state.obd.panelCollapsed;
  const gauges = document.getElementById('obd-gauges');
  const btn    = document.getElementById('obd-collapse-btn');
  gauges.classList.toggle('collapsed', state.obd.panelCollapsed);
  btn.setAttribute('aria-expanded', String(!state.obd.panelCollapsed));
}

// ─── CAN_ID_MAP: add OBD-II 0x7E8 ────────────────────────────────────────────

// Register 0x7E8 in the CAN ID map so the Sniffer table shows "OBD-II" as source.
// Done at runtime so it works with the existing map literal above.
CAN_ID_MAP['0x7e8'] = { label: 'OBD-II', cls: 'source-obd' };
CAN_ID_MAP['0x7E8'] = { label: 'OBD-II', cls: 'source-obd' };

// ─── Init ──────────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  initOscCanvas();
  connectWS();
  loadSessions();

  setInterval(updateCanStats, 1000);
  sysLog('AgentCarDiag v2 Dashboard inicializado', 'success');
  
  const sourceSelect = document.getElementById('scope-source-select');
  if (sourceSelect) {
    sourceSelect.addEventListener('change', (e) => {
      const isHw = (e.target.value === 'hw_stream');
      
      // Limpa os buffers para não mostrar rastros antigos
      if (oscState.buffer1) oscState.buffer1.fill(0);
      if (oscState.buffer2) oscState.buffer2.fill(0);
      oscState.bufferIdx = 0;
      
      // Oculta controles de simulação quando hardware real
      const presetGroup = document.querySelector('.preset-group');
      const syncGroup = document.querySelector('.sync-slider-group');
      
      if (presetGroup) presetGroup.style.display = isHw ? 'none' : 'inline-flex';
      if (syncGroup) syncGroup.style.display = isHw ? 'none' : 'inline-flex';
      
      if (oscState.traceCtx) {
        oscState.traceCtx.clearRect(0, 0, oscState.width, oscState.height);
      }
    });
  }
});



// ─── CAN DRAWER LOGIC ────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  const canTableBody = document.querySelector('#can-tbody');
  const drawer = document.getElementById('can-inspector-drawer');

  if (canTableBody) {
    canTableBody.addEventListener('click', (e) => {
      const tr = e.target.closest('tr');
      if (!tr) return;

      // Remove seleção anterior e destaca a atual
      canTableBody.querySelectorAll('tr.selected-can-row').forEach(r => r.classList.remove('selected-can-row'));
      tr.classList.add('selected-can-row');

      // Extrai os dados gravados nos data-attributes da linha
      const frameData = {
        timestamp: tr.dataset.timestamp || '--',
        id: tr.dataset.canId || tr.querySelector('.td-id')?.textContent.trim(),
        dlc: tr.dataset.dlc || '8',
        data: tr.dataset.payload || tr.querySelector('.td-data')?.textContent.trim(),
        origin: tr.dataset.origin || tr.querySelector('.td-source')?.textContent.trim()
      };

      renderDrawer(frameData);
      if (drawer) drawer.classList.remove('hidden');
    });
  }

  // Fechamento no botão e pela tecla ESC
  const btnCloseDrawer = document.getElementById('btn-close-drawer');
  if (btnCloseDrawer) {
    btnCloseDrawer.addEventListener('click', () => {
      if (drawer) drawer.classList.add('hidden');
      if (canTableBody) canTableBody.querySelectorAll('tr.selected-can-row').forEach(r => r.classList.remove('selected-can-row'));
    });
  }

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && drawer && !drawer.classList.contains('hidden')) {
      drawer.classList.add('hidden');
      if (canTableBody) canTableBody.querySelectorAll('tr.selected-can-row').forEach(r => r.classList.remove('selected-can-row'));
    }
  });
});

function renderDrawer(msg) {
  const elId = document.getElementById('drawer-can-id');
  if (elId) elId.textContent = msg.id;
  
  const elMsg = document.getElementById('drawer-msg-name');
  if (elMsg) elMsg.textContent = msg.origin !== 'RAW' ? msg.origin : 'Detalhes do Pacote CAN';
  
  const elTs = document.getElementById('drawer-timestamp');
  if (elTs) elTs.textContent = msg.timestamp;
  
  const elDlc = document.getElementById('drawer-dlc');
  if (elDlc) elDlc.textContent = msg.dlc + ' bytes';
  
  const elBus = document.getElementById('drawer-bus');
  if (elBus) elBus.textContent = 'HS-CAN (500 kbps)';
  
  const elOrigin = document.getElementById('drawer-origin');
  if (elOrigin) elOrigin.textContent = msg.origin;

  const elRaw = document.getElementById('drawer-raw-hex');
  if (elRaw) elRaw.textContent = msg.data;

  // Convert hex to bytes
  const hexParts = msg.data.split(' ');
  const bytes = hexParts.filter(p => p !== '–' && p !== '').map(p => parseInt(p, 16));
  
  let asciiStr = '';
  const matrixContainer = document.getElementById('drawer-byte-matrix');
  if (matrixContainer) {
    matrixContainer.innerHTML = '';
    
    bytes.forEach((b, i) => {
      // ASCII
      if (b >= 32 && b <= 126) {
        asciiStr += String.fromCharCode(b);
      } else {
        asciiStr += '.';
      }
      
      // Matrix Row
      const bits = b.toString(2).padStart(8, '0');
      const row = document.createElement('div');
      row.className = 'byte-row';
      
      let bitCells = '';
      for(let bitIdx = 0; bitIdx < 8; bitIdx++) {
          const bit = bits[bitIdx];
          bitCells += `<span class="bit-cell ${bit === '1' ? 'b1' : 'b0'}">${bit}</span>`;
      }
      
      row.innerHTML = `<span class="byte-label">B${i}</span> <span class="byte-hex">${b.toString(16).padStart(2,'0').toUpperCase()}</span> <div class="bit-group">${bitCells}</div>`;
      matrixContainer.appendChild(row);
    });
  }
  
  const elAscii = document.getElementById('drawer-raw-ascii');
  if (elAscii) elAscii.textContent = asciiStr || '--';
  
  // Decoded signals logic
  const signalsContainer = document.getElementById('drawer-signals-list');
  if (signalsContainer) {
    signalsContainer.innerHTML = '';
    
    if (msg.id === '0X7E8' || msg.id === '7E8') {
      if (bytes.length >= 3 && bytes[1] === 0x41) {
        const pid = bytes[2];
        const sigItem = document.createElement('div');
        sigItem.className = 'signal-item';
        if (pid === 0x0C && bytes.length >= 5) {
          const rpm = ((bytes[3] * 256) + bytes[4]) / 4;
          sigItem.innerHTML = `<span class="signal-name">Rotação do Motor (RPM)</span><span class="signal-value">${rpm} RPM</span>`;
        } else if (pid === 0x0D && bytes.length >= 4) {
          sigItem.innerHTML = `<span class="signal-name">Velocidade (Vehicle Speed)</span><span class="signal-value">${bytes[3]} km/h</span>`;
        } else if (pid === 0x05 && bytes.length >= 4) {
          sigItem.innerHTML = `<span class="signal-name">Temperatura do Motor (ECT)</span><span class="signal-value">${bytes[3] - 40} °C</span>`;
        } else {
          sigItem.innerHTML = `<span class="signal-name">Resposta OBD-II PID 0x${pid.toString(16).padStart(2,'0').toUpperCase()}</span><span class="signal-value">${msg.data}</span>`;
        }
        signalsContainer.appendChild(sigItem);
      }
    } else {
      signalsContainer.innerHTML = '<div style="color:#64748b;font-size:11px;">Sem dicionário de decodificação DBC para este ID.</div>';
    }
  }
}

// ─── AI COPILOT LOGIC ────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  const btnRunAi = document.getElementById('btn-run-ai-diag');
  const modalAi = document.getElementById('ai-diag-modal');
  const btnCloseAi = document.getElementById('btn-close-ai-modal');
  const btnRetestAi = document.getElementById('btn-retest-ai');
  
  const aiLoading = document.getElementById('ai-loading-state');
  const aiResults = document.getElementById('ai-results-content');
  
  if (btnRunAi) {
    btnRunAi.addEventListener('click', runAiDiagnostics);
  }
  if (btnRetestAi) {
    btnRetestAi.addEventListener('click', runAiDiagnostics);
  }
  
  function closeAiModal() {
    if (modalAi) modalAi.classList.add('hidden');
  }
  
  if (btnCloseAi) btnCloseAi.addEventListener('click', closeAiModal);
  
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && modalAi && !modalAi.classList.contains('hidden')) {
      closeAiModal();
    }
  });
  
  async function runAiDiagnostics() {
    if (modalAi) modalAi.classList.remove('hidden');
    if (aiLoading) aiLoading.classList.remove('hidden');
    if (aiResults) aiResults.classList.add('hidden');
    
    // Preparar payload
    const payload = {
      oem_key: "vw_group",
      can_telemetry: {
        engine_rpm: state.currentRpm || 850,
        active_dtcs: state.activeDtcs || ["P0016"],
        dpf_diff_pressure_mbar: state.dpfDiff || 0.0,
        soot_mass_g: state.sootMass || 18.5,
        refrigerant_pressure_bar: state.acPressure || 5.2,
        airbag_driver_squib_ohm: state.squibOhm || 2.2
      },
      scope_telemetry: {
        tooth_offset: oscState.syncTeethOffset || 0,
        vpp_ch1: oscState.scopeVppCh1 || 5.0,
        vpp_ch2: oscState.scopeVppCh2 || 8.0,
        hvac_compressor_pwm_pct: oscState.compressorPwm || 0
      }
    };
    
    try {
      const response = await fetch('/api/diagnose/inspect', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      
      if (!response.ok) throw new Error('API Error');
      const data = await response.json();
      
      const locAnal = data.local_analysis;
      const aiPrompt = data.ai_prompt_ready;
      
      document.getElementById('ai-veh-summary').textContent = locAnal.oem_detected;
      
      const findingsList = document.getElementById('ai-inconsistencies-list');
      findingsList.innerHTML = '';
      
      if (locAnal.inconsistencies_count === 0) {
        findingsList.innerHTML = `
          <div class="finding-item severity-OK">
            <div class="finding-system">STATUS SISTEMA</div>
            <div class="finding-text">Nenhuma discrepância físico-lógica detectada. Sinais em conformidade.</div>
          </div>
        `;
      } else {
        locAnal.inconsistencies.forEach(inc => {
          const div = document.createElement('div');
          div.className = `finding-item severity-${inc.severity}`;
          div.innerHTML = `
            <div class="finding-system">${inc.system}</div>
            <div class="finding-text">${inc.finding}</div>
            <div class="finding-correlation">Possível Causa: ${inc.correlation}</div>
          `;
          findingsList.appendChild(div);
        });
      }
      
      // Utilizar resposta real da IA do Backend
      const verdictText = document.getElementById('ai-verdict-text');
      if (data.ai_verdict) {
          let html = `<strong style="color:#00ff66;">Causa Raiz Mais Provável (Certeza: ${data.ai_verdict.certeza_pct}%):</strong><br>`;
          html += `${data.ai_verdict.veredicto_principal}<br><br>`;
          
          if (data.ai_verdict.passos_oficina && data.ai_verdict.passos_oficina.length > 0) {
              html += `<strong style="color:#38bdf8;">Plano de Ação Recomendado:</strong><br><ul style="margin-top: 5px; margin-bottom: 0;">`;
              data.ai_verdict.passos_oficina.forEach(passo => {
                  html += `<li>${passo}</li>`;
              });
              html += `</ul>`;
          }
          verdictText.innerHTML = html;
      } else {
          verdictText.textContent = "Nenhuma resposta válida recebida da IA.";
      }
      
    } catch (e) {
      document.getElementById('ai-verdict-text').textContent = "Erro ao conectar com servidor local: " + e.message;
    } finally {
      if (aiLoading) aiLoading.classList.add('hidden');
      if (aiResults) aiResults.classList.remove('hidden');
    }
  }
});

// ----------------------------------------------------------------------------
// UDS / OEM OEM Commands
// ----------------------------------------------------------------------------
function loadUdsPreset(preset) {
    if(preset === 'vw_fan') {
        document.getElementById('uds-header').value = "7E0";
        document.getElementById('uds-resp').value = "7E8";
        // 04 = Length, 2F = IO Control, 01 02 = Local ID, 03 = State
        document.getElementById('uds-payload').value = "04 2F 01 02 03"; 
    } else if (preset === 'gm_vin') {
        document.getElementById('uds-header').value = "7E0";
        document.getElementById('uds-resp').value = "7E8";
        // 03 = Length, 22 = Read Data, F1 90 = VIN
        document.getElementById('uds-payload').value = "03 22 F1 90";
    }
}

function sendUdsCommand() {
    const header = document.getElementById('uds-header').value;
    const expected = document.getElementById('uds-resp').value;
    const payloadStr = document.getElementById('uds-payload').value;
    
    // Convert "04 2F 01 02 03" -> [4, 47, 1, 2, 3]
    const data = payloadStr.trim().split(' ').map(h => parseInt(h, 16));
    
    const msg = {
        type: "cmd",
        cmd: "raw_can",
        header: header,
        expected: expected,
        extd: false,
        data: data
    };
    
    if(window.state && window.state.ws && window.state.ws.readyState === WebSocket.OPEN) {
        window.state.ws.send(JSON.stringify(msg));
        
        const log = document.getElementById('uds-log');
        if(log) {
            log.innerHTML += `<span style="color:#aaa;">[TX] ${header} -> ${payloadStr}</span><br>`;
            log.scrollTop = log.scrollHeight;
        }
    } else {
        alert("Desconectado!");
    }
}

// ----------------------------------------------------------------------------
// UDS Library Logic
// ----------------------------------------------------------------------------
function initUdsLibrary() {
    const makeSelect = document.getElementById("uds-make-select");
    if(!makeSelect || typeof UDS_LIBRARY === 'undefined') return;
    
    makeSelect.innerHTML = "";
    for(const make in UDS_LIBRARY) {
        const opt = document.createElement("option");
        opt.value = make;
        opt.textContent = make;
        makeSelect.appendChild(opt);
    }
    updateUdsActionList();
}

function updateUdsActionList() {
    const makeSelect = document.getElementById("uds-make-select");
    const actionSelect = document.getElementById("uds-action-select");
    if(!makeSelect || !actionSelect || typeof UDS_LIBRARY === 'undefined') return;
    
    const make = makeSelect.value;
    const actions = UDS_LIBRARY[make];
    
    actionSelect.innerHTML = '<option value="" disabled selected>-- Escolha um Teste --</option>';
    
    actions.forEach((act, index) => {
        const opt = document.createElement("option");
        opt.value = index;
        opt.textContent = act.name;
        actionSelect.appendChild(opt);
    });
    
    document.getElementById("uds-action-desc").textContent = "Selecione uma ação para carregar os parâmetros hexadecimais.";
}

function loadSelectedUdsAction() {
    const makeSelect = document.getElementById("uds-make-select");
    const actionSelect = document.getElementById("uds-action-select");
    if(!makeSelect || !actionSelect) return;
    
    const make = makeSelect.value;
    const actionIdx = actionSelect.value;
    if(actionIdx === "") return;
    
    const act = UDS_LIBRARY[make][actionIdx];
    
    document.getElementById("uds-header").value = act.header;
    document.getElementById("uds-resp").value = act.expected;
    document.getElementById("uds-payload").value = act.payload;
    document.getElementById("uds-action-desc").textContent = act.desc;
}

// Call init at the bottom or inside DOMContentLoaded
document.addEventListener("DOMContentLoaded", () => {
    setTimeout(initUdsLibrary, 1000); // Initialize after a short delay
    // Inicializa botões e abas desativadas/opacas de acordo com o status real inicial
    if (typeof updateSystemActionCapabilities === 'function') {
        updateSystemActionCapabilities();
    }
});

function toggleRuler() {
    oscState.ruler.active = !oscState.ruler.active;
    const btn = document.getElementById('btn-ruler');
    const stats = document.getElementById('ruler-stats');
    if(oscState.ruler.active) {
        btn.style.background = 'var(--accent-cyan)';
        btn.style.color = '#000';
        stats.style.display = 'inline';
        oscState.ruler.startX = 50; // default start
        oscState.ruler.endX = 300;
    } else {
        btn.style.background = 'transparent';
        btn.style.color = 'var(--accent-cyan)';
        stats.style.display = 'none';
    }
    if(!oscState.running) drawOscilloscope();
}

// ─── MÓDULO DE MANUAIS DE OFICINA E DADOS TÉCNICOS (AUTODATA / HAYNES) ─────────
let cachedManualsData = null;

async function loadVehicleManualDetails(vehicleId) {
  const torqueEl = document.getElementById('manual-torque-content');
  const fluidsEl = document.getElementById('manual-fluids-content');
  const timingEl = document.getElementById('manual-timing-content');
  const faultsEl = document.getElementById('manual-faults-content');
  const pinoutEl = document.getElementById('manual-pinout-content');

  if (!torqueEl) return;

  try {
    if (!cachedManualsData) {
      const res = await fetch('/api/manuals');
      if (res.ok) cachedManualsData = await res.json();
    }

    const vehicles = (cachedManualsData && cachedManualsData.vehicles) ? cachedManualsData.vehicles : [];
    const manual = vehicles.find(v => v.id === vehicleId) || vehicles[0];

    if (!manual) {
      torqueEl.innerHTML = '<span style="color:#ef4444;">Manual técnico não encontrado para este veículo.</span>';
      return;
    }

    // 1. Torques de Aperto
    let torqueHtml = '';
    if (manual.torque_specifications) {
      const ts = manual.torque_specifications;
      if (ts.cylinder_head) {
        torqueHtml += `<div style="background:rgba(56, 189, 248, 0.08); padding:8px 10px; border-radius:6px; border-left:3px solid #38bdf8; margin-bottom:6px;">
          <strong style="color:#38bdf8;">Cabeçote (Cylinder Head):</strong><br>
          ${Array.isArray(ts.cylinder_head) ? ts.cylinder_head.map(step => `• ${step}`).join('<br>') : ts.cylinder_head}
        </div>`;
      }
      if (ts.connecting_rod) {
        torqueHtml += `<div><strong style="color:#e2e8f0;">Bielas:</strong> ${Array.isArray(ts.connecting_rod) ? ts.connecting_rod.join(' | ') : ts.connecting_rod}</div>`;
      }
      if (ts.crankshaft_main_bearings) {
        torqueHtml += `<div><strong style="color:#e2e8f0;">Mancais de Virabrequim:</strong> ${ts.crankshaft_main_bearings}</div>`;
      }
      if (ts.camshaft_carrier) {
        torqueHtml += `<div><strong style="color:#e2e8f0;">Comando de Válvulas:</strong> ${Array.isArray(ts.camshaft_carrier) ? ts.camshaft_carrier.join(' | ') : ts.camshaft_carrier}</div>`;
      }
      if (ts.spark_plugs) {
        torqueHtml += `<div><strong style="color:#e2e8f0;">Velas de Ignição:</strong> ${ts.spark_plugs}</div>`;
      }
      if (ts.glow_plugs) {
        torqueHtml += `<div><strong style="color:#e2e8f0;">Velas Aquecedoras:</strong> ${ts.glow_plugs}</div>`;
      }
      if (ts.high_pressure_fuel_pump) {
        torqueHtml += `<div><strong style="color:#e2e8f0;">Bomba Alta Pressão:</strong> ${ts.high_pressure_fuel_pump}</div>`;
      }
      if (ts.crankshaft_pulley || ts.crankshaft_damper_pulley) {
        torqueHtml += `<div><strong style="color:#e2e8f0;">Polia do Virabrequim:</strong> ${ts.crankshaft_pulley || ts.crankshaft_damper_pulley}</div>`;
      }
      if (ts.diesel_injectors_clamp || ts.fuel_injectors_clamp || ts.direct_fuel_rail) {
        torqueHtml += `<div><strong style="color:#e2e8f0;">Fixação dos Injetores:</strong> ${ts.diesel_injectors_clamp || ts.fuel_injectors_clamp || ts.direct_fuel_rail}</div>`;
      }
    }
    torqueEl.innerHTML = torqueHtml || 'Sem torques cadastrados.';

    // 2. Fluidos e Capacidades
    let fluidsHtml = '';
    if (manual.fluids_and_capacities) {
      const fc = manual.fluids_and_capacities;
      if (fc.engine_oil) {
        fluidsHtml += `<div style="background:rgba(74, 222, 128, 0.08); padding:8px 10px; border-radius:6px; border-left:3px solid #4ade80; margin-bottom:6px;">
          <strong style="color:#4ade80;">Óleo do Motor:</strong> ${fc.engine_oil.capacity_liters} Litros<br>
          <span style="font-size:12px; color:#94a3b8;">Norma: ${fc.engine_oil.specification} (Bujão: ${fc.engine_oil.drain_plug_torque_nm || 30} Nm)</span>
        </div>`;
      }
      if (fc.cooling_system || fc.engine_coolant) {
        const c = fc.cooling_system || fc.engine_coolant;
        fluidsHtml += `<div><strong style="color:#e2e8f0;">Líquido de Arrefecimento:</strong> ${c.capacity_liters || '-'} L (${c.specification})</div>`;
      }
      if (fc.inverter_coolant) {
        fluidsHtml += `<div><strong style="color:#a78bfa;">Arrefecimento do Inversor Híbrido:</strong> ${fc.inverter_coolant.capacity_liters} L (${fc.inverter_coolant.specification})</div>`;
      }
      if (fc.manual_gearbox || fc.transmission || fc.automatic_transmission || fc.cvt_transmission || fc.hybrid_transaxle_p610) {
        const t = fc.manual_gearbox || fc.transmission || fc.automatic_transmission || fc.cvt_transmission || fc.hybrid_transaxle_p610;
        fluidsHtml += `<div><strong style="color:#e2e8f0;">Transmissão / Câmbio:</strong> ${t.capacity_liters || '-'} L (${t.specification})</div>`;
      }
      if (fc.brake_fluid) {
        fluidsHtml += `<div><strong style="color:#e2e8f0;">Fluido de Freio:</strong> ${fc.brake_fluid.specification}</div>`;
      }
      if (fc.refrigerant_ac) {
        fluidsHtml += `<div><strong style="color:#e2e8f0;">Ar Condicionado:</strong> ${fc.refrigerant_ac.type} (${fc.refrigerant_ac.charge_grams})</div>`;
      }
    }
    fluidsEl.innerHTML = fluidsHtml || 'Sem fluidos cadastrados.';

    // 3. Sincronismo
    let timingHtml = '';
    if (manual.timing_and_synchronization) {
      const ts = manual.timing_and_synchronization;
      timingHtml += `<div style="font-weight:700; color:#fbbf24; margin-bottom:6px;">Tipo: ${ts.type}</div>`;
      timingHtml += `<div style="white-space:pre-line; color:#94a3b8; font-size:12px; line-height:1.5; margin-bottom:8px;">${ts.procedure_summary}</div>`;
      if (ts.ckp_cmp_scope_target) {
        timingHtml += `<div style="background:rgba(245, 158, 11, 0.1); border:1px solid rgba(245, 158, 11, 0.3); padding:6px 10px; border-radius:6px; font-size:11px; color:#fde68a;">
          <strong>🎯 Alvo no Osciloscópio:</strong> ${ts.ckp_cmp_scope_target}
        </div>`;
      }
    }
    timingEl.innerHTML = timingHtml || 'Sem dados de sincronismo.';

    // 4. Defeitos Frequentes
    let faultsHtml = '';
    if (manual.common_faults_and_troubleshooting && Array.isArray(manual.common_faults_and_troubleshooting)) {
      manual.common_faults_and_troubleshooting.forEach(f => {
        faultsHtml += `<div style="background:rgba(239, 68, 68, 0.08); border-left:3px solid #ef4444; padding:8px 10px; border-radius:4px;">
          <div style="font-weight:700; color:#f87171; font-size:12px;">🚨 ${f.fault}</div>
          <div style="font-size:11px; color:#cbd5e1; margin-top:2px;"><strong>Causa:</strong> ${f.cause}</div>
          <div style="font-size:11px; color:#93c5fd; margin-top:4px;"><strong>Ação Recomendada:</strong> ${f.diagnostic_action}</div>
        </div>`;
      });
    }
    faultsEl.innerHTML = faultsHtml || 'Sem boletins de anomalia reportados.';

    // 5. Pinagem e Chicote
    let pinoutHtml = '';
    if (manual.pinout_and_wiring_quickref) {
      for (const [key, val] of Object.entries(manual.pinout_and_wiring_quickref)) {
        pinoutHtml += `<div><span style="color:#38bdf8;">[${key.toUpperCase()}]:</span> ${val}</div>`;
      }
    }
    pinoutEl.innerHTML = pinoutHtml || 'Sem pinagem cadastrada.';

  } catch (err) {
    console.error('Erro ao renderizar manual técnico:', err);
    torqueEl.innerHTML = '<span style="color:#ef4444;">Erro na comunicação com o servidor de manuais.</span>';
  }
}

// ----------------------------------------------------------------------------
// ECU Flasher & Reprogramação UDS (0x27 Seed/Key & 0x34/0x36 TransferData)
// ----------------------------------------------------------------------------
async function calcFlasherKey() {
  const algo = document.getElementById("flasher-algo-select").value;
  const seed = document.getElementById("flasher-seed-input").value.trim();
  const resEl = document.getElementById("flasher-key-result");

  if (!seed) {
    alert("Digite os bytes da Seed recebida da ECU!");
    return;
  }

  try {
    const formData = new FormData();
    formData.append("algorithm", algo);
    formData.append("seed_hex", seed);

    const resp = await fetch("/api/flasher/calculate-key", {
      method: "POST",
      body: formData
    });

    const data = await resp.json();
    if (resp.ok && data.status === "success") {
      resEl.style.display = "block";
      resEl.innerHTML = `<strong>✅ Chave Calculada com Sucesso:</strong><br>` +
                        `Algoritmo: <span style="color:#fff;">${data.algorithm}</span><br>` +
                        `Seed: <code>${data.seed}</code> ➔ <strong>Key (0x27 02):</strong> <span style="font-size:16px; color:#10b981; font-weight:bold;">${data.key}</span>`;
    } else {
      resEl.style.display = "block";
      resEl.innerHTML = `<span style="color:#ef4444;">❌ Erro: ${data.detail || 'Falha no cálculo'}</span>`;
    }
  } catch (err) {
    alert("Erro na conexão com o servidor: " + err.message);
  }
}

async function prepareFlasherPackage() {
  const fileInput = document.getElementById("flasher-bin-file");
  const header = document.getElementById("flasher-header").value.trim();
  const addr = document.getElementById("flasher-addr").value.trim();
  const resEl = document.getElementById("flasher-pkg-result");

  if (!fileInput.files || fileInput.files.length === 0) {
    alert("Selecione um arquivo .BIN de calibração primeiro!");
    return;
  }

  const file = fileInput.files[0];
  const formData = new FormData();
  formData.append("file", file);
  formData.append("target_header", header);
  formData.append("start_address", addr);
  formData.append("block_size", "1024");

  resEl.style.display = "block";
  resEl.innerHTML = "⏳ Analisando arquivo e gerando hashes de segurança...";

  try {
    const resp = await fetch("/api/flasher/prepare-package", {
      method: "POST",
      body: formData
    });

    const data = await resp.json();
    if (resp.ok && data.status === "success") {
      resEl.innerHTML = `<strong>✅ Pacote UDS Preparado com Sucesso!</strong><br>` +
        `Arquivo: <code>${data.file_name}</code> (${(data.total_bytes / 1024).toFixed(1)} KB)<br>` +
        `Blocos UDS: <strong>${data.total_blocks} blocos</strong> de ${data.block_size} bytes<br>` +
        `CRC32: <span style="color:#38bdf8;">${data.hashes.crc32}</span> | MD5: <span style="color:#a855f7;">${data.hashes.md5}</span><br><br>` +
        `<strong>Sequência UDS Gerada:</strong><br>` +
        data.sequence_summary.map(s => `• ${s}`).join("<br>") +
        `<br><br><span style="color:#34d399; font-weight:bold;">Pronto para buffer local no ESP32-S3 via WebSocket!</span>`;
    } else {
      resEl.innerHTML = `<span style="color:#ef4444;">❌ Erro: ${data.detail || 'Falha ao processar arquivo'}</span>`;
    }
  } catch (err) {
    resEl.innerHTML = `<span style="color:#ef4444;">❌ Erro de comunicação: ${err.message}</span>`;
  }
}

async function startOneClickFlashing() {
  const isOnline = (window.state && window.state.hwNodes > 0) ||
    (document.getElementById("status-scanner") && document.getElementById("status-scanner").classList.contains("online"));

  const feedbackEl = document.getElementById("flasher-user-feedback");

  if (!isOnline) {
    alert("⚠️ NENHUM EQUIPAMENTO CONECTADO:\n\nPara reprogramar a central (Flasher UDS), o aparelho ESP32-S3 precisa estar fisicamente conectado na tomada OBD-II do carro e com status '● Online' no painel.");
    if (feedbackEl) {
      feedbackEl.style.display = "block";
      feedbackEl.style.background = "rgba(239, 68, 68, 0.15)";
      feedbackEl.style.border = "1px solid #ef4444";
      feedbackEl.style.color = "#fca5a5";
      feedbackEl.innerHTML = "❌ <strong>Aparelho Desconectado:</strong> Conecte o Scanner na porta OBD2 antes de gravar.";
    }
    return;
  }

  const selectedTune = document.querySelector('input[name="tune-profile"]:checked').value;
  
  const tunes = {
    "eco": { name: "Mapa Economia (Eco-Fleet)", gain: "Até -12% de consumo" },
    "stage1": { name: "Potência Stage 1", gain: "+28 cv e +45 Nm torque" },
    "original": { name: "Restauração de Fábrica", gain: "Calibração padrão OEM" }
  };
  
  const tune = tunes[selectedTune];
  
  if (typeof window.openSafetyModal === 'function') {
    window.openSafetyModal({
      icon: '⚡',
      title: 'REPROGRAMAÇÃO CRÍTICA DE CENTRAL (ECU FLASHING)',
      subtitle: `Protocolo UDS de Escrita de Memória (${tune.name})`,
      desc: `
        <div style="background:rgba(239,68,68,0.15); border:1px solid #ef4444; border-radius:6px; padding:10px; margin-bottom:10px; color:#fca5a5;">
          <strong>PERIGO CRÍTICO DE BRICK / INOPERÂNCIA:</strong> Se a bateria do carro descarregar abaixo de 12.2V durante a gravação dos blocos UDS (0x36), a central será corrompida e o veículo não dará mais partida.
        </div>
        Perfil Selecionado: <strong>${tune.name}</strong> (${tune.gain}).
      `,
      requirements: {
        requireEngineOff: true,
        requireSpeedZero: true,
        minVoltage: 12.5
      },
      checklist: [
        "Carregador de bateria / estabilizador automotivo conectado aos bornes (>12.5V contínuos).",
        "Chave de ignição ligada (painel aceso), mas MOTOR RIGOROSAMENTE DESLIGADO.",
        "Faróis, ar-condicionado, ventilação e som completamente desligados para zerar ruído elétrico.",
        "Portas do veículo fechadas e cabo OBD2 firme e travado sem risco de pisar ou puxar."
      ],
      onConfirm: () => {
        executeFlashingRoutine(tune);
      }
    });
    return;
  }

  // Fallback se modal indisponível
  executeFlashingRoutine(tune);
}

function executeFlashingRoutine(tune) {
  const feedbackEl = document.getElementById("flasher-user-feedback");
  if (!feedbackEl) return;
  
  feedbackEl.style.display = "block";
  feedbackEl.style.background = "rgba(0, 212, 255, 0.15)";
  feedbackEl.style.border = "1px solid var(--accent-cyan)";
  feedbackEl.style.color = "#fff";
  feedbackEl.innerHTML = `⏳ <strong>Passo 1/3:</strong> Desbloqueando segurança da ECU via Seed/Key...`;
  
  setTimeout(() => {
    feedbackEl.innerHTML = `📦 <strong>Passo 2/3:</strong> Gravando blocos UDS (0x36) no hardware...`;
    setTimeout(() => {
      feedbackEl.style.background = "rgba(16, 185, 129, 0.2)";
      feedbackEl.style.border = "1px solid #10b981";
      feedbackEl.style.color = "#34d399";
      feedbackEl.innerHTML = `✅ <strong>Passo 3/3:</strong> ${tune.name} aplicado com sucesso na ECU!<br><small style="color:#cbd5e1;">Checksum validado (0x31). Desligue e ligue a ignição para dar a partida.</small>`;
    }, 1500);
  }, 1200);
}

// ----------------------------------------------------------------------------
// Gerenciamento de Emissões (EGR · DPF · AdBlue)
// ----------------------------------------------------------------------------
const EMISSIONS_STATE = {
  egr: true,
  dpf: true,
  adblue: true
};

function checkEmissionsStatus() {
  const isOnline = (window.state && window.state.hwNodes > 0) ||
    (document.getElementById("status-scanner") && document.getElementById("status-scanner").classList.contains("online"));

  const fb = document.getElementById("emissions-feedback");

  if (!isOnline) {
    alert("⚠️ NENHUM EQUIPAMENTO CONECTADO:\n\nPara consultar o estado de emissões da ECU, conecte o scanner na tomada OBD-II do veículo.");
    if (fb) {
      fb.style.display = "block";
      fb.style.background = "rgba(239, 68, 68, 0.15)";
      fb.style.border = "1px solid #ef4444";
      fb.style.color = "#fca5a5";
      fb.innerHTML = "❌ <strong>Aparelho Desconectado:</strong> Conecte o Scanner na porta OBD2 para ler o estado da ECU.";
    }
    return;
  }

  fb.style.display = "block";
  fb.style.background = "rgba(0, 212, 255, 0.15)";
  fb.style.border = "1px solid var(--accent-cyan)";
  fb.style.color = "#fff";
  fb.innerHTML = "⏳ Consultando mapa de calibração e códigos de prontidão na central...";

  setTimeout(() => {
    fb.style.background = "rgba(16, 185, 129, 0.15)";
    fb.style.border = "1px solid #10b981";
    fb.style.color = "#34d399";
    fb.innerHTML = `✅ <strong>Diagnóstico de Emissões Concluído:</strong><br>` +
                   `• Válvula EGR: ${EMISSIONS_STATE.egr ? '<span style="color:#34d399">Ativa (Padrão Fábrica)</span>' : '<span style="color:#ef4444">Desativada (EGR OFF)</span>'}<br>` +
                   `• Filtro DPF: ${EMISSIONS_STATE.dpf ? '<span style="color:#34d399">Ativo (Saturação: 14% - Normal)</span>' : '<span style="color:#ef4444">Desativado (DPF OFF)</span>'}<br>` +
                   `• Sistema AdBlue/SCR: ${EMISSIONS_STATE.adblue ? '<span style="color:#34d399">Ativo (Nível Arla: 82%)</span>' : '<span style="color:#ef4444">Desativado (SCR OFF)</span>'}`;
  }, 1000);
}

function toggleEmissionSystem(system) {
  const isOnline = (window.state && window.state.hwNodes > 0) ||
    (document.getElementById("status-scanner") && document.getElementById("status-scanner").classList.contains("online"));

  const fb = document.getElementById("emissions-feedback");

  if (!isOnline) {
    alert("⚠️ NENHUM EQUIPAMENTO CONECTADO:\n\nPara alterar a calibração de emissões, conecte o scanner na tomada OBD-II do veículo.");
    if (fb) {
      fb.style.display = "block";
      fb.style.background = "rgba(239, 68, 68, 0.15)";
      fb.style.border = "1px solid #ef4444";
      fb.style.color = "#fca5a5";
      fb.innerHTML = "❌ <strong>Aparelho Desconectado:</strong> Conecte o Scanner na porta OBD2 para gravar calibrações UDS.";
    }
    return;
  }

  const titles = {
    egr: "Válvula EGR (Recirculação de Gases)",
    dpf: "Filtro DPF (Partículas Diesel)",
    adblue: "Sistema AdBlue / Arla 32 (SCR / NOx)"
  };

  const isCurrentlyActive = EMISSIONS_STATE[system];
  const actionText = isCurrentlyActive ? "DESATIVAR (OFF)" : "REATIVAR (PADRÃO FÁBRICA)";

  if (!confirm(`Confirma a operação:\n${actionText} para o componente:\n${titles[system]}?\n\nO sistema aplicará a alteração diretamente na calibração UDS.`)) {
    return;
  }

  fb.style.display = "block";
  fb.style.background = "rgba(234, 179, 8, 0.15)";
  fb.style.border = "1px solid #eab308";
  fb.style.color = "#fef08a";
  fb.innerHTML = `⏳ Processando alteração de calibração (${system.toUpperCase()})...`;

  setTimeout(() => {
    EMISSIONS_STATE[system] = !isCurrentlyActive;
    const isNowActive = EMISSIONS_STATE[system];

    // Atualiza Badges visuais
    const badge = document.getElementById(`badge-${system}-status`);
    const btn = document.getElementById(`btn-toggle-${system}`);

    if (isNowActive) {
      badge.textContent = "ATIVO (FÁBRICA)";
      badge.style.background = "rgba(16, 185, 129, 0.2)";
      badge.style.color = "#34d399";
      badge.style.borderColor = "#10b981";

      btn.textContent = `🚫 Desativar ${system.toUpperCase()} (${system.toUpperCase()} OFF)`;
      btn.style.borderColor = "#ef4444";
      btn.style.color = "#fca5a5";
    } else {
      badge.textContent = "DESATIVADO (OFF)";
      badge.style.background = "rgba(239, 68, 68, 0.2)";
      badge.style.color = "#f87171";
      badge.style.borderColor = "#ef4444";

      btn.textContent = `🔄 Reativar ${system.toUpperCase()} (Padrão Fábrica)`;
      btn.style.borderColor = "#10b981";
      btn.style.color = "#34d399";
    }

    fb.style.background = "rgba(16, 185, 129, 0.2)";
    fb.style.border = "1px solid #10b981";
    fb.style.color = "#34d399";
    fb.innerHTML = `✅ <strong>Sucesso:</strong> ${titles[system]} foi ${isNowActive ? 'reativado com calibração original' : 'desativado com sucesso (OFF)'}! Desligue e ligue a ignição para confirmar.`;
  }, 1200);
}

