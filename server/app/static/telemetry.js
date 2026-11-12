// Gateway BLE Telemetry Client
let telemetryWs = null;
const wsProtocol = window.location.protocol === 'https:' ? 'wss://' : 'ws://';
const TELEMETRY_WS_URL = wsProtocol + window.location.host + '/ws/telemetry';
let reconnectDelay = 1000;
const MAX_RECONNECT_DELAY = 30000;

function connectTelemetry() {
  telemetryWs = new WebSocket(TELEMETRY_WS_URL);
  
  telemetryWs.onopen = () => {
    console.log('[Telemetry] Connected');
    reconnectDelay = 1000; // Reset backoff on success
  };
  
  telemetryWs.onmessage = (evt) => {
    try {
      const msg = JSON.parse(evt.data);
      handleTelemetryMessage(msg);
    } catch (e) {
      console.error('[Telemetry] Parse error', e);
    }
  };
  
  telemetryWs.onclose = () => {
    console.log(`[Telemetry] Disconnected. Reconnecting in ${reconnectDelay}ms...`);
    setTimeout(connectTelemetry, reconnectDelay);
    reconnectDelay = Math.min(reconnectDelay * 1.5, MAX_RECONNECT_DELAY);
  };
  
  telemetryWs.onerror = (err) => {
    console.error('[Telemetry] WebSocket error:', err);
  };
}

function handleTelemetryMessage(msg) {
  if (msg.type === 'hardware_status') {
    const updateCard = (id, data) => {
      const badge = document.getElementById(`status-${id}`);
      const ping = document.getElementById(`ping-${id}`);
      if (!badge || !ping) return;
      
      if (data && data.connected) {
        badge.className = 'badge-status online';
        badge.textContent = '● Online';
        badge.style.background = 'rgba(16, 185, 129, 0.2)';
        badge.style.color = '#10b981';
        
        const ms = Math.round(data.ping_ms);
        ping.textContent = ms;
        
        // Limites Críticos de Latência (Osciloscópio exige mais velocidade que o Scanner)
        const limitDanger = (id === 'osc') ? 250 : 450;
        const limitWarning = (id === 'osc') ? 120 : 250;
        
        if (ms >= limitDanger) {
            ping.style.color = '#ef4444'; // Vermelho (Problema/Lag)
        } else if (ms >= limitWarning) {
            ping.style.color = '#f59e0b'; // Amarelo (Atenção/Oscilando)
        } else {
            ping.style.color = '#10b981'; // Verde (Excelente)
        }
      } else {
        badge.className = 'badge-status offline';
        badge.textContent = '● Offline';
        badge.style.background = 'rgba(239, 68, 68, 0.2)';
        badge.style.color = '#ef4444';
        ping.textContent = '--';
        ping.style.color = 'var(--text-muted)'; // Volta pra cor apagada
      }
    };
    
    // Atualiza tabela Meus Equipamentos com o status ao vivo por número de série individual
    if (msg.devices && typeof window.updateWorkshopDevicesOnlineStatus === 'function') {
      window.updateWorkshopDevicesOnlineStatus(msg.devices);
    }

    if (msg.nodes) {
      updateCard('scanner', msg.nodes['Scanner_CAN']);
      updateCard('osc', msg.nodes['Osciloscopio']);

      const fwScannerBadge = document.getElementById('fw-scanner-badge');
      if (fwScannerBadge && msg.nodes['Scanner_CAN'] && msg.nodes['Scanner_CAN'].fw_version) {
        fwScannerBadge.textContent = `FW: ${msg.nodes['Scanner_CAN'].fw_version}`;
      }
      
      // Atualiza indicador de hardware no Agente Dev
      if (typeof window.devAgentUpdateHwStatus === 'function') {
          window.devAgentUpdateHwStatus(msg.nodes);
      }

      // Update general nodes counter & header status pills
      let count = 0;
      let connectedSerials = [];
      if (msg.devices) {
        Object.entries(msg.devices).forEach(([s, d]) => {
          if (d.connected) {
            count++;
            connectedSerials.push(s);
          }
        });
      } else {
        if (msg.nodes['Scanner_CAN'] && msg.nodes['Scanner_CAN'].connected) count++;
        if (msg.nodes['Osciloscopio'] && msg.nodes['Osciloscopio'].connected) count++;
      }

      if (typeof window.state !== 'undefined') {
          window.state.hwNodes = count;
      }
      if (typeof state !== 'undefined') {
          state.hwNodes = count;
      }
      if (typeof updateHwNodes === 'function') {
          updateHwNodes();
      } else if (typeof window.updateHwNodes === 'function') {
          window.updateHwNodes();
      }

      // Atualiza Pill do Header (ESP32: Off / Online) de forma consistente
      if (typeof window.updateHwStatusPill === 'function') {
        window.updateHwStatusPill(count, connectedSerials.join(', '));
      } else {
        const wsPill = document.getElementById("ws-status-pill");
        const wsPillText = document.getElementById("ws-status-text");
        const wsPillDot = document.getElementById("ws-status-dot");
        if (wsPill && wsPillText && wsPillDot) {
          wsPill.classList.toggle('connected', count > 0);
          if (count > 0) {
            wsPillText.textContent = `Online: ${connectedSerials.join(', ') || 'HW Conectado'}`;
            wsPillDot.style.background = "var(--accent-green)";
            wsPillDot.classList.add("pulse");
          } else {
            wsPillText.textContent = "ESP32: Off";
            wsPillDot.style.background = "var(--accent-red)";
            wsPillDot.classList.remove("pulse");
          }
        }
      }
    }
  } else if (msg.type === 'ble_pair_status') {
    const el = document.getElementById('ble-paired-device');
    if (el) {
      if (msg.paired) {
        const currentMac = msg.paired_mac || msg.mac || "Nenhum";
        el.innerHTML = `<span style="color:var(--accent-green)">Vinculado: ${currentMac}</span>`;
      } else {
        el.innerHTML = 'Nenhum dispositivo pareado';
      }
    }
    // Ocultar resultados se conectou
    if (msg.connected) {
      const resultsPanel = document.getElementById('ble-scan-results');
      if (resultsPanel) resultsPanel.style.display = 'none';
    }
  } else if (msg.type === 'dtc_response') {
    renderDtcs(msg.raw);
  } else if (msg.type === 'dtc_cleared') {
    alert("DTCs limpos. Resposta: " + msg.raw);
    document.getElementById('health-report-list').innerHTML = "DTCs Limpos.";
  } else if (msg.type === 'live_data') {
    updateLiveData(msg);
  } else if (msg.type === 'obd_ready') {
    if (msg.status) alert("Scanner OBD-II Inicializado e Pronto!");
  } else if (msg.type === 'log') {
    appendTerminalLog(msg.message);
  } else if (msg.type === 'vehicle_auto_detected') {
    if (typeof handleVehicleAutoDetected === 'function') {
      handleVehicleAutoDetected(msg);
    }
  } else if (msg.query || msg.raw) {
    // Resposta direta do scanner ESP32 (ex: {"query":"010C", "raw":"04 41 0C..."})
    if (typeof handleScannerResponse === 'function') {
      handleScannerResponse(msg);
    }
  }
}

// As funções de interface do Scanner (startHealthReport, startLiveData, clearAllDtcs, etc)
// são gerenciadas pelo /static/scanner.js

function sendBleCommand(command, mac = null, extra = null) {
  if (telemetryWs && telemetryWs.readyState === WebSocket.OPEN) {
    let payload = { command };
    if (mac) payload.mac = mac;
    if (extra) Object.assign(payload, extra);
    
    if (command === 'scan_ble') {
      const list = document.getElementById('ble-device-list');
      if (list) list.innerHTML = '';
      const resultsPanel = document.getElementById('ble-scan-results');
      if (resultsPanel) resultsPanel.style.display = 'block';
    }
    
    telemetryWs.send(JSON.stringify(payload));
  } else {
    if (typeof showToast === 'function') {
      showToast('Aguardando reconexão com o servidor...', 'error');
    } else {
      console.warn('Conexão WebSocket não está ativa.');
    }
  }
}

// Iniciar conexão quando carregar
document.addEventListener('DOMContentLoaded', () => {
  connectTelemetry();
});

function appendTerminalLog(msg) {
  const sysLog = document.getElementById('sys-log');
  if (!sysLog) return;
  const now = new Date();
  const timeStr = String(now.getHours()).padStart(2, '0') + ':' +
                  String(now.getMinutes()).padStart(2, '0') + ':' +
                  String(now.getSeconds()).padStart(2, '0');
  
  const line = document.createElement('div');
  line.style.borderBottom = '1px solid rgba(255,255,255,0.05)';
  line.innerHTML = `<span style="color:var(--text-muted)">${timeStr}</span> <span style="color:var(--text-main)">${msg}</span>`;
  sysLog.appendChild(line);
  sysLog.scrollTop = sysLog.scrollHeight;
}

function clearTerminal() {
  const sysLog = document.getElementById('sys-log');
  if (sysLog) sysLog.innerHTML = '';
}

function sendTerminalCommand() {
  const input = document.getElementById('term-input');
  if (!input) return;
  const val = input.value.trim();
  if (!val) return;
  
  appendTerminalLog(`> ${val}`);
  
  if (telemetryWs && telemetryWs.readyState === WebSocket.OPEN) {
    telemetryWs.send(JSON.stringify({
      command: "terminal",
      data: val
    }));
  }
  input.value = '';
}
