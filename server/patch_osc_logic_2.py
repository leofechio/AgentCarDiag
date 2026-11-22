import re

path = "/home/leonardof/AgentCarDiag/server/app/static/app.js"
with open(path, "r") as f:
    code = f.read()

# 1. Update handleAdcBurst for Trigger Logic
old_burst = """function handleAdcBurst(msg) {
  if (state.scopeSource !== 'hw_stream' || !oscState.running) return;
  
  if (msg.ch1 && oscState.ch1) {
    const len1 = Math.min(msg.ch1.length, oscState.buffer1.length);
    oscState.buffer1.set(msg.ch1.slice(0, len1));
    oscState.bufferIdx = len1;
  }
  
  if (msg.ch2 && oscState.ch2) {
    const len2 = Math.min(msg.ch2.length, oscState.buffer2.length);
    oscState.buffer2.set(msg.ch2.slice(0, len2));
    if (!msg.ch1 || !oscState.ch1) {
      oscState.bufferIdx = len2;
    }
  }
  
  if (msg.sample_rate) {
    oscState.sampleRate = msg.sample_rate;
  }
}"""

new_burst = """function handleAdcBurst(msg) {
  if (state.scopeSource !== 'hw_stream' || !oscState.running) return;
  
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
  
  if (msg.ch1 && oscState.ch1) {
    const len1 = Math.min(msg.ch1.length, oscState.buffer1.length);
    oscState.buffer1.set(msg.ch1.slice(0, len1));
    oscState.bufferIdx = len1;
  }
  
  if (msg.ch2 && oscState.ch2) {
    const len2 = Math.min(msg.ch2.length, oscState.buffer2.length);
    oscState.buffer2.set(msg.ch2.slice(0, len2));
    if (!msg.ch1 || !oscState.ch1) {
      oscState.bufferIdx = len2;
    }
  }
  
  if (msg.sample_rate) {
    oscState.sampleRate = msg.sample_rate;
  }
}"""
code = code.replace(old_burst, new_burst)

# 2. Update simulateOscSignal Trigger Logic
old_sim = """  // Basic Trigger
  if (oscState.trigMode !== 'Auto') {
    const edge = oscState.trigEdge === 'Rise' ? 1 : -1;
    const tLvl = oscState.trigLevel;
    let trigged = false;
    for (let i = 1; i < pts; i++) {
      if (edge > 0 && b1[i-1] < tLvl && b1[i] >= tLvl) { trigged = true; break; }
      if (edge < 0 && b1[i-1] > tLvl && b1[i] <= tLvl) { trigged = true; break; }
    }
    if (!trigged && oscState.trigMode === 'Normal') return;
  }"""
new_sim = """  // Basic Trigger
  if (oscState.trigMode !== 'Auto') {
    const edge = oscState.trigEdge === 'Rise' ? 1 : -1;
    const tLvl = oscState.trigLevel;
    let trigged = false;
    for (let i = 1; i < pts; i++) {
      if (edge > 0 && b1[i-1] < tLvl && b1[i] >= tLvl) { trigged = true; break; }
      if (edge < 0 && b1[i-1] > tLvl && b1[i] <= tLvl) { trigged = true; break; }
    }
    if (!trigged && (oscState.trigMode === 'Normal' || oscState.trigMode === 'Single')) return;
    
    if (trigged && oscState.trigMode === 'Single') {
        setTimeout(toggleOscRun, 50);
    }
  }"""
code = code.replace(old_sim, new_sim)


# 3. Add Ruler overlay to oscRenderLoop (right before updateOscBadgeStats)
old_loop_end = """  if (oscState.ch2 && oscState.bufferIdx > 0) {
    drawTrace(ctx, oscState.buffer2, oscState.bufferIdx, '#00f0ff', W, H, oscState.vDiv2, oscState.offset2);
  }
  
  updateOscBadgeStats();"""

new_loop_end = """  if (oscState.ch2 && oscState.bufferIdx > 0) {
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
          
          // Contagem de Dentes CH1 (Zero Crossing em relação à média)
          let maxPts = Math.min(oscState.bufferIdx, Math.floor(W));
          let startIdx = Math.floor((sx / W) * maxPts);
          let endIdx = Math.floor((ex / W) * maxPts);
          
          if(startIdx < 0) startIdx = 0;
          if(endIdx > maxPts - 1) endIdx = maxPts - 1;
          
          let dentes = 0;
          let threshold = 2.0; // aprox mid point
          
          for(let i = startIdx + 1; i <= endIdx; i++) {
              let prev = oscState.buffer1[i-1];
              let curr = oscState.buffer1[i];
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
  
  updateOscBadgeStats();"""
code = code.replace(old_loop_end, new_loop_end)

with open(path, "w") as f:
    f.write(code)

print("app.js logic patched!")
