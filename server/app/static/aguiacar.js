/**
 * aguiacar.js — Frontend do AguiaCar Fleet Guardian
 * Gerenciamento de mapa ao vivo, telemetria telemática, guardião mecânico e configurações remotas.
 */

let fleetMap = null;
let vehicleMarker = null;
let routePolyline = null;
let currentVehicleId = null;
let routePoints = [];

// Coordenadas padrão da oficina / Espanha
const defaultCoords = [42.580346, -5.584364];

document.addEventListener("DOMContentLoaded", () => {
    // Inicializa quando a aba AguiaCar for clicada
    const tabAguia = document.getElementById("tab-aguiacar");
    if (tabAguia) {
        tabAguia.addEventListener("click", () => {
            setTimeout(async () => {
                await detectActiveVehicle();
                initFleetMap();
                if (currentVehicleId) {
                    loadFleetData();
                    loadFleetConfig();
                    loadFleetAlerts();
                }
            }, 100);
        });
    }
});

// Detecta se há rastreador ativo na frota
async function detectActiveVehicle() {
    try {
        const res = await fetch("/api/fleet/vehicles");
        if (!res.ok) return;
        const vehicles = await res.json();
        const labelEl = document.getElementById("aguia-active-vehicle-label");
        if (vehicles && vehicles.length > 0) {
            const activeHw = vehicles[0];
            if (activeHw) {
                currentVehicleId = activeHw.id;
                if (labelEl) {
                    labelEl.innerText = `${activeHw.name || activeHw.id} (${activeHw.plate || activeHw.id})`;
                }
            }
        } else {
            currentVehicleId = null;
            if (labelEl) {
                labelEl.innerText = "Nenhum rastreador conectado";
            }
        }
    } catch (e) {
        console.warn("[AguiaCar] Erro ao listar veículos da frota:", e);
    }
}

// ─── Inicialização do Mapa Leaflet ───────────────────────────────────────────
function initFleetMap() {
    if (fleetMap) {
        fleetMap.invalidateSize();
        return;
    }

    const mapContainer = document.getElementById("aguiacar-map");
    if (!mapContainer) return;

    fleetMap = L.map('aguiacar-map', {
        zoomControl: true,
        attributionControl: false
    }).setView(defaultCoords, 15);

    // ─── Camadas Google Maps & OpenStreetMap ──────────────────────────────────
    // 1. Google Maps Satélite Híbrido (Satélite + Ruas com nomes)
    const googleSatellite = L.tileLayer('https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}', {
        maxZoom: 20,
        subdomains: ['mt0', 'mt1', 'mt2', 'mt3']
    });

    // 2. Google Maps Ruas Padrão (Roadmap)
    const googleStreets = L.tileLayer('https://mt1.google.com/vt/lyrs=m&x={x}&y={y}&z={z}', {
        maxZoom: 20,
        subdomains: ['mt0', 'mt1', 'mt2', 'mt3']
    });

    // 3. OpenStreetMap Padrão (100% Livre e Estável)
    const osmStandard = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19
    });

    // Adiciona Google Satélite como padrão inicial (impacto visual máximo para frotas)
    googleSatellite.addTo(fleetMap);

    // Seletor de Camadas no canto superior direito do mapa
    const baseMaps = {
        "🛰️ Google Satélite": googleSatellite,
        "🗺️ Google Ruas": googleStreets,
        "🌍 OpenStreetMap": osmStandard
    };
    L.control.layers(baseMaps, null, { position: 'topright' }).addTo(fleetMap);

    // Ícone personalizado do veículo com pulso neon
    const carIcon = L.divIcon({
        className: 'custom-car-icon',
        html: '<div style="background: #00f0ff; width: 18px; height: 18px; border-radius: 50%; border: 3px solid #ffffff; box-shadow: 0 0 16px #00f0ff, 0 0 30px #00f0ff;"></div>',
        iconSize: [18, 18],
        iconAnchor: [9, 9]
    });

    const initialLat = defaultCoords[0];
    const initialLon = defaultCoords[1];
    const initialGmapsUrl = `https://www.google.com/maps/dir/?api=1&destination=${initialLat},${initialLon}`;

    const initialPopupHtml = `
        <div style="min-width: 220px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; color: #ffffff; padding: 4px 2px;">
            <div style="font-size: 14px; font-weight: 800; color: #00f0ff; letter-spacing: 0.5px; margin-bottom: 6px; display: flex; align-items: center; justify-content: space-between;">
                <span>🦅 <span id="popup-vehicle-id">${currentVehicleId}</span></span>
                <span style="background: rgba(0, 255, 136, 0.2); color: #00ff88; font-size: 10px; font-weight: 700; padding: 2px 6px; border-radius: 4px; border: 1px solid rgba(0, 255, 136, 0.4);">4G ATIVO</span>
            </div>
            <div style="font-size: 12px; color: #e2e8f0; margin-bottom: 3px;">
                📡 <b>Operadora:</b> Vodafone Espanha (Cat-1)
            </div>
            <div style="font-size: 12px; color: #cbd5e1; margin-bottom: 4px; font-family: monospace;">
                📍 <b>Lat:</b> ${initialLat.toFixed(5)} | <b>Lon:</b> ${initialLon.toFixed(5)}
            </div>
            <div style="font-size: 12px; color: #ffbb33; margin-bottom: 10px;">
                🛰️ <i>Aguardando fix dos satélites GNSS</i>
            </div>
            <a href="${initialGmapsUrl}" target="_blank" rel="noopener noreferrer" 
               style="display: flex; align-items: center; justify-content: center; gap: 6px; width: 100%; background: linear-gradient(135deg, #00f0ff 0%, #0077ff 100%); color: #050b14; font-weight: 800; font-size: 12px; padding: 8px 10px; border-radius: 6px; text-decoration: none; box-shadow: 0 2px 10px rgba(0, 240, 255, 0.4); text-transform: uppercase;">
                🗺️ Como Chegar (Google Maps) ↗
            </a>
        </div>
    `;

    vehicleMarker = L.marker(defaultCoords, { icon: carIcon }).addTo(fleetMap);
    vehicleMarker.bindPopup(initialPopupHtml).openPopup();

    routePolyline = L.polyline([], {
        color: '#00f0ff',
        weight: 5,
        opacity: 0.85,
        smoothFactor: 1
    }).addTo(fleetMap);
}

// ─── Atualização de Telemetria e Posição ──────────────────────────────────────
async function loadFleetData() {
    try {
        const res = await fetch(`/api/fleet/telemetry/${currentVehicleId}?limit=20`);
        if (!res.ok) return;
        const telemetryList = await res.json();
        const simBadge = document.getElementById("aguia-sim-status");
        
        if (telemetryList.length === 0) {
            // NENHUM dado gravado ainda: indica claramente no painel que está em escuta do sinal físico
            if (simBadge) {
                simBadge.className = "status-pill status-warn";
                simBadge.innerText = "🟡 Aguardando 1º Disparo 4G";
            }
            const healthBadge = document.getElementById("aguia-health-badge");
            const healthDesc = document.getElementById("aguia-health-desc");
            if (healthBadge && healthDesc) {
                healthBadge.className = "status-pill status-warn";
                healthBadge.innerText = "⏳ AGUARDANDO DISPARO REAL DO AGUIACAR";
                healthDesc.innerText = "Banco de dados limpo. Aguardando o modem SIM7670G enviar coordenadas via 4G LTE.";
            }
            return;
        }

        if (simBadge) {
            simBadge.className = "status-pill status-ok";
            simBadge.innerText = "🟢 Online (Vodafone 4G)";
        }

        const latest = telemetryList[telemetryList.length - 1];
        updateGauges(latest);

        // Atualiza indicador de satélites e GPS no cabeçalho do mapa
        const gpsStatusEl = document.getElementById("aguia-gps-status-text");
        if (gpsStatusEl) {
            if (latest.lat && latest.lon && (latest.lat !== 0 || latest.lon !== 0)) {
                gpsStatusEl.innerHTML = `📍 GPS Fix: <b>${latest.lat.toFixed(5)}, ${latest.lon.toFixed(5)}</b> • Atualizado em tempo real`;
                gpsStatusEl.style.color = "#00ff88";
            } else {
                gpsStatusEl.innerHTML = `🛰️ <b>Conexão 4G Ativa</b> • Aguardando Fix dos Satélites GNSS (Céu Aberto)`;
                gpsStatusEl.style.color = "#ffbb33";
            }
        }

        // Atualiza rastro no mapa apenas com coordenadas reais válidas (> 0)
        routePoints = telemetryList
            .filter(t => t.lat && t.lon && (Math.abs(t.lat) > 0.001 || Math.abs(t.lon) > 0.001))
            .map(t => [t.lat, t.lon]);

        if (routePoints.length > 0 && routePolyline && fleetMap) {
            routePolyline.setLatLngs(routePoints);
            const latestPoint = routePoints[routePoints.length - 1];
            const lat = latestPoint[0];
            const lon = latestPoint[1];
            const gmapsUrl = `https://www.google.com/maps/dir/?api=1&destination=${lat},${lon}`;

            if (vehicleMarker) {
                vehicleMarker.setLatLng(latestPoint);
                const popupContent = `
                    <div style="min-width: 220px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; color: #ffffff; padding: 4px 2px;">
                        <div style="font-size: 14px; font-weight: 800; color: #00f0ff; letter-spacing: 0.5px; margin-bottom: 6px; display: flex; align-items: center; justify-content: space-between;">
                            <span>🦅 ${currentVehicleId}</span>
                            <span style="background: rgba(0, 255, 136, 0.2); color: #00ff88; font-size: 10px; font-weight: 700; padding: 2px 6px; border-radius: 4px; border: 1px solid rgba(0, 255, 136, 0.4);">4G ATIVO</span>
                        </div>
                        <div style="font-size: 12px; color: #e2e8f0; margin-bottom: 3px;">
                            📡 <b>Operadora:</b> Vodafone Espanha (Cat-1)
                        </div>
                        <div style="font-size: 12px; color: #cbd5e1; margin-bottom: 3px; font-family: monospace;">
                            📍 <b>Lat:</b> ${lat.toFixed(5)} | <b>Lon:</b> ${lon.toFixed(5)}
                        </div>
                        <div style="font-size: 12px; color: #cbd5e1; margin-bottom: 10px;">
                            🏎️ <b>Velocidade:</b> ${Math.round(latest.speed_gps || latest.speed_obd || 0)} km/h
                        </div>
                        <a href="${gmapsUrl}" target="_blank" rel="noopener noreferrer" 
                           style="display: flex; align-items: center; justify-content: center; gap: 6px; width: 100%; background: linear-gradient(135deg, #00f0ff 0%, #0077ff 100%); color: #050b14; font-weight: 800; font-size: 12px; padding: 8px 10px; border-radius: 6px; text-decoration: none; box-shadow: 0 2px 10px rgba(0, 240, 255, 0.4); text-transform: uppercase; transition: transform 0.2s;">
                            🗺️ Como Chegar (Google Maps) ↗
                        </a>
                    </div>
                `;
                vehicleMarker.bindPopup(popupContent);
            }
            fleetMap.panTo(latestPoint, { animate: true, duration: 1.0 });
        } else if (routePolyline) {
            routePolyline.setLatLngs([]);
        }
    } catch (e) {
        console.warn("[AguiaCar] Erro ao carregar telemetria:", e);
    }
}

let geofenceCircle = null;

function updateGeofenceOnMap(lat, lon, radiusKm, enabled) {
    if (!fleetMap) return;
    if (geofenceCircle) {
        fleetMap.removeLayer(geofenceCircle);
        geofenceCircle = null;
    }
    if (enabled && lat && lon && radiusKm > 0) {
        geofenceCircle = L.circle([lat, lon], {
            radius: radiusKm * 1000,
            color: '#a855f7',
            weight: 2,
            opacity: 0.85,
            fillColor: '#a855f7',
            fillOpacity: 0.12,
            dashArray: '6, 6'
        }).addTo(fleetMap);
        geofenceCircle.bindPopup(`<b>🟣 Cerca Virtual Ativa</b><br>Raio de Cobertura: ${radiusKm} km`);
    }
}

function updateGauges(data) {
    // RPM
    const rpmEl = document.getElementById("aguia-gauge-rpm");
    if (rpmEl) rpmEl.innerText = Math.round(data.rpm || 0);

    // Velocidade
    const speedEl = document.getElementById("aguia-gauge-speed");
    if (speedEl) speedEl.innerText = Math.round(data.speed_obd || data.speed_gps || 0);

    // Temperatura do Motor
    const tempEl = document.getElementById("aguia-gauge-temp");
    if (tempEl) {
        const temp = Math.round(data.engine_temp || 0);
        tempEl.innerText = `${temp}°C`;
        tempEl.style.color = temp > 105 ? "#ff4444" : (temp < 60 ? "#ffbb33" : "#00ff88");
    }

    // Nível de Combustível
    const fuelEl = document.getElementById("aguia-gauge-fuel");
    if (fuelEl) fuelEl.innerText = `${(data.fuel_pct || 0).toFixed(1)}%`;

    // Bateria OBD (12V)
    const battEl = document.getElementById("aguia-gauge-batt");
    if (battEl) battEl.innerText = `${(data.battery_v || 12.6).toFixed(1)}V`;

    // Força G (Aceleração Longitudinal / Impacto)
    const accelEl = document.getElementById("aguia-gauge-accel");
    if (accelEl) {
        const gVal = (data.accel_g !== undefined && data.accel_g !== null) ? Number(data.accel_g).toFixed(2) : "0.00";
        accelEl.innerText = `${gVal} G`;
        if (Math.abs(Number(gVal)) >= 2.5) {
            accelEl.style.color = "#ff4444";
        } else if (Number(gVal) <= -0.50 || Number(gVal) >= 0.35) {
            accelEl.style.color = "#ffbb33";
        } else {
            accelEl.style.color = "var(--accent-cyan)";
        }
    }

    // Evento de Condução Recente
    const eventEl = document.getElementById("aguia-driving-event-badge");
    if (eventEl) {
        const ev = data.driving_event || "";
        if (ev === "CRASH") {
            eventEl.className = "status-pill status-danger pulse-critico";
            eventEl.innerText = "💥 COLISÃO / IMPACTO SEVERO";
        } else if (ev === "HARSH_BRAKE") {
            eventEl.className = "status-pill status-warn";
            eventEl.innerText = "⚠️ FRENAGEM BRUSCA (-G)";
        } else if (ev === "HARSH_ACCEL") {
            eventEl.className = "status-pill status-warn";
            eventEl.innerText = "⚡ ACELERAÇÃO BRUSCA (+G)";
        } else {
            eventEl.className = "status-pill status-ok";
            eventEl.innerText = "🟢 Condução Suave (Eco-Drive)";
        }
    }

    // Banner de Saúde do Guardião Mecânico
    const healthBadge = document.getElementById("aguia-health-badge");
    const healthDesc = document.getElementById("aguia-health-desc");
    const alertLevel = data.alert_level || "NORMAL";

    if (healthBadge && healthDesc) {
        if (alertLevel === "CRITICO_PARADA") {
            healthBadge.className = "status-pill status-danger pulse-critico";
            healthBadge.innerText = "🔴 PARADA IMEDIATA / STOP VEHICLE";
            healthDesc.innerText = "Risco iminente de fundir o motor ou colisão severa! Notificação enviada para central.";
        } else if (alertLevel === "PREVENTIVA") {
            healthBadge.className = "status-pill status-warn";
            healthBadge.innerText = "🟡 MANUTENÇÃO PREVENTIVA";
            healthDesc.innerText = "Anomalia mecânica ou evento agressivo de condução registrado.";
        } else {
            healthBadge.className = "status-pill status-ok";
            healthBadge.innerText = "🟢 MOTOR SAUDÁVEL / OPERACIONAL";
            healthDesc.innerText = "Todos os sistemas operando nos parâmetros nominais da fábrica.";
        }
    }

    // Atualiza Score e Geofence Status do Veículo
    fetch("/api/fleet/vehicles").then(r => r.json()).then(vehicles => {
        if (!vehicles) return;
        const v = vehicles.find(x => x.id === currentVehicleId) || vehicles[0];
        if (v) {
            const scoreEl = document.getElementById("aguia-score-val");
            const scorePill = document.getElementById("aguia-score-pill");
            if (scoreEl) {
                const score = v.driving_score !== undefined && v.driving_score !== null ? v.driving_score : 100;
                scoreEl.innerText = score;
                if (scorePill) {
                    if (score >= 90) {
                        scorePill.style.borderColor = "var(--accent-green)";
                        scoreEl.style.color = "var(--accent-green)";
                    } else if (score >= 70) {
                        scorePill.style.borderColor = "#ffbb33";
                        scoreEl.style.color = "#ffbb33";
                    } else {
                        scorePill.style.borderColor = "var(--accent-red)";
                        scoreEl.style.color = "var(--accent-red)";
                    }
                }
            }

            const geoStatusEl = document.getElementById("aguia-geofence-status");
            if (geoStatusEl) {
                const gStatus = v.geofence_status || "INSIDE";
                if (gStatus === "OUTSIDE") {
                    geoStatusEl.className = "status-pill status-danger pulse-critico";
                    geoStatusEl.innerText = "🚨 FORA DA CERCA VIRTUAL";
                } else {
                    geoStatusEl.className = "status-pill status-ok";
                    geoStatusEl.innerText = "🟣 DENTRO DO PERÍMETRO";
                }
            }
        }
    }).catch(err => console.warn("[AguiaCar] Erro ao sincronizar veículo:", err));
}

// ─── Configurações Remotas OTA ──────────────────────────────────────────────
async function loadFleetConfig() {
    try {
        const res = await fetch(`/api/fleet/config/${currentVehicleId}`);
        if (!res.ok) return;
        const cfg = await res.json();

        const gpsRange = document.getElementById("cfg-gps-interval");
        if (gpsRange) {
            gpsRange.value = cfg.gps_interval_sec || 5;
            const valSpan = document.getElementById("cfg-gps-interval-val");
            if (valSpan) valSpan.innerText = `${cfg.gps_interval_sec || 5}s`;
        }

        const dtcSel = document.getElementById("cfg-dtc-interval");
        if (dtcSel) dtcSel.value = cfg.dtc_scan_interval_min || 30;

        const emailInp = document.getElementById("cfg-email");
        if (emailInp) emailInp.value = cfg.alert_email || "reileonardofechio@gmail.com";

        const tempInp = document.getElementById("cfg-max-temp");
        if (tempInp) tempInp.value = cfg.max_engine_temp || 105;

        const rpmInp = document.getElementById("cfg-max-rpm");
        if (rpmInp) rpmInp.value = cfg.max_rpm || 5500;

        // Cerca Virtual
        const geoCheck = document.getElementById("cfg-geofence-enabled");
        if (geoCheck) geoCheck.checked = !!cfg.geofence_enabled;

        const geoRadius = document.getElementById("cfg-geofence-radius");
        if (geoRadius) {
            geoRadius.value = cfg.geofence_radius_km || 15;
            const geoRadVal = document.getElementById("cfg-geofence-radius-val");
            if (geoRadVal) geoRadVal.innerText = `${cfg.geofence_radius_km || 15} km`;
        }

        const geoLat = cfg.geofence_lat || defaultCoords[0];
        const geoLon = cfg.geofence_lon || defaultCoords[1];
        const geoLatInp = document.getElementById("cfg-geofence-lat");
        const geoLonInp = document.getElementById("cfg-geofence-lon");
        if (geoLatInp) geoLatInp.value = geoLat;
        if (geoLonInp) geoLonInp.value = geoLon;

        // Renderiza no mapa a Cerca Virtual
        updateGeofenceOnMap(geoLat, geoLon, cfg.geofence_radius_km || 15, cfg.geofence_enabled !== 0);
    } catch (e) {
        console.error("Erro ao carregar configurações remotas:", e);
    }
}

async function saveFleetConfig() {
    const geoCheck = document.getElementById("cfg-geofence-enabled");
    const geoRadius = document.getElementById("cfg-geofence-radius");
    const geoLat = document.getElementById("cfg-geofence-lat");
    const geoLon = document.getElementById("cfg-geofence-lon");

    const payload = {
        gps_interval_sec: parseInt(document.getElementById("cfg-gps-interval").value, 10),
        gps_standby_interval_sec: 60,
        dtc_scan_interval_min: parseInt(document.getElementById("cfg-dtc-interval").value, 10),
        alert_email: document.getElementById("cfg-email").value.trim(),
        max_engine_temp: parseFloat(document.getElementById("cfg-max-temp").value),
        max_rpm: parseFloat(document.getElementById("cfg-max-rpm").value),
        max_speed: 130.0,
        notify_disconnect: 1,
        geofence_enabled: geoCheck ? (geoCheck.checked ? 1 : 0) : 1,
        geofence_lat: geoLat ? parseFloat(geoLat.value) : defaultCoords[0],
        geofence_lon: geoLon ? parseFloat(geoLon.value) : defaultCoords[1],
        geofence_radius_km: geoRadius ? parseFloat(geoRadius.value) : 15.0
    };

    try {
        const res = await fetch(`/api/fleet/config/${currentVehicleId}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (data.status === "success") {
            // Atualiza círculo no mapa
            updateGeofenceOnMap(payload.geofence_lat, payload.geofence_lon, payload.geofence_radius_km, payload.geofence_enabled === 1);
            alert("✅ Configurações salvas e Cerca Virtual sincronizada com o rastreador AguiaCar!");
        }
    } catch (e) {
        alert("Erro ao salvar configurações remotas: " + e.message);
    }
}

// ─── Alertas & Ordens de Serviço ────────────────────────────────────────────
async function loadFleetAlerts() {
    try {
        const res = await fetch("/api/fleet/alerts");
        if (!res.ok) return;
        const alerts = await res.json();
        const tbody = document.getElementById("aguia-alerts-tbody");
        if (!tbody) return;

        if (alerts.length === 0) {
            tbody.innerHTML = `<tr><td colspan="5" style="text-align: center; color: var(--text-secondary); padding: 15px;">Nenhum alerta pendente. Frota operando normalmente.</td></tr>`;
            return;
        }

        tbody.innerHTML = alerts.map(a => {
            const dateStr = new Date(a.timestamp).toLocaleString("pt-BR", { timeZone: "Europe/Madrid" });
            const badgeClass = a.severity === "CRITICO_PARADA" ? "status-danger" : (a.severity === "PREVENTIVA" ? "status-warn" : "status-ok");
            return `
                <tr>
                    <td><span class="status-pill ${badgeClass}">${a.severity}</span></td>
                    <td style="font-weight: 500;">${a.title}</td>
                    <td style="color: var(--text-secondary); font-size: 13px;">${a.message}</td>
                    <td style="font-size: 12px;">${dateStr}</td>
                    <td>
                        ${a.status === 'OPEN' ? 
                            `<button class="btn btn-secondary" onclick="resolveFleetAlert(${a.id})" style="padding: 4px 8px; font-size: 12px;">Concluir OS</button>` : 
                            `<span style="color: var(--accent-green); font-size: 12px;">✓ Atendida</span>`
                        }
                    </td>
                </tr>
            `;
        }).join("");
    } catch (e) {
        console.error("Erro ao carregar alertas:", e);
    }
}

async function resolveFleetAlert(alertId) {
    await fetch(`/api/fleet/alerts/${alertId}/resolve`, { method: "POST" });
    loadFleetAlerts();
    loadFleetData();
}

// ─── Simulador de Demonstração Comercial ────────────────────────────────────
async function simulateFleetScenario(scenario) {
    try {
        const res = await fetch(`/api/fleet/simulate?scenario=${scenario}`, { method: "POST" });
        const data = await res.json();
        loadFleetData();
        loadFleetAlerts();
    } catch (e) {
        console.error("Erro na simulação:", e);
    }
}

// Atualização periódica a cada 4 segundos
setInterval(() => {
    const tabAguia = document.getElementById("panel-aguiacar");
    if (tabAguia && tabAguia.classList.contains("active")) {
        loadFleetData();
    }
}, 4000);
