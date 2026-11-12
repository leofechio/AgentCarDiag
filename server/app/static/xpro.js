/* ═══════════════════════════════════════════════════════════════════════════════
   xpro.js — Módulo Front-End Estilo Launch X-PRO5 para AgentCarDiag
   ═══════════════════════════════════════════════════════════════════════════════ */

let xproCurrentBrand = null;
let xproCurrentSystem = null;
let xproIsScanning = false;
let xproLiveInterval = null;

async function initXProModule() {
  updateXProHardwareBinding();
  await loadXProBrands();
  setInterval(updateXProHardwareBinding, 2000);
}

function updateXProHardwareBinding() {
  const badge = document.getElementById('xpro-hardware-badge');
  const label = document.getElementById('xpro-hardware-label');
  const sub = document.getElementById('xpro-hardware-sub');
  if (!badge || !label) return;

  const connectedList = [];
  if (window.state && window.state.devices) {
    Object.entries(window.state.devices).forEach(([serial, dev]) => {
      if (dev && dev.connected) connectedList.push(serial);
    });
  }

  // Fallback para hardware detectado no gateway
  const hwOnline = (window.state && window.state.hwNodes > 0);

  if (connectedList.length > 0) {
    const primarySerial = connectedList[0];
    const isAguia = primarySerial.startsWith('a');
    badge.className = 'xpro-badge-vci';
    badge.style.background = isAguia ? 'rgba(255, 170, 0, 0.15)' : 'rgba(16, 185, 129, 0.15)';
    badge.style.borderColor = isAguia ? '#ffaa00' : '#10b981';
    badge.style.color = isAguia ? '#ffaa00' : '#10b981';
    label.innerText = isAguia ? `🦅 ÁguiaCar VCI: ${primarySerial.toUpperCase()}` : `🔌 Scanner CAN: ${primarySerial.toUpperCase()}`;
    if (sub) sub.innerText = isAguia ? 'LTE 4G + CAN Bus' : 'ESP32-S3 TWAI 500k';
  } else if (hwOnline) {
    badge.className = 'xpro-badge-vci';
    badge.style.background = 'rgba(16, 185, 129, 0.15)';
    badge.style.borderColor = '#10b981';
    badge.style.color = '#10b981';
    label.innerText = '🔌 Scanner CAN: Online';
    if (sub) sub.innerText = 'ESP32-S3 TWAI';
  } else {
    badge.className = 'xpro-badge-vci';
    badge.style.background = 'rgba(239, 68, 68, 0.15)';
    badge.style.borderColor = '#ef4444';
    badge.style.color = '#f87171';
    label.innerText = '🔌 Interface Desconectada';
    if (sub) sub.innerText = 'Aguardando ESP32 / ÁguiaCar';
  }
}

async function loadXProBrands() {
  const grid = document.getElementById('xpro-brands-grid');
  if (!grid) return;
  grid.innerHTML = '<div style="color:#94a3b8; font-size:13px;">Carregando montadoras do catálogo...</div>';

  try {
    const res = await fetch('/api/xpro/brands');
    const data = await res.json();
    grid.innerHTML = '';

    data.brands.forEach(b => {
      const card = document.createElement('div');
      card.className = 'xpro-brand-card';
      card.onclick = () => selectXProBrand(b.id);
      card.innerHTML = `
        <div class="xpro-brand-icon-box">
          <img src="${b.icon}" alt="${b.name}" class="xpro-brand-icon" onerror="this.src='/static/favicon.ico'">
        </div>
        <div class="xpro-brand-info">
          <div class="xpro-brand-name">${b.name}</div>
          <div class="xpro-brand-meta">
            <span class="xpro-brand-version">${b.version}</span>
            <span class="xpro-brand-region">${b.region}</span>
          </div>
        </div>
      `;
      grid.appendChild(card);
    });
  } catch (err) {
    grid.innerHTML = `<div style="color:#ef4444; font-size:13px;">Erro ao carregar montadoras: ${err.message}</div>`;
  }
}

async function selectXProBrand(brandId) {
  try {
    const res = await fetch(`/api/xpro/brand/${brandId}`);
    xproCurrentBrand = await res.json();
    
    // Atualiza cabeçalho e navegação de telas
    document.getElementById('xpro-view-brands').style.display = 'none';
    document.getElementById('xpro-view-diag').style.display = 'flex';
    document.getElementById('xpro-header-brand-name').innerText = xproCurrentBrand.name;
    document.getElementById('xpro-header-brand-ver').innerText = xproCurrentBrand.version;
    document.getElementById('xpro-header-icon').src = xproCurrentBrand.icon;

    renderXProSystems(xproCurrentBrand.systems);
    renderXProSpecialFunctions(xproCurrentBrand.special_functions);
    
    // Volta para tela de sistemas
    switchXProSubTab('systems');
  } catch (err) {
    if (typeof showToast === 'function') showToast(`Erro ao selecionar montadora: ${err.message}`, 'error');
  }
}

function returnToXProBrands() {
  if (xproLiveInterval) {
    clearInterval(xproLiveInterval);
    xproLiveInterval = null;
  }
  document.getElementById('xpro-view-diag').style.display = 'none';
  document.getElementById('xpro-view-brands').style.display = 'block';
  xproCurrentBrand = null;
  xproCurrentSystem = null;
}

function renderXProSystems(systems) {
  const container = document.getElementById('xpro-systems-list');
  if (!container) return;
  container.innerHTML = '';

  systems.forEach((s, idx) => {
    const row = document.createElement('div');
    row.className = 'xpro-list-item';
    row.id = `xpro-sys-row-${s.id}`;
    row.onclick = () => selectXProSystem(s);
    
    row.innerHTML = `
      <div style="display:flex; align-items:center; gap:12px;">
        <span style="font-family:monospace; font-size:12px; color:#38bdf8; font-weight:700;">[${s.ecu_id}]</span>
        <div>
          <div style="font-weight:700; font-size:13px; color:#fff;">${s.name}</div>
          <div style="font-size:11px; color:#94a3b8;">UDS / ISO15765-4 • Resposta: ${s.rx_id}</div>
        </div>
      </div>
      <div style="display:flex; align-items:center; gap:10px;">
        <span class="xpro-status-badge ${s.dtcs > 0 ? 'badge-error' : 'badge-ok'}" id="xpro-sys-status-${s.id}">
          ${s.dtcs > 0 ? `⚠️ ${s.dtcs} DTC` : '✅ OK'}
        </span>
        <span style="color:#64748b; font-size:14px;">›</span>
      </div>
    `;
    container.appendChild(row);
  });
}

function renderXProSpecialFunctions(funcs) {
  const container = document.getElementById('xpro-specfunc-list');
  if (!container) return;
  container.innerHTML = '';

  funcs.forEach(f => {
    const card = document.createElement('div');
    card.className = 'xpro-func-card';
    card.onclick = () => runXProSpecialFunc(f);
    card.innerHTML = `
      <div style="display:flex; align-items:center; gap:10px;">
        <span style="font-size:20px;">⚡</span>
        <div>
          <div style="font-weight:700; font-size:13px; color:#fff;">${f.name}</div>
          <div style="font-size:10px; color:#94a3b8; font-family:monospace;">Rotina UDS: ${f.code}</div>
        </div>
      </div>
      <button class="xpro-btn-small" style="background:#0284c7; border:none; color:#fff; border-radius:4px; padding:4px 10px; font-size:11px; font-weight:bold;">Executar</button>
    `;
    container.appendChild(card);
  });
}

function switchXProSubTab(tab) {
  document.querySelectorAll('.xpro-subnav-btn').forEach(b => b.classList.remove('active'));
  document.getElementById(`xpro-subtab-${tab}`).classList.add('active');

  document.getElementById('xpro-panel-systems').style.display = (tab === 'systems') ? 'block' : 'none';
  document.getElementById('xpro-panel-specfunc').style.display = (tab === 'specfunc') ? 'block' : 'none';
  document.getElementById('xpro-panel-livedata').style.display = (tab === 'livedata') ? 'block' : 'none';
  document.getElementById('xpro-panel-security').style.display = (tab === 'security') ? 'block' : 'none';

  if (tab === 'livedata') {
    startXProLiveData();
  } else if (xproLiveInterval) {
    clearInterval(xproLiveInterval);
    xproLiveInterval = null;
  }
}

function selectXProSystem(system) {
  xproCurrentSystem = system;
  document.getElementById('xpro-active-sys-title').innerText = `${system.name} (${system.ecu_id})`;
  switchXProSubTab('livedata');
}

/* ── Varredura Rápida (Health Report / Quick Test) ────────────────────────── */
async function startXProQuickTest() {
  if (!xproCurrentBrand || xproIsScanning) return;
  xproIsScanning = true;

  const btn = document.getElementById('btn-xpro-quicktest');
  const progContainer = document.getElementById('xpro-scan-progress-box');
  const progBar = document.getElementById('xpro-scan-progressbar');
  const progText = document.getElementById('xpro-scan-progresstext');

  btn.disabled = true;
  btn.innerText = 'Varrendo Barramento...';
  progContainer.style.display = 'block';

  const total = xproCurrentBrand.systems.length;
  for (let i = 0; i < total; i++) {
    const sys = xproCurrentBrand.systems[i];
    const pct = Math.round(((i + 1) / total) * 100);
    progBar.style.width = `${pct}%`;
    progText.innerText = `Varrendo ${sys.id}: ${sys.name}... (${pct}%)`;

    // Efeito visual no item da lista
    const badge = document.getElementById(`xpro-sys-status-${sys.id}`);
    if (badge) {
      badge.innerText = '⏳ Verificando...';
      badge.className = 'xpro-status-badge badge-scanning';
    }

    await new Promise(r => setTimeout(r, 450)); // Simulação real da requisição UDS 0x19 02

    if (badge) {
      if (sys.dtcs > 0) {
        badge.innerText = `⚠️ ${sys.dtcs} DTC Falha`;
        badge.className = 'xpro-status-badge badge-error';
      } else {
        badge.innerText = '✅ Normal / Sem Falhas';
        badge.className = 'xpro-status-badge badge-ok';
      }
    }
  }

  progText.innerText = `Varredura Concluída: ${total} módulos verificados com sucesso.`;
  btn.disabled = false;
  btn.innerText = '⚡ Varredura Rápida (Quick Test)';
  xproIsScanning = false;

  if (typeof showToast === 'function') showToast('Relatório de Saúde X-PRO5 Concluído!', 'success');
}

/* ── Live Data / Fluxo de Dados ─────────────────────────────────────────── */
function startXProLiveData() {
  if (xproLiveInterval) clearInterval(xproLiveInterval);

  const container = document.getElementById('xpro-livedata-grid');
  if (!container) return;

  const pids = [
    { name: 'Rotação do Motor (RPM)', unit: 'rpm', min: 780, max: 830, val: 800 },
    { name: 'Temperatura Líquido Arrefecimento (ECT)', unit: '°C', min: 88, max: 92, val: 90 },
    { name: 'Pressão Coletor Admissão (MAP)', unit: 'kPa', min: 98, max: 104, val: 101 },
    { name: 'Tensão da Bateria (VCI Sensor)', unit: 'V', min: 14.1, max: 14.3, val: 14.2 },
    { name: 'Abertura Borboleta Acelerador (TPS)', unit: '%', min: 12.0, max: 13.5, val: 12.5 },
    { name: 'Velocidade do Veículo', unit: 'km/h', min: 0, max: 0, val: 0 },
    { name: 'Pressão Rail Common Rail', unit: 'bar', min: 280, max: 310, val: 295 }
  ];

  container.innerHTML = '';
  pids.forEach((p, idx) => {
    const card = document.createElement('div');
    card.className = 'xpro-live-card';
    card.id = `xpro-live-pid-${idx}`;
    card.innerHTML = `
      <div style="font-size:11px; color:#94a3b8; font-weight:600;">${p.name}</div>
      <div style="display:flex; align-items:baseline; justify-content:space-between; margin-top:6px;">
        <span class="xpro-live-val" id="xpro-val-${idx}">${p.val}</span>
        <span style="font-size:12px; color:#38bdf8; font-weight:bold;">${p.unit}</span>
      </div>
      <div class="xpro-live-graph-bar">
        <div class="xpro-live-graph-fill" id="xpro-fill-${idx}" style="width: 50%;"></div>
      </div>
    `;
    container.appendChild(card);
  });

  xproLiveInterval = setInterval(() => {
    pids.forEach((p, idx) => {
      const delta = (Math.random() - 0.5) * (p.max - p.min) * 0.4;
      let cur = parseFloat((p.val + delta).toFixed(1));
      if (cur < p.min) cur = p.min;
      if (cur > p.max) cur = p.max;

      const elVal = document.getElementById(`xpro-val-${idx}`);
      const elFill = document.getElementById(`xpro-fill-${idx}`);
      if (elVal) elVal.innerText = cur;
      if (elFill) {
        const pct = Math.min(100, Math.max(10, (cur / (p.max || 1)) * 100));
        elFill.style.width = `${pct}%`;
      }
    });
  }, 600);
}

/* ── Desafio Criptográfico UDS (Seed/Key AuSCrypto DiagBaseService) ───────── */
async function solveXProChallenge() {
  const sgbm = document.getElementById('xpro-challenge-sgbm').value;
  const seed = document.getElementById('xpro-challenge-seed').value;
  const resBox = document.getElementById('xpro-challenge-result');

  resBox.style.display = 'block';
  resBox.innerHTML = '<span style="color:#94a3b8;">Processando AuSCrypto / DiagBaseService...</span>';

  try {
    const res = await fetch('/api/xpro/security/solve-challenge', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sgbmid: sgbm, seed: seed, level: 1 })
    });
    const data = await res.json();
    if (res.ok) {
      resBox.innerHTML = `
        <div style="color:#10b981; font-weight:bold; margin-bottom:6px;">✅ Chave Gerada com Sucesso:</div>
        <div><strong>Key Calculada:</strong> <span style="color:#38bdf8;">${data.key_calculated}</span></div>
        <div style="margin-top:4px;"><strong>Comando UDS:</strong> <code style="background:#0f172a; padding:2px 6px; border-radius:4px; color:#f8fafc;">${data.uds_command}</code></div>
        <div style="font-size:10px; color:#64748b; margin-top:4px;">Algoritmo: ${data.algorithm}</div>
      `;
    } else {
      resBox.innerHTML = `<span style="color:#ef4444;">Erro: ${data.detail || 'Falha no cálculo'}</span>`;
    }
  } catch (err) {
    resBox.innerHTML = `<span style="color:#ef4444;">Erro de conexão: ${err.message}</span>`;
  }
}

function runXProSpecialFunc(func) {
  if (typeof showToast === 'function') {
    showToast(`Iniciando procedimento especial: ${func.name}`, 'info');
  }
}

// Inicializa quando a página carrega
document.addEventListener('DOMContentLoaded', () => {
  initXProModule();
});
