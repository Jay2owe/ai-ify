/* ai-ify chat panel: add <script src="/aiify/panel.js" defer></script> to a page.
 *
 * Optional attributes on the script tag:
 *   data-open="true"        start open
 *   data-theme="dark|light" force a theme (default follows the system)
 *   data-title="..."        panel title (default: the app name)
 *
 * Exposes window.aiify: open(), close(), toggle(), send(text), on(kind, fn),
 * post(type, payload) for the page bridge (stage 05), and info.
 */
(function () {
  'use strict';
  if (window.aiify && window.aiify.panel) return;
  const script = document.currentScript;
  const prefix = script ? script.src.replace(/\/panel\.js(\?.*)?$/, '') : '/aiify';
  const opts = script ? script.dataset : {};
  const STORE = 'aiify-panel:' + location.pathname.split('/')[1];

  const api = window.aiify = Object.assign(window.aiify || {}, { panel: true, prefix, info: null });
  const listeners = {};
  api.on = (kind, fn) => { (listeners[kind] = listeners[kind] || []).push(fn); };
  const fire = (kind, ev) => (listeners[kind] || []).forEach(fn => { try { fn(ev); } catch (e) { console.error(e); } });

  // Named UI commands and the page-state hook live in bridge.js; until it has
  // loaded, calls are queued so host code can register at any time after this file.
  if (!api.registerTool) api.registerTool = tool => { (api._pendingTools = api._pendingTools || []).push(tool); };
  if (!api.setState) api.setState = fn => { api._pendingState = fn; };
  if (opts.bridge !== 'false' && !api.bridge) {
    const b = document.createElement('script');
    b.src = prefix + '/bridge.js';
    document.head.appendChild(b);
  }

  function remember(key, value) {
    try {
      const all = JSON.parse(localStorage.getItem(STORE) || '{}');
      if (value === undefined) return all[key];
      all[key] = value; localStorage.setItem(STORE, JSON.stringify(all));
    } catch (e) { return undefined; }
  }

  // -- DOM ------------------------------------------------------------------------------
  const host = document.createElement('div');
  host.id = 'aiify-root';
  host.setAttribute('data-agent', 'off');          // the control tree never touches the panel
  if (opts.theme) host.setAttribute('data-theme', opts.theme);
  const root = host.attachShadow({ mode: 'open' });

  function el(tag, attrs = {}, ...kids) {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (v == null) continue;
      if (k === 'class') e.className = v;
      else if (k.startsWith('on')) e[k] = v;
      else e.setAttribute(k, v);
    }
    for (const k of kids) if (k != null) e.append(k.nodeType ? k : document.createTextNode(String(k)));
    return e;
  }

  const ui = {};
  ui.css = el('link', { rel: 'stylesheet', href: prefix + '/panel.css' });
  ui.launcher = el('button', { class: 'launcher', title: 'Open the assistant', onclick: () => api.open() }, 'AI');
  ui.title = el('div', { class: 'title' }, opts.title || 'Assistant');
  ui.newBtn = el('button', { class: 'quiet', title: 'Start a new conversation', onclick: () => post('new') }, 'New chat');
  ui.consoleBtn = el('button', { class: 'quiet', title: 'Open this conversation in a terminal', onclick: openConsole }, 'Console');
  ui.closeBtn = el('button', { class: 'quiet', title: 'Hide the panel', onclick: () => api.close() }, '✕');
  ui.profile = el('select', { title: 'Profile' });
  ui.provider = el('select', { title: 'Agent' });
  ui.model = el('select', { title: 'Model' });
  ui.effort = el('select', { title: 'Effort' });
  ui.mode = el('select', { title: 'Permission mode' });
  ui.profileLabel = el('label', {}, ui.profile);
  ui.account = el('select', { title: 'Saved Codex account (switches between messages)' });
  ui.accountLabel = el('label', {}, 'account', ui.account);
  ui.limits = el('div', { class: 'limits' });
  ui.status = el('div', { class: 'status' }, 'connecting...');
  ui.log = el('div', { class: 'log', role: 'log', 'aria-live': 'polite' });
  ui.input = el('textarea', { rows: '1', placeholder: 'Ask the assistant...' });
  ui.sendBtn = el('button', { class: 'primary', onclick: sendOrStop }, 'Send');
  ui.grip = el('div', { class: 'grip', title: 'Drag to resize' });
  ui.panel = el('div', { class: 'panel', hidden: '' },
    ui.grip,
    el('div', { class: 'head' }, ui.title, ui.newBtn, ui.consoleBtn, ui.closeBtn),
    el('div', { class: 'cfg' }, ui.profileLabel, ui.provider,
      el('label', {}, 'model', ui.model), el('label', {}, 'effort', ui.effort), el('label', {}, 'mode', ui.mode),
      ui.accountLabel),
    ui.limits, ui.status, ui.log,
    el('div', { class: 'composer' }, ui.input, ui.sendBtn));
  root.append(ui.css, ui.launcher, ui.panel);

  ui.input.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); sendOrStop(); }
  });
  ui.input.addEventListener('input', () => {
    ui.input.style.height = 'auto'; ui.input.style.height = Math.min(ui.input.scrollHeight, 160) + 'px';
  });
  ui.profile.onchange = () => post('settings', { profile: ui.profile.value });
  ui.provider.onchange = () => post('settings', { provider: ui.provider.value });
  ui.account.onchange = () => post('account', { id: ui.account.value });
  for (const role of ['model', 'effort', 'mode']) ui[role].onchange = () => post('settings', { [role]: ui[role].value });

  // resize from the left edge
  ui.grip.addEventListener('pointerdown', e => {
    e.preventDefault(); ui.grip.setPointerCapture(e.pointerId);
    const move = ev => setWidth(window.innerWidth - ev.clientX);
    const up = () => { ui.grip.removeEventListener('pointermove', move); ui.grip.removeEventListener('pointerup', up); remember('width', host.style.getPropertyValue('--aiify-width')); };
    ui.grip.addEventListener('pointermove', move); ui.grip.addEventListener('pointerup', up);
  });
  function setWidth(px) { host.style.setProperty('--aiify-width', Math.max(300, Math.min(px, window.innerWidth - 40)) + 'px'); }
  const savedWidth = remember('width'); if (savedWidth) host.style.setProperty('--aiify-width', savedWidth);

  api.open = () => { ui.panel.hidden = false; ui.launcher.hidden = true; remember('open', true); setTimeout(() => ui.input.focus(), 0); fire('open', {}); };
  api.close = () => { ui.panel.hidden = true; ui.launcher.hidden = false; remember('open', false); fire('close', {}); };
  api.toggle = () => (ui.panel.hidden ? api.open() : api.close());

  // -- server calls -----------------------------------------------------------------------
  async function post(path, body) {
    try {
      const r = await fetch(prefix + '/api/' + path, { method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Aiify': '1' }, body: JSON.stringify(body || {}) });
      const data = await r.json();
      if (!data.ok) line('err', data.error || 'request failed');
      return data;
    } catch (e) { line('err', 'could not reach the app: ' + e.message); return { ok: false }; }
  }
  api.send = text => post('send', { text });
  function sendOrStop() {
    if (api.info && api.info.busy) { post('cancel'); return; }
    const text = ui.input.value.trim(); if (!text) return;
    ui.input.value = ''; ui.input.style.height = 'auto';
    api.send(text);
  }
  async function openConsole() {
    const r = await post('console');
    if (r.ok) line('sys', 'Opened in a terminal.');
  }

  // -- rendering --------------------------------------------------------------------------
  let current = null, currentText = '', tools = {}, perms = {}, hadMessages = false;

  function esc(s) { return String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])); }
  function inline(s) {
    return s.replace(/`([^`]+)`/g, '<code>$1</code>')
      .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
      .replace(/(^|[^*])\*([^*\s][^*]*)\*/g, '$1<em>$2</em>')
      .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
  }
  // Small, safe markdown: everything is escaped first, then a few patterns become tags.
  function markdown(src) {
    const out = [], parts = String(src).split(/```/);
    parts.forEach((part, i) => {
      if (i % 2) { out.push('<pre><code>' + esc(part.replace(/^[\w-]*\n/, '')) + '</code></pre>'); return; }
      let list = null;
      for (const raw of esc(part).split('\n')) {
        const bullet = raw.match(/^\s*([-*]|\d+\.)\s+(.*)$/);
        if (bullet) {
          const tag = /\d/.test(bullet[1]) ? 'ol' : 'ul';
          if (list !== tag) { if (list) out.push(`</${list}>`); out.push(`<${tag}>`); list = tag; }
          out.push('<li>' + inline(bullet[2]) + '</li>'); continue;
        }
        if (list) { out.push(`</${list}>`); list = null; }
        const h = raw.match(/^(#{1,4})\s+(.*)$/);
        if (h) out.push(`<h${h[1].length}>` + inline(h[2]) + `</h${h[1].length}>`);
        else if (raw.trim()) out.push('<p>' + inline(raw) + '</p>');
      }
      if (list) out.push(`</${list}>`);
    });
    return out.join('');
  }

  // the agents often repeat the command as both title and first detail line
  function trim(title, detail) {
    detail = detail || '';
    return title && detail.startsWith(title) ? detail.slice(title.length).replace(/^\n/, '') : detail;
  }
  function scroll() { ui.log.scrollTop = ui.log.scrollHeight; }
  function line(cls, text) {
    clearEmpty(); current = null;
    const d = el('div', { class: 'msg ' + cls }, text); ui.log.append(d); scroll(); return d;
  }
  function clearEmpty() { const e = ui.log.querySelector('.empty'); if (e) e.remove(); }
  function showEmpty() {
    if (!ui.log.children.length) ui.log.append(el('div', { class: 'empty' },
      'Ask about what is on screen, or ask the assistant to do something in the app. It asks before risky steps.'));
  }
  function resetLog() { ui.log.innerHTML = ''; current = null; currentText = ''; tools = {}; perms = {}; showEmpty(); }

  function render(ev) {
    switch (ev.kind) {
      case 'reset': resetLog(); break;
      case 'user': line('user', ev.text); break;
      case 'text':
        clearEmpty();
        if (!current) { current = el('div', { class: 'msg reply' }); currentText = ''; ui.log.append(current); }
        currentText += ev.text; current.innerHTML = markdown(currentText); scroll(); break;
      case 'thought': line('thought', ev.text); break;
      case 'tool': {
        clearEmpty(); current = null;
        const pre = el('pre', {}, trim(ev.title, ev.detail));
        const st = el('span', { class: 'st' }, ev.status || '');
        const box = el('details', { class: 'tool ' + (ev.status || '') }, el('summary', {}, el('span', {}, ev.title || 'tool'), st), pre);
        tools[ev.id] = { box, pre, st }; ui.log.append(box); scroll(); break; }
      case 'tool_update': {
        const t = tools[ev.id]; if (!t) break;
        if (ev.status) { t.box.className = 'tool ' + ev.status; t.st.textContent = ev.status; }
        if (ev.title) t.box.querySelector('summary span').textContent = ev.title;
        const more = trim(t.box.querySelector('summary span').textContent, ev.detail);
        if (more && !t.pre.textContent.includes(more)) t.pre.textContent = (t.pre.textContent ? t.pre.textContent + '\n' : '') + more;
        break; }
      case 'plan': {
        clearEmpty(); current = null;
        const ul = el('ul', { class: 'plan' });
        for (const e of ev.entries || []) ul.append(el('li', { class: e.status }, e.text));
        ui.log.append(ul); scroll(); break; }
      case 'permission': {
        clearEmpty(); current = null;
        const row = el('div', { class: 'opts' });
        const box = el('div', { class: 'perm' }, el('strong', {}, (ev.source === 'action' ? '' : 'The assistant asks: ') + ev.title),
          trim(ev.title, ev.detail) ? el('pre', {}, trim(ev.title, ev.detail)) : null, row);
        for (const o of ev.options || []) row.append(el('button', {
          class: String(o.kind).startsWith('allow') ? 'primary' : '',
          onclick: () => post('answer', { id: ev.id, option: o.id }) }, o.name));
        perms[ev.id] = { box, row, options: ev.options || [] }; ui.log.append(box); scroll(); break; }
      case 'permission_done': {
        const p = perms[ev.id]; if (!p) break;
        const chosen = p.options.find(o => o.id === ev.option);
        p.row.replaceWith(el('div', { class: 'msg sys' }, chosen ? 'You chose: ' + chosen.name : 'Not allowed (no answer).'));
        p.box.classList.add('answered'); break; }
      case 'status': ui.status.textContent = ev.text; break;
      case 'ready': ui.status.textContent = `ready · started in ${ev.startup}s`; break;
      case 'error': line('err', ev.text); break;
      case 'done': {
        current = null;
        const parts = [];
        if (ev.stop && ev.stop !== 'end_turn') parts.push(ev.stop === 'cancelled' ? 'stopped' : ev.stop);
        if (ev.first_words != null) parts.push(`first words ${ev.first_words}s`);
        if (ev.total != null) parts.push(`total ${ev.total}s`);
        if (ev.tools) parts.push(`${ev.tools} tool call${ev.tools > 1 ? 's' : ''}`);
        if (ev.waiting_on_you) parts.push(`waiting on you ${ev.waiting_on_you}s`);
        ui.log.append(el('div', { class: 'done' }, parts.join(' · '))); scroll(); break; }
    }
  }

  function fill(select, choices, value, labels) {
    select.innerHTML = '';
    for (const c of choices || []) select.append(el('option', { value: c }, (labels && labels[c]) || c));
    if (value != null) select.value = value;
    select.disabled = !(choices && choices.length);
  }

  function clock(iso) {
    if (!iso) return '';
    const d = new Date(iso), now = new Date();
    const hm = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    return d.toDateString() === now.toDateString() ? hm : d.toLocaleDateString([], { weekday: 'short' }) + ' ' + hm;
  }
  // one bar per subscription window of the agent in use, e.g. "5h ▮▮▮▯ 40% · resets 14:10"
  function showLimits(info) {
    const windows = ((info.limits || {}).providers || {})[info.provider] || [];
    ui.limits.innerHTML = '';
    ui.limits.hidden = !windows.length;
    for (const w of windows) {
      const pct = w.used == null ? null : Math.max(0, Math.min(100, w.used));
      const text = (pct == null ? (w.status || '?') : Math.round(pct) + '%') +
        (w.expired ? ' · reset' : w.resets_at ? ' · resets ' + clock(w.resets_at) : '');
      const fill = el('span', { class: 'fill' }); fill.style.width = (pct || 0) + '%';
      ui.limits.append(el('div', { class: 'limit' + (w.warn ? ' warn' : ''), title: `${w.label} limit: ${text}` },
        el('span', { class: 'name' }, w.label), el('span', { class: 'bar' }, fill), el('span', { class: 'pct' }, text)));
    }
  }

  function applyInfo(info) {
    api.info = info;
    if (!opts.title) ui.title.textContent = 'Assistant · ' + info.app;
    const profiles = info.profiles || [];
    fill(ui.profile, profiles.map(p => p.name), info.profile, Object.fromEntries(profiles.map(p => [p.name, p.label])));
    ui.profileLabel.style.display = profiles.length > 1 ? '' : 'none';
    fill(ui.provider, (info.providers || []).map(p => p.name), info.provider,
      Object.fromEntries((info.providers || []).map(p => [p.name, p.label])));
    for (const role of ['model', 'effort', 'mode']) {
      const o = (info.options || {})[role];
      if (o) fill(ui[role], o.choices, o.value);
      else fill(ui[role], info.settings && info.settings[role] ? [info.settings[role]] : [], info.settings && info.settings[role]);
      ui[role].parentElement.style.display = o || (info.settings && info.settings[role]) ? '' : (info.ready ? 'none' : '');
    }
    const acc = info.accounts;
    ui.accountLabel.style.display = acc ? '' : 'none';
    if (acc) fill(ui.account, acc.choices.map(c => c.id), acc.pending || acc.current,
      Object.fromEntries(acc.choices.map(c => [c.id, c.name + (c.id === acc.pending ? ' (after this reply)' : '')])));
    showLimits(info);
    ui.sendBtn.textContent = info.busy ? 'Stop' : 'Send';
    ui.sendBtn.className = info.busy ? '' : 'primary';
    ui.launcher.classList.toggle('busy', !!info.busy);
    ui.consoleBtn.disabled = !(info.console && info.console.available);
    ui.consoleBtn.title = info.console && info.console.available ? 'Open this conversation in a terminal'
      : 'Console: ' + ((info.console && info.console.reason) || 'not available');
    if (!info.ready && !info.busy) ui.status.textContent = 'starting the assistant...';
  }

  // -- websocket ------------------------------------------------------------------------------
  let socket = null, retry = 500;
  api.post = (type, payload) => {
    if (socket && socket.readyState === 1) { socket.send(JSON.stringify(Object.assign({ type }, payload || {}))); return true; }
    return false;
  };
  function connect() {
    const url = prefix.replace(/^http/, 'ws') + '/ws';
    socket = new WebSocket(url.startsWith('ws') ? url : (location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + url);
    socket.onopen = () => { retry = 500; fire('connect', {}); };
    socket.onmessage = m => {
      const ev = JSON.parse(m.data);
      if (ev.kind === 'hello') {
        resetLog(); applyInfo(ev.info);
        for (const h of ev.history || []) render(h);
        ui.status.textContent = ev.info.ready ? 'ready' : 'starting the assistant...';
      } else if (ev.kind === 'info') applyInfo(ev.info);
      else render(ev);
      fire(ev.kind, ev);
    };
    socket.onclose = () => {
      ui.status.textContent = 'disconnected - retrying...'; fire('disconnect', {});
      setTimeout(connect, retry); retry = Math.min(retry * 2, 8000);
    };
  }

  function boot() {
    document.body.append(host);
    resetLog();
    if (opts.open === 'true' || remember('open')) api.open();
    connect();
  }
  if (document.body) boot(); else document.addEventListener('DOMContentLoaded', boot);
})();
