with open('/home/leonardof/AgentCarDiag/server/app/static/app.js', 'r') as f:
    content = f.read()

start_idx = content.find('// ─── CAN DRAWER LOGIC ────────────────────────────────────────────────')

if start_idx != -1:
    old_logic = content[start_idx:]
    
    new_logic = """// ─── CAN DRAWER LOGIC ────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  const canTableBody = document.querySelector('#can-tbody');
  const drawer = document.getElementById('can-inspector-drawer');

  if (canTableBody) {
    canTableBody.addEventListener('click', (e) => {
      const tr = e.target.closest('tr');
      if (!tr) return;

      // Remove seleção anterior e destaca a atual
      canTableBody.querySelectorAll('tr.selected-can-row').forEach(r => r.classList.remove('selected-can-row'));
      tr.classList.add('selected-can-row');

      // Extrai os dados gravados nos data-attributes da linha
      const frameData = {
        timestamp: tr.dataset.timestamp || '--',
        id: tr.dataset.canId || tr.querySelector('.td-id')?.textContent.trim(),
        dlc: tr.dataset.dlc || '8',
        data: tr.dataset.payload || tr.querySelector('.td-data')?.textContent.trim(),
        origin: tr.dataset.origin || tr.querySelector('.td-source')?.textContent.trim()
      };

      renderDrawer(frameData);
      if (drawer) drawer.classList.remove('hidden');
    });
  }

  // Fechamento no botão e pela tecla ESC
  const btnCloseDrawer = document.getElementById('btn-close-drawer');
  if (btnCloseDrawer) {
    btnCloseDrawer.addEventListener('click', () => {
      if (drawer) drawer.classList.add('hidden');
      if (canTableBody) canTableBody.querySelectorAll('tr.selected-can-row').forEach(r => r.classList.remove('selected-can-row'));
    });
  }

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && drawer && !drawer.classList.contains('hidden')) {
      drawer.classList.add('hidden');
      if (canTableBody) canTableBody.querySelectorAll('tr.selected-can-row').forEach(r => r.classList.remove('selected-can-row'));
    }
  });
});

function renderDrawer(msg) {
  const elId = document.getElementById('drawer-can-id');
  if (elId) elId.textContent = msg.id;
  
  const elMsg = document.getElementById('drawer-msg-name');
  if (elMsg) elMsg.textContent = msg.origin !== 'RAW' ? msg.origin : 'Detalhes do Pacote CAN';
  
  const elTs = document.getElementById('drawer-timestamp');
  if (elTs) elTs.textContent = msg.timestamp;
  
  const elDlc = document.getElementById('drawer-dlc');
  if (elDlc) elDlc.textContent = msg.dlc + ' bytes';
  
  const elBus = document.getElementById('drawer-bus');
  if (elBus) elBus.textContent = 'HS-CAN (500 kbps)';
  
  const elOrigin = document.getElementById('drawer-origin');
  if (elOrigin) elOrigin.textContent = msg.origin;

  const elRaw = document.getElementById('drawer-raw-hex');
  if (elRaw) elRaw.textContent = msg.data;

  // Convert hex to bytes
  const hexParts = msg.data.split(' ');
  const bytes = hexParts.filter(p => p !== '–' && p !== '').map(p => parseInt(p, 16));
  
  let asciiStr = '';
  const matrixContainer = document.getElementById('drawer-byte-matrix');
  if (matrixContainer) {
    matrixContainer.innerHTML = '';
    
    bytes.forEach((b, i) => {
      // ASCII
      if (b >= 32 && b <= 126) {
        asciiStr += String.fromCharCode(b);
      } else {
        asciiStr += '.';
      }
      
      // Matrix Row
      const bits = b.toString(2).padStart(8, '0');
      const row = document.createElement('div');
      row.className = 'byte-row';
      
      let bitCells = '';
      for(let bitIdx = 0; bitIdx < 8; bitIdx++) {
          const bit = bits[bitIdx];
          bitCells += `<span class="bit-cell ${bit === '1' ? 'b1' : 'b0'}">${bit}</span>`;
      }
      
      row.innerHTML = `<span class="byte-label">B${i}</span> <span class="byte-hex">${b.toString(16).padStart(2,'0').toUpperCase()}</span> <div class="bit-group">${bitCells}</div>`;
      matrixContainer.appendChild(row);
    });
  }
  
  const elAscii = document.getElementById('drawer-raw-ascii');
  if (elAscii) elAscii.textContent = asciiStr || '--';
  
  // Decoded signals logic
  const signalsContainer = document.getElementById('drawer-signals-list');
  if (signalsContainer) {
    signalsContainer.innerHTML = '';
    
    if (msg.id === '0X7E8' || msg.id === '7E8') {
      if (bytes.length >= 3 && bytes[1] === 0x41) {
        const pid = bytes[2];
        const sigItem = document.createElement('div');
        sigItem.className = 'signal-item';
        if (pid === 0x0C && bytes.length >= 5) {
          const rpm = ((bytes[3] * 256) + bytes[4]) / 4;
          sigItem.innerHTML = `<span class="signal-name">Rotação do Motor (RPM)</span><span class="signal-value">${rpm} RPM</span>`;
        } else if (pid === 0x0D && bytes.length >= 4) {
          sigItem.innerHTML = `<span class="signal-name">Velocidade (Vehicle Speed)</span><span class="signal-value">${bytes[3]} km/h</span>`;
        } else if (pid === 0x05 && bytes.length >= 4) {
          sigItem.innerHTML = `<span class="signal-name">Temperatura do Motor (ECT)</span><span class="signal-value">${bytes[3] - 40} °C</span>`;
        } else {
          sigItem.innerHTML = `<span class="signal-name">Resposta OBD-II PID 0x${pid.toString(16).padStart(2,'0').toUpperCase()}</span><span class="signal-value">${msg.data}</span>`;
        }
        signalsContainer.appendChild(sigItem);
      }
    } else {
      signalsContainer.innerHTML = '<div style="color:#64748b;font-size:11px;">Sem dicionário de decodificação DBC para este ID.</div>';
    }
  }
}
"""
    
    new_content = content[:start_idx] + new_logic
    
    with open('/home/leonardof/AgentCarDiag/server/app/static/app.js', 'w') as f:
        f.write(new_content)
    print("app.js logic fixed.")
else:
    print("Could not find logic to replace")
