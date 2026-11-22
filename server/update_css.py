import re

with open('/home/leonardof/AgentCarDiag/server/app/static/styles.css', 'r') as f:
    content = f.read()

# Remover bloco antigo do Drawer
start_old = '/* --- CAN Drawer --- */'
start_idx = content.find(start_old)
if start_idx != -1:
    content = content[:start_idx]

new_css = """/* Container relativo do Sniffer para ancorar o drawer */
.sniffer-layout-wrapper {
  position: relative;
  overflow: hidden;
  display: flex;
  width: 100%;
  height: 100%;
}

/* Gaveta Lateral Retrátil */
.can-drawer {
  position: absolute;
  top: 0;
  right: 0;
  width: 440px;
  max-width: 90vw;
  height: 100%;
  background: #0b111e;
  border-left: 1px solid #1e293b;
  box-shadow: -8px 0 25px rgba(0, 0, 0, 0.6);
  z-index: 100;
  display: flex;
  flex-direction: column;
  transform: translateX(100%);
  transition: transform 0.25s cubic-bezier(0.16, 1, 0.3, 1);
}

.can-drawer:not(.hidden) {
  transform: translateX(0);
}

.can-drawer.hidden {
  transform: translateX(100%);
  pointer-events: none;
}

.drawer-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 18px;
  background: #0f172a;
  border-bottom: 1px solid #1e293b;
}

.drawer-id-badge {
  background: #0284c7;
  color: #fff;
  font-family: monospace;
  font-weight: 700;
  padding: 3px 8px;
  border-radius: 4px;
  font-size: 13px;
  margin-right: 8px;
}

.drawer-msg-name {
  color: #f8fafc;
  font-weight: 600;
  font-size: 13px;
}

.btn-drawer-close {
  background: transparent;
  border: none;
  color: #94a3b8;
  font-size: 22px;
  cursor: pointer;
  line-height: 1;
}

.btn-drawer-close:hover {
  color: #ef4444;
}

.drawer-body {
  padding: 16px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.drawer-block {
  background: #070d19;
  border: 1px solid #1e293b;
  border-radius: 6px;
  padding: 12px;
}

.block-title {
  font-size: 10px;
  font-weight: 700;
  color: #64748b;
  letter-spacing: 0.05em;
  margin-bottom: 8px;
}

.meta-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  font-size: 11px;
}

.meta-label {
  color: #94a3b8;
}

/* Matriz de Bytes e Bits */
.byte-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 6px;
  border-bottom: 1px solid #131d31;
  font-family: monospace;
  font-size: 11px;
}

.byte-label {
  color: #38bdf8;
  width: 28px;
}

.byte-hex {
  color: #00ff66;
  font-weight: bold;
  width: 32px;
}

.bit-group {
  display: flex;
  gap: 3px;
}

.bit-cell {
  width: 16px;
  height: 16px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 10px;
  border-radius: 2px;
}

.bit-cell.b1 {
  background: rgba(0, 255, 102, 0.15);
  color: #00ff66;
  font-weight: bold;
}

.bit-cell.b0 {
  background: rgba(148, 163, 184, 0.08);
  color: #475569;
}

/* Sinais Decodificados */
.signal-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 6px 0;
  border-bottom: 1px solid #131d31;
  font-size: 12px;
}

.signal-name {
  color: #cbd5e1;
}

.signal-value {
  font-family: monospace;
  font-weight: 700;
  color: #38bdf8;
}

/* Linha da tabela selecionada */
#can-table tbody tr.selected-can-row {
  background: rgba(56, 189, 248, 0.15) !important;
  border-left: 3px solid #38bdf8 !important;
}

.raw-box {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.raw-row {
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: 11px;
  color: #94a3b8;
}
.raw-row code {
  background: #000;
  padding: 6px 8px;
  border-radius: 4px;
  font-family: monospace;
  font-size: 12px;
  color: #e2e8f0;
  word-break: break-all;
}
"""

with open('/home/leonardof/AgentCarDiag/server/app/static/styles.css', 'w') as f:
    f.write(content + "\n" + new_css)
print("CSS updated")
