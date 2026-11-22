import re

path = "/home/leonardof/AgentCarDiag/server/app/static/app.js"
with open(path, "r") as f:
    code = f.read()

# 1. Add ruler to oscState
old_state = """  trigEdge: 'Rise',
  trigLevel: 2.5,
  syncTeethOffset: 0, // Dentes de defasagem

  gridCtx: null,"""
new_state = """  trigEdge: 'Rise',
  trigLevel: 2.5,
  syncTeethOffset: 0, // Dentes de defasagem
  
  ruler: { active: false, startX: 0, endX: 0, dragging: false, mode: 0 }, // mode 0 = setting start, 1 = setting end

  gridCtx: null,"""
code = code.replace(old_state, new_state)

# 2. Add mouse events to trace layer
old_init = """  // Listener de redimensionamento
  const ro = new ResizeObserver(() => {
    resizeOscilloscope();
    drawGrid();
  });"""
new_init = """  // Eventos de Mouse para Régua
  const tCanvas = document.getElementById('osc-trace-layer');
  tCanvas.addEventListener('mousedown', (e) => {
      if(!oscState.ruler.active) return;
      const rect = tCanvas.getBoundingClientRect();
      const x = e.clientX - rect.left;
      oscState.ruler.dragging = true;
      oscState.ruler.startX = x;
      oscState.ruler.endX = x;
  });
  tCanvas.addEventListener('mousemove', (e) => {
      if(!oscState.ruler.active || !oscState.ruler.dragging) return;
      const rect = tCanvas.getBoundingClientRect();
      oscState.ruler.endX = e.clientX - rect.left;
      if(!oscState.running) drawOscilloscope(); // Redesenha se estiver parado
  });
  tCanvas.addEventListener('mouseup', (e) => {
      if(oscState.ruler.active) oscState.ruler.dragging = false;
  });

  // Listener de redimensionamento
  const ro = new ResizeObserver(() => {
    resizeOscilloscope();
    drawGrid();
  });"""
code = code.replace(old_init, new_init)

# 3. Add toggleRuler function
old_toggle = """function toggleOscRun() {
  oscState.running = !oscState.running;
  document.getElementById('btn-run').textContent = oscState.running ? '⏸ Parar (Hold)' : '▶ Rodar';
  document.getElementById('btn-run').className = oscState.running ? 'btn btn-primary' : 'btn btn-outline';
}"""
new_toggle = """function toggleOscRun() {
  oscState.running = !oscState.running;
  document.getElementById('btn-run').textContent = oscState.running ? '⏸ Parar (Hold)' : '▶ Rodar';
  document.getElementById('btn-run').className = oscState.running ? 'btn btn-primary' : 'btn btn-outline';
}

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
}"""
code = code.replace(old_toggle, new_toggle)

# 4. Modify processOscilloscopeData for Single Trigger
old_proc = """    let triggered = false;
    let trigIdx = 0;
    
    // Busca do ponto de Trigger
    if (oscState.trigMode !== 'Auto') {
      const edge = oscState.trigEdge === 'Rise' ? 1 : -1;
      const tLvl = oscState.trigLevel;
      // Procura borda
      for (let i = 1; i < len; i++) {
        if (edge > 0 && buf[i-1] < tLvl && buf[i] >= tLvl) {
          triggered = true;
          trigIdx = i;
          break;
        } else if (edge < 0 && buf[i-1] > tLvl && buf[i] <= tLvl) {
          triggered = true;
          trigIdx = i;
          break;
        }
      }
      
      // Se não achou trigger e modo Normal, descarta pacote
      if (!triggered && oscState.trigMode === 'Normal') return;
    }"""
new_proc = """    let triggered = false;
    let trigIdx = 0;
    
    // Busca do ponto de Trigger
    if (oscState.trigMode !== 'Auto') {
      const edge = oscState.trigEdge === 'Rise' ? 1 : -1;
      const tLvl = oscState.trigLevel;
      // Procura borda
      for (let i = 1; i < len; i++) {
        if (edge > 0 && buf[i-1] < tLvl && buf[i] >= tLvl) {
          triggered = true;
          trigIdx = i;
          break;
        } else if (edge < 0 && buf[i-1] > tLvl && buf[i] <= tLvl) {
          triggered = true;
          trigIdx = i;
          break;
        }
      }
      
      // Se não achou trigger e modo Normal/Single, descarta pacote
      if (!triggered && (oscState.trigMode === 'Normal' || oscState.trigMode === 'Single')) return;
      
      // Se Single e trigou, congela no próximo frame
      if (triggered && oscState.trigMode === 'Single') {
          setTimeout(toggleOscRun, 50); // Para o gráfico logo após desenhar este frame
      }
    }"""
code = code.replace(old_proc, new_proc)

# 5. Modify drawOscilloscope for Ruler drawing and Tooth Counting
old_draw = """  ctx.stroke();
  
  if (oscState.ch2 && oscState.buffer2.length > 0) {
    ctx.beginPath();
    ctx.strokeStyle = '#00f0ff'; // Ciano
    for (let i = 0; i < renderLen; i++) {
      let x = i * pixelStep;
      let y = ch2_zero_y - (oscState.buffer2[i] / oscState.vDiv2) * pixelsPerVoltDiv;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.stroke();
  }
}"""
new_draw = """  ctx.stroke();
  
  if (oscState.ch2 && oscState.buffer2.length > 0) {
    ctx.beginPath();
    ctx.strokeStyle = '#00f0ff'; // Ciano
    for (let i = 0; i < renderLen; i++) {
      let x = i * pixelStep;
      let y = ch2_zero_y - (oscState.buffer2[i] / oscState.vDiv2) * pixelsPerVoltDiv;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.stroke();
  }
  
  // Desenhar Régua de 720 Graus e Contar Dentes
  if (oscState.ruler.active) {
      let sx = Math.min(oscState.ruler.startX, oscState.ruler.endX);
      let ex = Math.max(oscState.ruler.startX, oscState.ruler.endX);
      
      if (ex - sx > 10) {
          // Box translúcido
          ctx.fillStyle = 'rgba(0, 255, 255, 0.1)';
          ctx.fillRect(sx, 0, ex - sx, h);
          
          // Desenhar marcações
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
              ctx.lineTo(lineX, h);
              ctx.stroke();
              ctx.setLineDash([]);
              
              ctx.fillText(`${deg}°`, lineX, h - 5);
          });
          
          // Lógica de Contagem de Dentes (Crossings de CH1)
          let startIndex = Math.floor(sx / pixelStep);
          let endIndex = Math.floor(ex / pixelStep);
          
          if(startIndex < 0) startIndex = 0;
          if(endIndex > oscState.buffer.length - 1) endIndex = oscState.buffer.length - 1;
          
          let dentes = 0;
          let threshold = (oscState.vMax + oscState.vMin) / 2; // Threshold médio da onda
          if(isNaN(threshold)) threshold = 1.0;
          
          for(let i = startIndex + 1; i <= endIndex; i++) {
              let prev = oscState.buffer[i-1];
              let curr = oscState.buffer[i];
              // Subida cruzando o limiar
              if(prev < threshold && curr >= threshold) {
                  dentes++;
              }
          }
          
          const stats = document.getElementById('ruler-stats');
          if(stats) {
              stats.textContent = `Dentes (CH1): ${dentes}`;
          }
      }
  }
}"""
code = code.replace(old_draw, new_draw)

with open(path, "w") as f:
    f.write(code)

print("app.js patched for Oscilloscope features!")
