// workshops.js — Painel do Cliente / Oficina (Autenticação, Meus Equipamentos e Gatekeeper de Scanner)

let currentUser = null;
let currentWorkshopId = "oficina-matriz";
let workshopDevices = [];

// Inicialização
document.addEventListener("DOMContentLoaded", () => {
    initClientWorkshop();
});

async function initClientWorkshop() {
    await loadCurrentUser();
    await loadWorkshopDevices();
}

// 1. Carrega dados do Usuário / Oficina Logada
async function loadCurrentUser() {
    try {
        const res = await fetch("/api/auth/me");
        if (!res.ok) return;
        currentUser = await res.json();
        
        currentWorkshopId = currentUser.workshop_id || "oficina-matriz";

        // Atualiza cabeçalho com nome da oficina
        const headerName = document.getElementById("header-workshop-name");
        if (headerName) {
            headerName.textContent = `🏢 ${currentUser.name || currentUser.username}`;
            headerName.title = `Oficina: ${currentUser.name} (Usuário: ${currentUser.username})`;
        }

        // Se for admin, exibe o link para o Painel da Fábrica
        const adminLink = document.getElementById("header-admin-link");
        if (adminLink && currentUser.is_admin) {
            adminLink.style.display = "inline-block";
        }

        // Atualiza subtítulo do painel de equipamentos
        const subtitle = document.getElementById("client-panel-subtitle");
        if (subtitle) {
            subtitle.textContent = `Aparelhos autorizados para: ${currentUser.name}`;
        }
    } catch (e) {
        console.warn("Erro ao identificar usuário logado:", e);
    }
}

// 2. Carrega Aparelhos Vinculados a Esta Oficina
async function loadWorkshopDevices() {
    if (!currentWorkshopId) return;

    try {
        const res = await fetch(`/api/workshops/${currentWorkshopId}/devices`);
        if (!res.ok) return;
        workshopDevices = await res.json();

        const container = document.getElementById("workshop-devices-table-body");
        const emptyMsg = document.getElementById("workshop-devices-empty");
        const countBadge = document.getElementById("workshop-active-devices-count");

        if (countBadge) countBadge.textContent = `${workshopDevices.length}`;

        // Estado global de conectividade ao vivo de hardwares
        window.activeHardwareSerials = window.activeHardwareSerials || {};

        if (container) {
            container.innerHTML = "";
            if (workshopDevices.length === 0) {
                if (emptyMsg) emptyMsg.style.display = "block";
            } else {
                if (emptyMsg) emptyMsg.style.display = "none";
                workshopDevices.forEach(d => {
                    const tr = document.createElement("tr");
                    tr.style.borderBottom = "1px solid var(--border-subtle)";
                    const cleanSerial = (d.serial_number || '').trim().toLowerCase();
                    const isOnline = window.activeHardwareSerials && window.activeHardwareSerials[cleanSerial] && window.activeHardwareSerials[cleanSerial].connected;
                    const pingMs = isOnline ? Math.round(window.activeHardwareSerials[cleanSerial].ping_ms || 0) : null;
                    
                    let typeBadge = "🚗 Scanner CAN Pro";
                    if (d.device_type === "AGUIACAR_4G" || d.device_type === "fleet_tracker") typeBadge = "🦅 AguiaCar 4G";
                    else if (d.device_type === "OSCILOSCOPIO" || d.device_type === "oscilloscope") typeBadge = "📡 Osciloscópio";

                    const devFw = (devInfo && devInfo.fw_version) ? devInfo.fw_version : (d.fw_version || 'v2.5.2');

                    tr.innerHTML = `
                        <td style="padding:10px; font-family:monospace; font-weight:bold; color:var(--accent-cyan); font-size:13px;">${d.serial_number}</td>
                        <td style="padding:10px;" id="device-online-cell-${cleanSerial}">
                            <span style="display:inline-flex; align-items:center; gap:6px; padding:3px 8px; border-radius:12px; font-size:11px; font-weight:bold; ${isOnline ? 'background:rgba(16,185,129,0.15); color:#10b981; border:1px solid rgba(16,185,129,0.3);' : 'background:rgba(239,68,68,0.1); color:#ef4444; border:1px solid rgba(239,68,68,0.2);'}">
                                <span style="display:inline-block; width:7px; height:7px; border-radius:50%; background:${isOnline ? '#10b981' : '#ef4444'};"></span>
                                ${isOnline ? `Online (${pingMs}ms)` : 'Offline'}
                            </span>
                        </td>
                        <td style="padding:10px;" id="device-fw-cell-${cleanSerial}">
                            <span style="background:rgba(0,212,255,0.1); color:var(--accent-cyan); padding:2px 8px; border-radius:4px; font-family:monospace; font-weight:bold; font-size:11px;">
                                ${devFw}
                            </span>
                        </td>
                        <td style="padding:10px;"><span style="background:rgba(255,255,255,0.06); padding:3px 8px; border-radius:4px; font-size:11px;">${typeBadge}</span></td>
                        <td style="padding:10px; color:var(--text-secondary);">${d.model_name}</td>
                        <td style="padding:10px; font-size:11px; color:var(--text-muted);">${d.batch_code || 'LOTE-2026'}</td>
                        <td style="padding:10px;"><span style="color:var(--accent-green); font-size:12px; font-weight:bold;">● Ativo & Autorizado</span></td>
                    `;
                    container.appendChild(tr);
                });
            }
        }

        // Aplica Gatekeeper no Scanner
        checkGatekeeperScanner();
    } catch (e) {
        console.warn("Erro ao carregar aparelhos da oficina:", e);
    }
}

// Atualização ao vivo disparada pelo WebSocket de telemetria
window.updateWorkshopDevicesOnlineStatus = function(devicesMap) {
    window.activeHardwareSerials = devicesMap || {};
    if (!workshopDevices || workshopDevices.length === 0) return;

    workshopDevices.forEach(d => {
        const cleanSerial = (d.serial_number || '').trim().toLowerCase();
        const cell = document.getElementById(`device-online-cell-${cleanSerial}`);
        if (!cell) return;

        const devInfo = devicesMap && devicesMap[cleanSerial];
        const isOnline = devInfo && devInfo.connected;
        const pingMs = isOnline ? Math.round(devInfo.ping_ms || 0) : null;

        cell.innerHTML = `
            <span style="display:inline-flex; align-items:center; gap:6px; padding:3px 8px; border-radius:12px; font-size:11px; font-weight:bold; ${isOnline ? 'background:rgba(16,185,129,0.15); color:#10b981; border:1px solid rgba(16,185,129,0.3);' : 'background:rgba(239,68,68,0.1); color:#ef4444; border:1px solid rgba(239,68,68,0.2);'}">
                <span style="display:inline-block; width:7px; height:7px; border-radius:50%; background:${isOnline ? '#10b981' : '#ef4444'};"></span>
                ${isOnline ? `Online (${pingMs}ms)` : 'Offline'}
            </span>
        `;

        const fwCell = document.getElementById(`device-fw-cell-${cleanSerial}`);
        if (fwCell && devInfo && devInfo.fw_version) {
            fwCell.innerHTML = `
                <span style="background:rgba(0,212,255,0.1); color:var(--accent-cyan); padding:2px 8px; border-radius:4px; font-family:monospace; font-weight:bold; font-size:11px;">
                    ${devInfo.fw_version}
                </span>
            `;
        }
    });
};

// 3. Gatekeeper: Bloqueia ou Libera o Scanner OBD-II
function checkGatekeeperScanner() {
    const hasScanner = workshopDevices.some(d => d.device_type === "SCANNER_CAN" || d.device_type === "SCANNER_OBD");
    const gatekeeperBox = document.getElementById("scanner-gatekeeper-overlay");
    const scannerControls = document.getElementById("scanner-operational-controls");

    if (gatekeeperBox && scannerControls) {
        if (!hasScanner) {
            // Bloqueia e exibe tela de ativação
            gatekeeperBox.style.display = "flex";
            scannerControls.style.display = "none";
        } else {
            // Libera o uso total da aba Scanner
            gatekeeperBox.style.display = "none";
            scannerControls.style.display = "block";
        }
    }
}

// 4. Ativação de Aparelho por Número de Série (Claim)
async function claimDeviceBySerial(forcedSerial = null) {
    const input = document.getElementById("claim-serial-input");
    const serial = forcedSerial || (input ? input.value.trim().toLowerCase() : "");

    if (!serial) {
        alert("Por favor, digite o Número de Série gravado no aparelho (ex: s2001, a2001 ou o2001)");
        return;
    }

    try {
        const res = await fetch("/api/workshops/devices/claim", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                serial_number: serial,
                workshop_id: currentWorkshopId
            })
        });

        const data = await res.json();
        if (!res.ok) {
            alert(`Falha na Ativação: ${data.detail || 'Número de série não encontrado ou inválido.'}`);
            return;
        }

        if (input) input.value = "";
        alert(`🎉 ${data.msg}\nO Scanner foi liberado para uso imediato nesta oficina!`);

        if (window.showToast) showToast(`✅ ${data.msg}`, "success");
        if (window.sysLog) sysLog(`Equipamento ${serial} ativado com sucesso para esta oficina`, "success");

        await loadWorkshopDevices();
    } catch (e) {
        alert("Erro de conexão ao ativar equipamento: " + e.message);
    }
}
