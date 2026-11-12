let ws = null;
let allSms = [];
let allCalls = [];
let currentMainTab = 'sms';
let batteryChartInstance = null;
let activeDeviceId = null;

// Suporte dinâmico para rodar tanto na raiz quanto em subcaminhos como /homesim
const BASE_PATH = window.location.pathname.startsWith('/homesim') ? '/homesim' : '';

// Inicialização
function initHomeSim() {
    initWebSocket();
    loadDevices();
    loadSmsList();
    loadCallsList();
    loadSettings();
    initBatteryChart();
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initHomeSim);
} else {
    initHomeSim();
}

// Toast visual
function showToast(message, isSuccess = true) {
    const toast = document.getElementById('toast');
    const toastMessage = document.getElementById('toastMessage');
    toastMessage.textContent = message;
    toast.className = `fixed bottom-6 right-6 z-50 ${isSuccess ? 'bg-indigo-600' : 'bg-rose-600'} text-white text-xs font-medium px-4 py-3 rounded-xl shadow-xl flex items-center space-x-2 transition-all duration-300 opacity-100 translate-y-0`;
    setTimeout(() => {
        toast.className = toast.className.replace('opacity-100 translate-y-0', 'opacity-0 translate-y-4 pointer-events-none');
    }, 3000);
}

// Som de notificação em Web Audio API (não depende de arquivo de áudio externo)
function playNotificationChime() {
    try {
        const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        const osc = audioCtx.createOscillator();
        const gain = audioCtx.createGain();
        osc.connect(gain);
        gain.connect(audioCtx.destination);
        
        osc.type = 'sine';
        osc.frequency.setValueAtTime(587.33, audioCtx.currentTime); // D5
        osc.frequency.setValueAtTime(880, audioCtx.currentTime + 0.1); // A5
        gain.gain.setValueAtTime(0.15, audioCtx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.001, audioCtx.currentTime + 0.35);
        
        osc.start();
        osc.stop(audioCtx.currentTime + 0.35);
    } catch (e) {
        console.log("Audio contextual block:", e);
    }
}

// WebSocket Live Engine
function initWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}${BASE_PATH}/ws/live`;

    const wsDot = document.getElementById('wsDot');
    const wsText = document.getElementById('wsText');

    try {
        ws = new WebSocket(wsUrl);

        ws.onopen = () => {
            wsDot.className = 'w-2.5 h-2.5 rounded-full bg-emerald-400';
            wsText.textContent = 'Tempo Real Ativo';
        };

        ws.onmessage = (event) => {
            try {
                const payload = JSON.parse(event.data);
                handleLiveEvent(payload);
            } catch (err) {
                console.error('Erro ao processar mensagem WS:', err);
            }
        };

        ws.onclose = () => {
            wsDot.className = 'w-2.5 h-2.5 rounded-full bg-amber-400 status-pulse';
            wsText.textContent = 'Reconectando...';
            setTimeout(initWebSocket, 4000);
        };

        ws.onerror = () => {
            ws.close();
        };
    } catch (e) {
        console.error('Falha ao abrir WebSocket:', e);
        setTimeout(initWebSocket, 5000);
    }
}

function handleLiveEvent(msg) {
    if (msg.event === 'telemetry_update') {
        updateDeviceUI(msg.data);
        if (msg.data.device_id === activeDeviceId) {
            appendBatteryChartPoint(msg.data.battery_level, msg.data.last_seen);
        }
    } else if (msg.event === 'new_sms') {
        playNotificationChime();
        showToast(`Novo SMS recebido de ${msg.data.sender}!`);
        allSms.unshift(msg.data);
        renderSmsList(allSms);
        updateSmsStats();
    } else if (msg.event === 'new_call') {
        playNotificationChime();
        const typeLabel = msg.data.call_type === 'missed' ? 'Chamada Perdida' : 'Chamada';
        showToast(`Nova ${typeLabel} de ${msg.data.number}!`, msg.data.call_type !== 'missed');
        allCalls.unshift(msg.data);
        renderCallsList(allCalls);
        updateCallsStats();
    }
}

// Dispositivos e Telemetria
async function loadDevices() {
    try {
        const res = await fetch(`${BASE_PATH}/api/devices`);
        const devices = await res.json();
        if (devices && devices.length > 0) {
            const dev = devices[0];
            activeDeviceId = dev.id;
            updateDeviceUI(dev);
            loadDeviceHistory(dev.id);
        }
    } catch (err) {
        console.error('Erro ao carregar dispositivos:', err);
    }
}

function parseIsoToDate(isoStr) {
    if (!isoStr) return new Date();
    // Se não tiver indicador de timezone nem offset (+ ou -), adiciona 'Z' (UTC)
    if (!isoStr.endsWith('Z') && !/[+-]\d{2}:\d{2}$/.test(isoStr)) {
        return new Date(isoStr + 'Z');
    }
    return new Date(isoStr);
}

function updateDeviceUI(dev) {
    document.getElementById('devName').textContent = dev.name || dev.device_name || 'HomeSIM Sentinel';
    
    // Status Online / Offline
    const lastSeenDate = parseIsoToDate(dev.last_seen);
    const diffMinutes = Math.floor((Date.now() - lastSeenDate.getTime()) / (1000 * 60));
    const isOnline = diffMinutes < 15;

    const devStatusDot = document.getElementById('devStatusDot');
    const devStatusText = document.getElementById('devStatusText');
    const devLastSeen = document.getElementById('devLastSeen');

    if (isOnline) {
        devStatusDot.className = 'w-2.5 h-2.5 rounded-full bg-emerald-400';
        devStatusText.className = 'text-emerald-400 font-semibold';
        devStatusText.textContent = 'Online & Vigiando';
    } else {
        devStatusDot.className = 'w-2.5 h-2.5 rounded-full bg-rose-500';
        devStatusText.className = 'text-rose-400 font-semibold';
        devStatusText.textContent = `Offline há ${diffMinutes} min`;
    }
    devLastSeen.textContent = `Último contato: ${lastSeenDate.toLocaleTimeString('pt-BR')} (${diffMinutes === 0 ? 'agora há pouco' : diffMinutes + 'm atrás'})`;

    // Bateria
    const batt = dev.battery_level !== undefined ? dev.battery_level : 0;
    const isCharging = Boolean(dev.is_charging);
    document.getElementById('batteryPercent').textContent = `${batt}%`;
    
    const battBar = document.getElementById('batteryBar');
    battBar.style.width = `${Math.min(100, Math.max(0, batt))}%`;
    if (batt <= 20) {
        battBar.className = 'bg-rose-500 h-full transition-all duration-500';
    } else if (batt <= 40) {
        battBar.className = 'bg-amber-500 h-full transition-all duration-500';
    } else {
        battBar.className = 'bg-emerald-500 h-full transition-all duration-500';
    }

    const chgStatus = document.getElementById('chargingStatus');
    const chgIcon = document.getElementById('chargingIcon');
    if (isCharging) {
        chgStatus.textContent = 'Carregando (Tomada)';
        chgStatus.className = 'text-xs px-2 py-0.5 rounded bg-amber-500/20 text-amber-300 border border-amber-500/30';
        chgIcon.className = 'fa-solid fa-bolt text-amber-400';
    } else {
        chgStatus.textContent = 'Na Bateria (Desplugado!)';
        chgStatus.className = 'text-xs px-2 py-0.5 rounded bg-rose-500/20 text-rose-300 border border-rose-500/30';
        chgIcon.className = 'fa-solid fa-battery-half text-slate-400';
    }

    const temp = dev.battery_temp ? Number(dev.battery_temp).toFixed(1) : '26.0';
    document.getElementById('batteryTemp').textContent = `${temp} °C`;
    const healthBadge = document.getElementById('batteryHealthBadge');
    if (Number(temp) > 42) {
        healthBadge.textContent = 'Superaquecendo!';
        healthBadge.className = 'text-rose-400 font-bold';
    } else {
        healthBadge.textContent = 'Segura';
        healthBadge.className = 'text-emerald-400';
    }

    // Chip & Rede
    document.getElementById('carrierName').textContent = dev.carrier_name || 'Operadora Móvel';
    const sigLevel = dev.signal_level !== undefined ? dev.signal_level : 3;
    const sigDbm = dev.signal_strength_dbm || -85;
    document.getElementById('signalText').textContent = `${sigDbm} dBm (${sigLevel}/4)`;

    // Barras de sinal
    const barSpans = document.querySelectorAll('#signalBars span');
    barSpans.forEach((span, idx) => {
        if (idx < sigLevel) {
            span.className = 'w-1.5 rounded-sm bg-emerald-400';
            if (idx === 0) span.classList.add('h-1.5');
            if (idx === 1) span.classList.add('h-2.5');
            if (idx === 2) span.classList.add('h-3.5');
            if (idx === 3) span.classList.add('h-4');
        } else {
            span.className = 'w-1.5 rounded-sm bg-slate-700';
            if (idx === 0) span.classList.add('h-1.5');
            if (idx === 1) span.classList.add('h-2.5');
            if (idx === 2) span.classList.add('h-3.5');
            if (idx === 3) span.classList.add('h-4');
        }
    });

    document.getElementById('wifiSsid').textContent = dev.wifi_ssid || 'Conectado';
    document.getElementById('wifiIp').textContent = dev.wifi_ip || '--';
}

// Histórico de Bateria no Chart.js
function initBatteryChart() {
    const ctx = document.getElementById('batteryChart').getContext('2d');
    batteryChartInstance = new Chart(ctx, {
        type: 'line',
        data: {
            labels: [],
            datasets: [{
                label: 'Bateria (%)',
                data: [],
                borderColor: '#10b981',
                backgroundColor: 'rgba(16, 185, 129, 0.1)',
                borderWidth: 2,
                fill: true,
                tension: 0.3,
                pointRadius: 2,
                pointHoverRadius: 5
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                y: {
                    min: 0,
                    max: 100,
                    grid: { color: 'rgba(51, 65, 85, 0.3)' },
                    ticks: { color: '#94a3b8', font: { size: 10 } }
                },
                x: {
                    grid: { display: false },
                    ticks: { color: '#94a3b8', font: { size: 9 }, maxTicksLimit: 6 }
                }
            },
            plugins: {
                legend: { display: false }
            }
        }
    });
}

async function loadDeviceHistory(deviceId) {
    try {
        const res = await fetch(`${BASE_PATH}/api/devices/${deviceId}/history?limit=30`);
        const history = await res.json();
        if (batteryChartInstance && history.length > 0) {
            const labels = history.map(h => {
                const d = new Date(h.created_at);
                return `${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`;
            });
            const data = history.map(h => h.battery_level);
            batteryChartInstance.data.labels = labels;
            batteryChartInstance.data.datasets[0].data = data;
            batteryChartInstance.update();
        }
    } catch (err) {
        console.error('Erro ao carregar histórico:', err);
    }
}

function appendBatteryChartPoint(batteryLevel, timestamp) {
    if (!batteryChartInstance) return;
    const d = new Date(timestamp);
    const label = `${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`;
    
    batteryChartInstance.data.labels.push(label);
    batteryChartInstance.data.datasets[0].data.push(batteryLevel);
    if (batteryChartInstance.data.labels.length > 30) {
        batteryChartInstance.data.labels.shift();
        batteryChartInstance.data.datasets[0].data.shift();
    }
    batteryChartInstance.update();
}

// SMS Inbox
async function loadSmsList() {
    try {
        const res = await fetch(`${BASE_PATH}/api/sms`);
        allSms = await res.json();
        renderSmsList(allSms);
        updateSmsStats();
    } catch (err) {
        console.error('Erro ao buscar lista de SMS:', err);
    }
}

function updateSmsStats() {
    document.getElementById('totalSmsCount').textContent = allSms.length;
    document.getElementById('smsBadgeCount').textContent = allSms.length;
    const otpCount = allSms.filter(s => s.otp_code && s.otp_code.length > 0).length;
    document.getElementById('totalOtpCount').textContent = otpCount;
}

function renderSmsList(items) {
    const list = document.getElementById('smsList');
    const emptyState = document.getElementById('emptySmsState');

    if (!items || items.length === 0) {
        list.innerHTML = '';
        list.appendChild(emptyState);
        emptyState.classList.remove('hidden');
        return;
    }

    list.innerHTML = '';
    items.forEach(sms => {
        const card = createSmsCard(sms);
        list.appendChild(card);
    });
}

function createSmsCard(sms) {
    const div = document.createElement('div');
    div.className = 'bg-slate-800/80 border border-slate-700/60 rounded-xl p-4 transition hover:border-slate-600 shadow-sm space-y-2.5';

    const receivedDate = parseIsoToDate(sms.received_at);
    const timeFormatted = receivedDate.toLocaleString('pt-BR', {
        day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit'
    });

    let otpBlock = '';
    if (sms.otp_code) {
        otpBlock = `
            <div class="mt-2.5 p-3 rounded-xl bg-indigo-950/70 border border-indigo-500/40 flex items-center justify-between">
                <div class="flex items-center space-x-2.5">
                    <span class="w-2 h-2 rounded-full bg-indigo-400"></span>
                    <div>
                        <span class="text-[10px] uppercase font-bold text-indigo-300 block">Código de Verificação 2FA</span>
                        <span class="text-xl font-extrabold text-white otp-badge">${escapeHtml(sms.otp_code)}</span>
                    </div>
                </div>
                <button onclick="copyToClipboard('${escapeHtml(sms.otp_code)}')" class="flex items-center space-x-1.5 px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white font-semibold text-xs shadow-md transition active:scale-95">
                    <i class="fa-solid fa-copy"></i>
                    <span>Copiar Código</span>
                </button>
            </div>
        `;
    }

    div.innerHTML = `
        <div class="flex items-center justify-between">
            <div class="flex items-center space-x-2">
                <span class="w-8 h-8 rounded-lg bg-slate-700/80 flex items-center justify-center text-slate-300 font-bold text-xs">
                    <i class="fa-solid fa-comment-dots text-indigo-400"></i>
                </span>
                <div>
                    <h4 class="font-bold text-white text-sm">${escapeHtml(sms.sender)}</h4>
                    <span class="text-[11px] text-slate-400">${timeFormatted}</span>
                </div>
            </div>
            ${sms.otp_code ? '<span class="text-[10px] bg-indigo-500/20 text-indigo-300 border border-indigo-500/30 px-2 py-0.5 rounded-md font-semibold">2FA DETECTADO</span>' : ''}
        </div>
        <p class="text-xs text-slate-300 leading-relaxed font-sans">${escapeHtml(sms.body)}</p>
        ${otpBlock}
    `;

    return div;
}

function filterSmsList() {
    const term = document.getElementById('smsSearchInput').value.toLowerCase().trim();
    if (!term) {
        renderSmsList(allSms);
        return;
    }
    const filtered = allSms.filter(s => 
        (s.sender && s.sender.toLowerCase().includes(term)) ||
        (s.body && s.body.toLowerCase().includes(term)) ||
        (s.otp_code && s.otp_code.toLowerCase().includes(term))
    );
    renderSmsList(filtered);
}

function copyToClipboard(text) {
    navigator.clipboard.writeText(text).then(() => {
        showToast(`Código "${text}" copiado com sucesso!`);
    }).catch(err => {
        console.error('Falha ao copiar:', err);
    });
}

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Pareamento por QR Code
let pairQrInstance = null;

async function openPairModal() {
    const modal = document.getElementById('pairModal');
    const container = document.getElementById('qrcodeContainer');
    const info = document.getElementById('pairTokenInfo');
    
    modal.classList.remove('hidden');
    container.innerHTML = '<span class="text-xs text-slate-500 py-8">Gerando QR Code...</span>';
    info.textContent = 'Solicitando token seguro...';

    try {
        const res = await fetch(`${BASE_PATH}/api/devices/pair-token`, { method: 'POST' });
        const data = await res.json();
        const pairToken = data.token;

        // Monta o payload JSON que o app Android espera
        // Usa a URL base completa atual do navegador (incluindo /homesim se houver)
        const serverOrigin = window.location.origin + BASE_PATH;
        const qrPayload = JSON.stringify({
            server_url: serverOrigin,
            token: pairToken,
            e2ee_secret: "homesim_default_secret"
        });

        container.innerHTML = '';
        pairQrInstance = new QRCode(container, {
            text: qrPayload,
            width: 180,
            height: 180,
            colorDark: "#020617",
            colorLight: "#ffffff",
            correctLevel: QRCode.CorrectLevel.M
        });

        info.textContent = `Token: ${pairToken.substring(0, 15)}... (válido por 15m)`;
    } catch (err) {
        container.innerHTML = '<span class="text-xs text-rose-500 py-4">Erro ao gerar QR Code</span>';
        info.textContent = 'Verifique a conexão com o servidor.';
    }
}

function closePairModal() {
    document.getElementById('pairModal').classList.add('hidden');
}

// Configurações e Modais
function openSettingsModal() {
    document.getElementById('settingsModal').classList.remove('hidden');
}

function closeSettingsModal() {
    document.getElementById('settingsModal').classList.add('hidden');
}

async function loadSettings() {
    try {
        const res = await fetch(`${BASE_PATH}/api/settings`);
        const settings = await res.json();
        if (settings) {
            if (settings.telegram_bot_token) document.getElementById('cfgTgToken').value = settings.telegram_bot_token;
            if (settings.telegram_chat_id) document.getElementById('cfgTgChatId').value = settings.telegram_chat_id;
            if (settings.offline_alert_minutes) document.getElementById('cfgOfflineMinutes').value = settings.offline_alert_minutes;
        }
    } catch (err) {
        console.error('Erro ao carregar configurações:', err);
    }
}

async function saveSettings() {
    const payload = {
        telegram_bot_token: document.getElementById('cfgTgToken').value.trim(),
        telegram_chat_id: document.getElementById('cfgTgChatId').value.trim(),
        offline_alert_minutes: parseInt(document.getElementById('cfgOfflineMinutes').value, 10) || 30
    };

    try {
        const res = await fetch(`${BASE_PATH}/api/settings`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        if (res.ok) {
            alert('Configurações salvas com sucesso!');
        } else {
            alert('Erro ao salvar configurações.');
        }
    } catch (err) {
        console.error('Erro ao salvar configs:', err);
        alert('Falha na comunicação ao salvar configurações.');
    }
}

// Gerenciamento de Abas e Chamadas
function switchMainTab(tab) {
    currentMainTab = tab;
    const tabSmsBtn = document.getElementById('tabSmsBtn');
    const tabCallsBtn = document.getElementById('tabCallsBtn');
    const smsPanel = document.getElementById('smsPanel');
    const callsPanel = document.getElementById('callsPanel');

    if (tab === 'sms') {
        tabSmsBtn.className = 'px-3 py-1.5 rounded-xl font-bold text-xs bg-indigo-600 text-white shadow transition flex items-center space-x-1.5';
        tabCallsBtn.className = 'px-3 py-1.5 rounded-xl font-bold text-xs bg-slate-800 text-slate-400 hover:text-white transition flex items-center space-x-1.5';
        smsPanel.classList.remove('hidden');
        callsPanel.classList.add('hidden');
    } else {
        tabCallsBtn.className = 'px-3 py-1.5 rounded-xl font-bold text-xs bg-indigo-600 text-white shadow transition flex items-center space-x-1.5';
        tabSmsBtn.className = 'px-3 py-1.5 rounded-xl font-bold text-xs bg-slate-800 text-slate-400 hover:text-white transition flex items-center space-x-1.5';
        callsPanel.classList.remove('hidden');
        smsPanel.classList.add('hidden');
    }
}

function refreshActiveTab() {
    if (currentMainTab === 'sms') {
        loadSmsList();
    } else {
        loadCallsList();
    }
}

function filterActiveList() {
    const term = document.getElementById('smsSearchInput').value.toLowerCase().trim();
    if (currentMainTab === 'sms') {
        if (!term) return renderSmsList(allSms);
        const filtered = allSms.filter(s =>
            (s.sender && s.sender.toLowerCase().includes(term)) ||
            (s.body && s.body.toLowerCase().includes(term)) ||
            (s.otp_code && s.otp_code.toLowerCase().includes(term))
        );
        renderSmsList(filtered);
    } else {
        if (!term) return renderCallsList(allCalls);
        const filtered = allCalls.filter(c =>
            (c.number && c.number.toLowerCase().includes(term)) ||
            (c.caller_name && c.caller_name.toLowerCase().includes(term)) ||
            (c.call_type && c.call_type.toLowerCase().includes(term))
        );
        renderCallsList(filtered);
    }
}

async function loadCallsList() {
    try {
        const res = await fetch(`${BASE_PATH}/api/calls`);
        allCalls = await res.json();
        renderCallsList(allCalls);
        updateCallsStats();
    } catch (err) {
        console.error('Erro ao buscar lista de chamadas:', err);
    }
}

function updateCallsStats() {
    const badge = document.getElementById('callsBadgeCount');
    if (badge) badge.textContent = allCalls.length;
}

function renderCallsList(items) {
    const list = document.getElementById('callsList');
    const emptyState = document.getElementById('emptyCallsState');

    if (!items || items.length === 0) {
        list.innerHTML = '';
        list.appendChild(emptyState);
        emptyState.classList.remove('hidden');
        return;
    }

    list.innerHTML = '';
    items.forEach(call => {
        const card = createCallCard(call);
        list.appendChild(card);
    });
}

function createCallCard(call) {
    const div = document.createElement('div');
    div.className = 'bg-slate-800/80 border border-slate-700/60 rounded-xl p-4 transition hover:border-slate-600 shadow-sm space-y-2';

    const receivedDate = parseIsoToDate(call.received_at);
    const timeFormatted = receivedDate.toLocaleString('pt-BR', {
        day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit'
    });

    const isMissed = call.call_type === 'missed';
    const isIncoming = call.call_type === 'incoming';

    let iconHtml = '<i class="fa-solid fa-phone-slash text-rose-400"></i>';
    let typeBadge = '<span class="text-[10px] bg-rose-500/20 text-rose-300 border border-rose-500/30 px-2 py-0.5 rounded-md font-semibold">CHAMADA PERDIDA</span>';

    if (isIncoming) {
        iconHtml = '<i class="fa-solid fa-phone-arrow-down-left text-emerald-400"></i>';
        typeBadge = '<span class="text-[10px] bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 px-2 py-0.5 rounded-md font-semibold">RECEBIDA</span>';
    } else if (call.call_type === 'rejected') {
        iconHtml = '<i class="fa-solid fa-phone-slash text-amber-400"></i>';
        typeBadge = '<span class="text-[10px] bg-amber-500/20 text-amber-300 border border-amber-500/30 px-2 py-0.5 rounded-md font-semibold">RECUSADA</span>';
    }

    const durationStr = call.duration_seconds > 0 ? `${call.duration_seconds} seg` : '';

    div.innerHTML = `
        <div class="flex items-center justify-between">
            <div class="flex items-center space-x-3">
                <span class="w-9 h-9 rounded-lg bg-slate-700/80 flex items-center justify-center text-sm">
                    ${iconHtml}
                </span>
                <div>
                    <h4 class="font-bold text-white text-sm flex items-center space-x-2">
                        <span>${escapeHtml(call.number)}</span>
                        ${call.caller_name ? `<span class="text-xs text-slate-400 font-normal">(${escapeHtml(call.caller_name)})</span>` : ''}
                    </h4>
                    <span class="text-[11px] text-slate-400">${timeFormatted} ${durationStr ? '• Duração: ' + durationStr : ''}</span>
                </div>
            </div>
            ${typeBadge}
        </div>
    `;

    return div;
}
