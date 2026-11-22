import re

path = "/home/leonardof/AgentCarDiag/server/app/static/app.js"
with open(path, "r") as f:
    code = f.read()

old_ai = """      // Simular chamada ao LLM (mock)
      const verdictText = document.getElementById('ai-verdict-text');
      if (locAnal.inconsistencies_count > 0) {
        verdictText.textContent = "Gerando parecer técnico com IA via prompt compactado...\\n\\n" + JSON.stringify(aiPrompt, null, 2);
        
        // Simular o delay de rede da OpenAI / Claude
        setTimeout(() => {
          verdictText.innerHTML = `
<strong style="color:#00ff66;">Causa Raiz Mais Provável:</strong>
Com base na defasagem de ${Math.abs(payload.scope_telemetry.tooth_offset)} dente(s) no sinal CKP/CMP, indica-se falha mecânica de sincronismo na correia dentada (pulo de dente) ou tensionador frouxo, descartando falha eletrônica pura.

<strong style="color:#38bdf8;">Testes Físicos Sugeridos:</strong>
1. Travar o virabrequim no PMS mecânico e checar a marcação de ponto nos comandos.
2. Medir tensão da correia no tensionador automático.

<strong style="color:#f59e0b;">Ação de Reparo Recomendada:</strong>
Substituir o kit de correia dentada e tensionadores, e refazer o sincronismo usando ferramentas de fasagem padrão do modelo. Limpar falhas de DTC (P0016).
          `;
        }, 1500);
      } else {
        verdictText.textContent = "Nenhuma falha primária reportada para gerar parecer de reparo.";
      }"""

new_ai = """      // Utilizar resposta real da IA do Backend
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
      }"""

code = code.replace(old_ai, new_ai)

with open(path, "w") as f:
    f.write(code)

print("AI UI patched!")
