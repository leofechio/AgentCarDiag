import re

path_js = "/home/leonardof/AgentCarDiag/server/app/static/telemetry.js"
with open(path_js, "r") as f:
    code = f.read()
    
old_func = """    const updateCard = (id, data) => {
      const badge = document.getElementById(`status-${id}`);
      const ping = document.getElementById(`ping-${id}`);
      if (!badge || !ping) return;
      
      if (data && data.connected) {
        badge.className = 'badge-status online';
        badge.textContent = '● Online';
        badge.style.background = 'rgba(16, 185, 129, 0.2)';
        badge.style.color = '#10b981';
        ping.textContent = Math.round(data.ping_ms);
      } else {
        badge.className = 'badge-status offline';
        badge.textContent = '● Offline';
        badge.style.background = 'rgba(239, 68, 68, 0.2)';
        badge.style.color = '#ef4444';
        ping.textContent = '--';
      }
    };"""

new_func = """    const updateCard = (id, data) => {
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
    };"""

code = code.replace(old_func, new_func)
with open(path_js, "w") as f:
    f.write(code)

path_html = "/home/leonardof/AgentCarDiag/server/app/static/index.html"
with open(path_html, "r") as f:
    html = f.read()

html = html.replace("telemetry.js?v=3", "telemetry.js?v=4")

with open(path_html, "w") as f:
    f.write(html)

print("Ping colors patched successfully!")
