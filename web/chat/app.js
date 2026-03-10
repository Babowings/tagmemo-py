const state = {
  messages: [],
  sending: false,
  activeRequestId: null,
  eventStatus: 'idle',
  events: [],
  eventSource: null,
};

const el = {
  baseUrl: document.getElementById('baseUrl'),
  model: document.getElementById('model'),
  endpoint: document.getElementById('endpoint'),
  stream: document.getElementById('stream'),
  clearBtn: document.getElementById('clearBtn'),
  messages: document.getElementById('messages'),
  input: document.getElementById('input'),
  sendBtn: document.getElementById('sendBtn'),
  events: document.getElementById('events'),
  eventStatus: document.getElementById('eventStatus'),
  requestMeta: document.getElementById('requestMeta'),
};

function pushMessage(role, content) {
  state.messages.push({ role, content: content || '' });
  render();
  return state.messages.length - 1;
}

function updateMessage(index, content) {
  if (index < 0 || index >= state.messages.length) return;
  state.messages[index].content = content;
  render();
}

function render() {
  el.messages.innerHTML = '';
  for (const msg of state.messages) {
    const div = document.createElement('div');
    div.className = `msg ${msg.role}`;
    div.textContent = msg.content || '';
    el.messages.appendChild(div);
  }
  el.messages.scrollTop = el.messages.scrollHeight;
}

function renderEvents() {
  el.events.innerHTML = '';

  if (!state.events.length) {
    const empty = document.createElement('div');
    empty.className = 'evt';
    empty.textContent = '当前请求还没有收到结构化运行事件。';
    el.events.appendChild(empty);
  } else {
    for (const event of state.events) {
      const card = document.createElement('div');
      card.className = 'evt';

      const head = document.createElement('div');
      head.className = 'evtHead';

      const type = document.createElement('div');
      type.className = 'evtType';
      type.textContent = event.event_type || 'UNKNOWN_EVENT';

      const seq = document.createElement('div');
      seq.className = 'evtSeq';
      seq.textContent = `#${event.seq || '?'} ${formatEventTime(event.timestamp)}`;

      const payload = document.createElement('pre');
      payload.className = 'evtPayload';
      payload.textContent = formatEventPayload(event.payload || {});

      head.appendChild(type);
      head.appendChild(seq);
      card.appendChild(head);
      card.appendChild(payload);
      el.events.appendChild(card);
    }
  }

  el.eventStatus.textContent = getEventStatusLabel();
  el.eventStatus.className = `statusBadge ${state.eventStatus}`;
  el.requestMeta.textContent = state.activeRequestId
    ? `request_id: ${state.activeRequestId}`
    : '尚未发送请求。';
  el.events.scrollTop = el.events.scrollHeight;
}

function getEventStatusLabel() {
  if (state.eventStatus === 'running') return '进行中';
  if (state.eventStatus === 'done') return '已完成';
  if (state.eventStatus === 'error') return '错误';
  return '空闲';
}

function formatEventTime(ts) {
  if (!ts) return '--:--:--';
  const date = new Date(ts * 1000);
  return date.toLocaleTimeString('zh-CN', { hour12: false });
}

function formatEventPayload(payload) {
  try {
    return JSON.stringify(payload, null, 2);
  } catch {
    return String(payload || '');
  }
}

function buildRequestId() {
  if (globalThis.crypto && typeof globalThis.crypto.randomUUID === 'function') {
    return globalThis.crypto.randomUUID();
  }
  return `req-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function closeEventStream() {
  if (state.eventSource) {
    state.eventSource.close();
    state.eventSource = null;
  }
}

function hasTerminalEvent() {
  return state.events.some(event => event.event_type === 'REQUEST_END');
}

function beginRequestEvents(requestId) {
  closeEventStream();
  state.activeRequestId = requestId;
  state.eventStatus = 'running';
  state.events = [];
  renderEvents();

  const base = (el.baseUrl.value || '').trim().replace(/\/$/, '');
  const url = `${base}/v1/chat/events?request_id=${encodeURIComponent(requestId)}`;
  const source = new EventSource(url);
  state.eventSource = source;

  source.onmessage = (event) => {
    if (!event.data) return;
    try {
      const payload = JSON.parse(event.data);
      state.events.push(payload);
      if (payload.event_type === 'REQUEST_END') {
        state.eventStatus = payload.payload?.status === 'error' ? 'error' : 'done';
        closeEventStream();
      }
      renderEvents();
    } catch {
      // ignore malformed event payloads
    }
  };

  source.onerror = () => {
    if (hasTerminalEvent()) {
      if (state.eventStatus === 'running') {
        state.eventStatus = 'done';
      }
      closeEventStream();
      renderEvents();
      return;
    }

    if (state.eventStatus === 'running') {
      state.eventStatus = 'error';
      renderEvents();
    }
  };
}

function setSending(flag) {
  state.sending = flag;
  el.sendBtn.disabled = flag;
  el.sendBtn.textContent = flag ? '发送中...' : '发送';
}

function buildRequestBody() {
  return {
    model: (el.model.value || '').trim() || undefined,
    stream: !!el.stream.checked,
    messages: state.messages.map(m => ({ role: m.role, content: m.content })),
  };
}

function appendSystem(text) {
  pushMessage('system', text);
}

async function sendNonStream(url, body, assistantIndex) {
  const resp = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });

  if (!resp.ok) {
    const t = await resp.text();
    throw new Error(`HTTP ${resp.status}: ${t.slice(0, 500)}`);
  }

  const data = await resp.json();
  const content = data?.choices?.[0]?.message?.content || '';
  updateMessage(assistantIndex, content);
}

async function sendStream(url, body, assistantIndex) {
  const resp = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });

  if (!resp.ok || !resp.body) {
    const t = await resp.text();
    throw new Error(`HTTP ${resp.status}: ${t.slice(0, 500)}`);
  }

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let assistantText = '';

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let idx;
    while ((idx = buffer.indexOf('\n\n')) !== -1) {
      const eventBlock = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);

      const lines = eventBlock.split(/\r?\n/);
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        const payload = line.slice(6).trim();
        if (!payload || payload === '[DONE]') continue;

        try {
          const obj = JSON.parse(payload);
          const delta = obj?.choices?.[0]?.delta?.content;
          const msg = obj?.choices?.[0]?.message?.content;
          const piece = delta ?? msg ?? '';
          if (piece) {
            assistantText += piece;
            updateMessage(assistantIndex, assistantText);
          }
        } catch {
          // ignore non-standard data chunks
        }
      }
    }
  }
}

async function onSend() {
  if (state.sending) return;
  const text = (el.input.value || '').trim();
  if (!text) return;

  const userIndex = pushMessage('user', text);
  el.input.value = '';
  const assistantIndex = pushMessage('assistant', '');

  const base = (el.baseUrl.value || '').trim().replace(/\/$/, '');
  const endpoint = el.endpoint.value;
  const url = `${base}${endpoint}`;
  const requestId = buildRequestId();

  try {
    setSending(true);
    const body = buildRequestBody();
    body.request_id = requestId;
    beginRequestEvents(requestId);

    if (el.stream.checked) {
      await sendStream(url, body, assistantIndex);
    } else {
      await sendNonStream(url, body, assistantIndex);
    }

    if (!state.messages[assistantIndex].content) {
      updateMessage(assistantIndex, '(空响应)');
    }
  } catch (err) {
    state.eventStatus = 'error';
    renderEvents();
    updateMessage(assistantIndex, `请求失败：${err.message || err}`);
  } finally {
    setSending(false);
    render();
  }
}

el.sendBtn.addEventListener('click', onSend);
el.clearBtn.addEventListener('click', () => {
  state.messages = [];
  state.events = [];
  state.activeRequestId = null;
  state.eventStatus = 'idle';
  closeEventStream();
  renderEvents();
  render();
});
el.input.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    onSend();
  }
});

appendSystem('聊天前端已就绪。');
renderEvents();
