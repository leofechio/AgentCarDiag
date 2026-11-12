// dev_agent.js — Agente Dev Chat com Histórico
(function () {
  'use strict';

  let currentChatId = null;
  let chatHistory = [];   // [{role, content}] — contexto Gemini da sessão atual
  let isThinking = false;

  // ── Markdown simples ─────────────────────────────────────────────────────────
  function renderMarkdown(text) {
    return text
      .replace(/```cpp([\s\S]*?)```/g, '<pre><code>$1</code></pre>')
      .replace(/```([\s\S]*?)```/g, '<pre><code>$1</code></pre>')
      .replace(/`([^`]+)`/g, '<code style="background:#0d1117;padding:2px 5px;border-radius:3px;font-family:monospace;font-size:11px;">$1</code>')
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      .replace(/\*(.+?)\*/g, '<em>$1</em>')
      .replace(/\n/g, '<br>');
  }

  function formatDate(isoStr) {
    if (!isoStr) return '';
    const d = new Date(isoStr);
    return d.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' }) +
           ' ' + d.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
  }

  // ── Elementos DOM ─────────────────────────────────────────────────────────────
  const $ = id => document.getElementById(id);

  // ── Mensagens ─────────────────────────────────────────────────────────────────
  function getMessages() { return $('devagent-messages'); }

  function clearMessages() {
    const msgs = getMessages();
    if (msgs) msgs.innerHTML = '';
  }

  function addMessage(role, content) {
    const msgs = getMessages();
    if (!msgs) return null;
    const wrap = document.createElement('div');
    wrap.className = role === 'user' ? 'devagent-msg-user' : 'devagent-msg-ai';
    const bubble = document.createElement('div');
    bubble.className = role === 'user' ? 'devagent-bubble-user' : 'devagent-bubble-ai';
    bubble.innerHTML = renderMarkdown(content);
    wrap.appendChild(bubble);
    msgs.appendChild(wrap);
    msgs.scrollTop = msgs.scrollHeight;
    return bubble;
  }

  function addToolLine(icon, html) {
    const msgs = getMessages();
    if (!msgs) return;
    const wrap = document.createElement('div');
    wrap.style.cssText = 'display:flex;justify-content:center;margin:2px 0;';
    const line = document.createElement('div');
    line.className = 'devagent-tool-line';
    line.innerHTML = icon + ' ' + html;
    wrap.appendChild(line);
    msgs.appendChild(wrap);
    msgs.scrollTop = msgs.scrollHeight;
  }

  function showTyping() {
    const msgs = getMessages();
    if (!msgs) return;
    removeTyping();
    const wrap = document.createElement('div');
    wrap.className = 'devagent-msg-ai';
    wrap.id = 'devagent-typing';
    const bubble = document.createElement('div');
    bubble.className = 'devagent-bubble-ai';
    bubble.innerHTML = '<div class="devagent-typing"><span></span><span></span><span></span></div>';
    wrap.appendChild(bubble);
    msgs.appendChild(wrap);
    msgs.scrollTop = msgs.scrollHeight;
  }

  function removeTyping() {
    const el = $('devagent-typing');
    if (el) el.remove();
  }

  // ── Sidebar de histórico ───────────────────────────────────────────────────────
  async function loadChatHistory() {
    const list = $('devagent-chat-list');
    if (!list) return;
    try {
      const resp = await fetch('/api/dev_agent/chats');
      const chats = await resp.json();
      list.innerHTML = '';
      if (!chats.length) {
        list.innerHTML = '<div style="padding:12px;color:var(--text-muted);font-size:11px;text-align:center;">Nenhuma conversa ainda</div>';
        return;
      }
      for (const chat of chats) {
        const item = document.createElement('div');
        item.className = 'devagent-chat-item' + (chat.id === currentChatId ? ' active' : '');
        item.dataset.chatId = chat.id;
        item.innerHTML = `
          <div class="devagent-chat-item-title" title="${chat.title}">${chat.title}</div>
          <div class="devagent-chat-item-date">${formatDate(chat.updated_at)}</div>
          <button class="devagent-chat-delete" onclick="devAgentDeleteChat('${chat.id}', event)" title="Apagar">🗑</button>
        `;
        item.onclick = (e) => { if (!e.target.closest('.devagent-chat-delete')) devAgentLoadChat(chat.id); };
        list.appendChild(item);
      }
    } catch (e) {
      console.error('Erro ao carregar histórico:', e);
    }
  }

  async function devAgentLoadChat(chatId) {
    try {
      const resp = await fetch(`/api/dev_agent/chats/${chatId}`);
      if (!resp.ok) return;
      const chat = await resp.json();

      // Atualiza estado
      currentChatId = chatId;
      chatHistory = [];
      clearMessages();

      // Renderiza mensagens salvas
      for (const msg of chat.messages) {
        addMessage(msg.role === 'assistant' ? 'ai' : msg.role, msg.content);
        chatHistory.push({ role: msg.role === 'assistant' ? 'assistant' : 'user', content: msg.content });
      }

      // Atualiza seleção na sidebar
      document.querySelectorAll('.devagent-chat-item').forEach(el => {
        el.classList.toggle('active', el.dataset.chatId === chatId);
      });

    } catch (e) {
      console.error('Erro ao carregar conversa:', e);
    }
  }

  async function devAgentDeleteChat(chatId, event) {
    event.stopPropagation();
    if (!confirm('Apagar esta conversa?')) return;
    await fetch(`/api/dev_agent/chats/${chatId}`, { method: 'DELETE' });
    if (currentChatId === chatId) devAgentNewChat();
    loadChatHistory();
  }

  function devAgentNewChat() {
    currentChatId = null;
    chatHistory = [];
    clearMessages();
    // Mensagem de boas-vindas
    addMessage('ai',
      '👋 Olá! Sou o **Agente Dev do AgentCarDiag**.\n\nPosso te ajudar a:\n• 🔍 Testar a comunicação com o carro em tempo real\n• 📊 Ler PIDs OBD-II e interpretar os dados\n• 🐛 Identificar problemas no firmware\n• 💻 Sugerir e ajustar código C++ para o ESP32\n\nComece me dizendo o que está fazendo! Ex: *"pluguei o scanner no carro, consegue testar?"*'
    );
    document.querySelectorAll('.devagent-chat-item').forEach(el => el.classList.remove('active'));
  }

  // ── Envio de mensagem ─────────────────────────────────────────────────────────
  const TOOL_META = {
    get_hardware_status: { icon: '🔌', label: 'Verificando status do hardware...' },
    send_obd_query:      { icon: '📡', label: 'Enviando query OBD-II para o carro...' },
    start_live_stream:   { icon: '▶️', label: 'Iniciando live stream de PIDs...' },
    stop_live_stream:    { icon: '⏹️', label: 'Parando live stream...' }
  };

  async function devAgentSend() {
    if (isThinking) return;
    const input = $('devagent-input');
    const btn = $('devagent-send-btn');
    const message = input ? input.value.trim() : '';
    if (!message) return;

    addMessage('user', message);
    if (input) input.value = '';
    input.style.height = 'auto';

    isThinking = true;
    if (btn) { btn.disabled = true; btn.textContent = '...'; }
    showTyping();

    // Prepara o histórico para o contexto
    const historyForContext = chatHistory.filter(m => m.role === 'user' || m.role === 'assistant')
      .map(m => ({ role: m.role === 'assistant' ? 'assistant' : 'user', content: m.content }));

    try {
      const resp = await fetch('/api/dev_agent/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message,
          chat_id: currentChatId,
          history: historyForContext
        })
      });

      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        removeTyping();
        addMessage('ai', '❌ Erro: ' + (err.error || 'Falha na requisição'));
        return;
      }

      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let aiBuffer = '';
      let aiBubble = null;
      let firstText = true;

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        const lines = decoder.decode(value).split('\n');
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          let data;
          try { data = JSON.parse(line.slice(6)); } catch { continue; }

          if (data.type === 'chat_id') {
            currentChatId = data.chat_id;
            loadChatHistory();
          }

          if (data.type === 'tool_call') {
            const meta = TOOL_META[data.tool] || { icon: '⚙️', label: data.tool };
            const extra = data.args && data.args.query ? ` <strong>${data.args.query}</strong>`
              : (data.args && data.args.pids ? ` [${data.args.pids.join(', ')}]` : '');
            addToolLine(meta.icon, meta.label.replace('...', '') + extra);
          }

          if (data.type === 'tool_result') {
            const res = data.result || {};
            if (data.tool === 'get_hardware_status') {
              const ok = res.any_connected;
              addToolLine(ok ? '✅' : '❌', ok ? 'Hardware online e conectado' : 'Hardware offline ou desconectado');
            } else if (data.tool === 'send_obd_query') {
              addToolLine(res.status === 'received' ? '📥' : '⚠️',
                res.status === 'received' ? `Resposta: <strong>${res.raw}</strong>` : 'Timeout — ' + (res.note || 'sem resposta'));
            } else if (res.status === 'started') {
              addToolLine('✅', 'Live stream ativo: ' + (res.pids || []).join(', '));
            } else if (res.status === 'stopped') {
              addToolLine('⏹️', 'Live stream parado');
            }
          }

          if (data.type === 'message') {
            if (firstText) { removeTyping(); firstText = false; aiBubble = addMessage('ai', ''); aiBuffer = ''; }
            aiBuffer += data.content;
            if (aiBubble) aiBubble.innerHTML = renderMarkdown(aiBuffer);
            const msgs = getMessages();
            if (msgs) msgs.scrollTop = msgs.scrollHeight;
          }

          if (data.type === 'done') {
            removeTyping();
            chatHistory.push({ role: 'user', content: message });
            if (aiBuffer) chatHistory.push({ role: 'assistant', content: aiBuffer });
            loadChatHistory();
          }

          if (data.type === 'error') {
            removeTyping();
            addMessage('ai', '❌ Erro: ' + data.content);
          }
        }
      }
    } catch (err) {
      removeTyping();
      addMessage('ai', '❌ Erro de rede: ' + err.message);
    } finally {
      isThinking = false;
      if (btn) { btn.disabled = false; btn.textContent = '↑ Enviar'; }
    }
  }

  function devAgentKeydown(event) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      devAgentSend();
    }
  }

  function devAgentInputResize(el) {
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 120) + 'px';
  }

  // ── Indicador de hardware ────────────────────────────────────────────────────
  function devAgentUpdateHwStatus(nodes) {
    const dot  = $('devagent-hw-indicator');
    const text = $('devagent-hw-status');
    if (!dot || !text) return;
    const sc = nodes && nodes['Scanner_CAN'];
    const ok = sc && sc.connected;
    dot.style.background  = ok ? 'var(--accent-green)' : 'var(--accent-red)';
    text.textContent      = ok ? `Scanner Online (${Math.round(sc.ping_ms || 0)}ms)` : 'Scanner Offline';
  }

  // ── Inicialização ─────────────────────────────────────────────────────────────
  document.addEventListener('DOMContentLoaded', () => {
    loadChatHistory();
  });

  // Expõe funções globais
  window.devAgentSend            = devAgentSend;
  window.devAgentKeydown         = devAgentKeydown;
  window.devAgentInputResize     = devAgentInputResize;
  window.devAgentUpdateHwStatus  = devAgentUpdateHwStatus;
  window.devAgentNewChat         = devAgentNewChat;
  window.devAgentLoadChat        = devAgentLoadChat;
  window.devAgentDeleteChat      = devAgentDeleteChat;
  window.devAgentLoadHistory     = loadChatHistory;
})();
