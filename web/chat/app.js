const state = {
  messages: [],
  sending: false,
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

  try {
    setSending(true);
    const body = buildRequestBody();

    if (el.stream.checked) {
      await sendStream(url, body, assistantIndex);
    } else {
      await sendNonStream(url, body, assistantIndex);
    }

    if (!state.messages[assistantIndex].content) {
      updateMessage(assistantIndex, '(空响应)');
    }
  } catch (err) {
    updateMessage(assistantIndex, `请求失败：${err.message || err}`);
  } finally {
    setSending(false);
    render();
  }
}

el.sendBtn.addEventListener('click', onSend);
el.clearBtn.addEventListener('click', () => {
  state.messages = [];
  render();
});
el.input.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    onSend();
  }
});

appendSystem('聊天前端已就绪。');
