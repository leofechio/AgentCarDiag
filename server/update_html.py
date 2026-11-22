import re

with open('/home/leonardof/AgentCarDiag/server/app/static/index.html', 'r') as f:
    content = f.read()

# Encontrar o start do can-table-wrapper e o final do aside
start_str = '<div class="can-table-wrapper">'
end_str = '</aside>'

start_idx = content.find(start_str)
end_idx = content.find(end_str) + len(end_str)

if start_idx != -1 and end_idx != -1:
    old_block = content[start_idx:end_idx]
    
    new_block = """<div class="sniffer-layout-wrapper">
        <div class="can-table-wrapper">
          <div class="can-table-scroll" id="can-table-scroll" role="region" aria-label="Tabela de frames CAN" aria-live="polite">
            <table class="can-table" id="can-table" aria-label="Frames CAN capturados">
              <thead>
                <tr>
                  <th scope="col">Timestamp</th>
                  <th scope="col">ID (Hex)</th>
                  <th scope="col">DLC</th>
                  <th scope="col">Dados (Hex)</th>
                  <th scope="col">Origem</th>
                </tr>
              </thead>
              <tbody id="can-tbody"></tbody>
            </table>
          </div>
          <div class="empty-state" id="can-empty-state" aria-label="Aguardando dados CAN">
            <div class="icon" aria-hidden="true">🔌</div>
            <div class="text">Aguardando frames CAN…</div>
            <div class="sub">Conecte o ESP32-S3 ou inicie o simulador</div>
          </div>
        </div>

        <!-- Gaveta Lateral de Inspeção CAN (Drawer) -->
        <aside id="can-inspector-drawer" class="can-drawer hidden">
          <div class="drawer-header">
            <div class="drawer-title-group">
              <span class="drawer-id-badge" id="drawer-can-id">0x7E8</span>
              <span class="drawer-msg-name" id="drawer-msg-name">OBD-II Diagnostic Response</span>
            </div>
            <button id="btn-close-drawer" class="btn-drawer-close" title="Fechar (Esc)">&times;</button>
          </div>

          <div class="drawer-body">
            <!-- Metadados do Frame -->
            <div class="drawer-block">
              <div class="block-title">METADADOS</div>
              <div class="meta-grid">
                <div><span class="meta-label">Timestamp:</span> <strong id="drawer-timestamp">--</strong></div>
                <div><span class="meta-label">DLC:</span> <strong id="drawer-dlc">8 bytes</strong></div>
                <div><span class="meta-label">Interface:</span> <strong id="drawer-bus">HS-CAN (500 kbps)</strong></div>
                <div><span class="meta-label">Origem:</span> <strong id="drawer-origin">OBD-II</strong></div>
              </div>
            </div>

            <!-- Matriz de Bytes e Bits -->
            <div class="drawer-block">
              <div class="block-title">BYTES & MATRIZ DE BITS (8x8)</div>
              <div id="drawer-byte-matrix" class="byte-matrix-container">
                <!-- Injetado dinamicamente via JS -->
              </div>
            </div>

            <!-- Decodificação Automotiva Inteligente (DBC) -->
            <div class="drawer-block">
              <div class="block-title">DECODIFICAÇÃO DE SINAIS (DBC VIRTUAL)</div>
              <div id="drawer-signals-list" class="signals-list">
                <!-- Sinais decodificados injetados aqui -->
              </div>
            </div>

            <!-- Conversões Rápidas -->
            <div class="drawer-block">
              <div class="block-title">REPRESENTAÇÃO BRUTA</div>
              <div class="raw-box">
                <div class="raw-row"><span>Hex Payload:</span> <code id="drawer-raw-hex">--</code></div>
                <div class="raw-row"><span>ASCII:</span> <code id="drawer-raw-ascii">--</code></div>
              </div>
            </div>
          </div>
        </aside>
        </div>"""
    
    new_content = content.replace(old_block, new_block)
    
    # Cache bust css and js to 14
    new_content = new_content.replace('styles.css?v=13', 'styles.css?v=14')
    new_content = new_content.replace('app.js?v=13', 'app.js?v=14')
    
    with open('/home/leonardof/AgentCarDiag/server/app/static/index.html', 'w') as f:
        f.write(new_content)
    print("HTML updated")
else:
    print("Could not find blocks")
