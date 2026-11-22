import re

with open('/home/leonardof/AgentCarDiag/server/app/static/app.js', 'r') as f:
    content = f.read()

# Substituir o final do arquivo (onde adicionei a versão anterior do drawer)
start_old = '// ─── CAN DRAWER LOGIC ────────────────────────────────────────────────'
start_idx = content.find(start_old)
if start_idx != -1:
    content = content[:start_idx]

# Replace inline onclicks and add dataset attributes
def repl_append(m):
    return """  const sourceLabel = meta ? meta.label : 'RAW';
  const tr = document.createElement('tr');
  tr.className = 'new-row';
  tr.style.cursor = 'pointer';
  if (!shouldDisplayFrame(idHex)) {
    tr.classList.add('d-none');
  }
  tr.dataset.timestamp = ts;
  tr.dataset.canId = idHex.toUpperCase();
  tr.dataset.dlc = frame.dlc ?? '–';
  tr.dataset.payload = dataHex;
  tr.dataset.origin = sourceLabel;
  """

content = re.sub(r"  const sourceLabel = meta \? meta\.label : 'RAW';\s*const tr = document\.createElement\('tr'\);\s*tr\.className = 'new-row';\s*tr\.style\.cursor = 'pointer';\s*if \(!shouldDisplayFrame\(idHex\)\) \{\s*tr\.classList\.add\('d-none'\);\s*\}\s*tr\.onclick = \(\) => openCanDrawer\(\{[^\}]*\}\);\s*", repl_append, content)

def repl_append_hist(m):
    return """  const tr = document.createElement('tr');
  tr.style.cursor = 'pointer';
  if (!shouldDisplayFrame(idHex)) {
    tr.classList.add('d-none');
  }
  tr.dataset.timestamp = ts;
  tr.dataset.canId = idHex.toUpperCase();
  tr.dataset.dlc = row.dlc ?? '–';
  tr.dataset.payload = row.data_hex || '–';
  tr.dataset.origin = sourceLabel;
  """

content = re.sub(r"  const tr = document\.createElement\('tr'\);\s*tr\.style\.cursor = 'pointer';\s*if \(!shouldDisplayFrame\(idHex\)\) \{\s*tr\.classList\.add\('d-none'\);\s*\}\s*tr\.onclick = \(\) => openCanDrawer\(\{[^\}]*\}\);\s*", repl_append_hist, content)


drawer_js = """
// ─── CAN DRAWER LOGIC ────────────────────────────────────────────────
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

function renderDrawer(msg) {
  document.getElementById('drawer-can-id').textContent = msg.id;
  document.getElementById('drawer-msg-name').textContent = msg.origin !== 'RAW' ? msg.origin : 'Detalhes do Pacote CAN';
  document.getElementById('drawer-timestamp').textContent = msg.timestamp;
  document.getElementById('drawer-dlc').textContent = msg.dlc + ' bytes';
  document.getElementById('drawer-bus').textContent = 'HS-CAN (500 kbps)';
  document.getElementById('drawer-origin').textContent = msg.origin;

  document.getElementById('drawer-raw-hex').textContent = msg.data;

  // Convert hex to bytes
  const hexParts = msg.data.split(' ');
  const bytes = hexParts.filter(p => p !== '–' && p !== '').map(p => parseInt(p, 16));
  
  let asciiStr = '';
  const matrixContainer = document.getElementById('drawer-byte-matrix');
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
  
  document.getElementById('drawer-raw-ascii').textContent = asciiStr || '--';
  
  // Decoded signals logic
  const signalsContainer = document.getElementById('drawer-signals-list');
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
"""

with open('/home/leonardof/AgentCarDiag/server/app/static/app.js', 'w') as f:
    f.write(content + "\n" + drawer_js)
print("JS updated")
