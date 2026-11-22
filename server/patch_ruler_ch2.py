import re

path = "/home/leonardof/AgentCarDiag/server/app/static/app.js"
with open(path, "r") as f:
    code = f.read()

old_count = """          // Contagem de Dentes CH1 (Zero Crossing em relação à média)
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
          }"""

new_count = """          // Contagem de Dentes (Sinal CKP - Geralmente no CH2 ou CH1 dependendo da amplitude/frequência)
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
          }"""

code = code.replace(old_count, new_count)

with open(path, "w") as f:
    f.write(code)

print("app.js logic patched to count teeth on CH2 with dynamic threshold!")
