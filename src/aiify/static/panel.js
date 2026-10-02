/* ai-ify chat panel: add <script src="/aiify/panel.js" defer></script> to a page.
 *
 * Optional attributes on the script tag:
 *   data-open="true"          start open
 *   data-theme="dark|light"   force a theme (default follows the system)
 *   data-title="..."          panel title (default: the app name)
 *   data-layout="..."         where the panel sits at first: "overlay" (over the right
 *                             edge, the default), "dock" (the page shrinks to make room),
 *                             "float" (a window that can be dragged and resized) or
 *                             "inline" (inside the element named by data-target)
 *   data-target="#id"         the element an inline panel fills
 *   data-opacity="30..100"    how solid the panel's background is at first (percent)
 *   data-launcher="none"      no round button; the app opens the panel with aiify.open()
 *   data-accent="#2b6cb0"     the panel's accent colour
 *   data-font="system"        use the system font instead of the page's
 * The person can change the layout (except inline) and the opacity in the panel;
 * their choice is remembered in this browser.
 *
 * Exposes window.aiify: open(), close(), toggle(), send(text), launch(name, data, attach),
 * attach(item), setLayout(name), setOpacity(percent), on(kind, fn), post(type, payload)
 * for the page bridge, and info. attach() takes a File/Blob, {name, text} or
 * {name, dataUrl} (e.g. canvas.toDataURL()); it goes with the next message.
 *
 * Launch buttons: any element with data-aiify-launch="name" (and optionally
 * data-aiify-data='{"json": "data"}') opens the panel and starts the app's launch
 * of that name, with its own context.
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
  const LAYOUTS = { overlay: 'Side', dock: 'Docked', float: 'Window' };
  const noLauncher = opts.launcher === 'none';
  const host = document.createElement('div');
  host.id = 'aiify-root';
  host.setAttribute('data-agent', 'off');          // the control tree never touches the panel
  if (opts.theme) host.setAttribute('data-theme', opts.theme);
  if (opts.accent) host.style.setProperty('--aiify-accent', opts.accent);
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
  ui.layout = el('select', { title: 'Where the panel sits' });
  for (const [k, v] of Object.entries(LAYOUTS)) ui.layout.append(el('option', { value: k }, v));
  ui.layoutLabel = el('label', {}, 'view', ui.layout);
  ui.alpha = el('input', { type: 'range', min: '30', max: '100', step: '5',
    title: 'Opacity: lower lets the app show through' });
  ui.alphaLabel = el('label', { class: 'alpha' }, 'opacity', ui.alpha);
  ui.profile = el('select', { title: 'Profile' });
  ui.provider = el('select', { title: 'Agent' });
  ui.model = el('select', { title: 'Model' });
  ui.effort = el('select', { title: 'Effort' });
  ui.mode = el('select', { title: 'Permission mode' });
  ui.profileLabel = el('label', {}, ui.profile);
  ui.account = el('select', { title: 'Saved Codex account (switches between messages)' });
  ui.accountLabel = el('label', {}, 'account', ui.account);
  ui.limits = el('div', { class: 'limits' });
  ui.signin = el('div', { class: 'signin', hidden: true });
  ui.status = el('div', { class: 'status' }, 'connecting...');
  ui.log = el('div', { class: 'log', role: 'log', 'aria-live': 'polite' });
  ui.input = el('textarea', { rows: '1', placeholder: 'Ask the assistant...' });
  ui.sendBtn = el('button', { class: 'primary', onclick: sendOrStop }, 'Send');
  ui.chips = el('div', { class: 'chips', hidden: '' });
  ui.pending = el('div', { class: 'pending', hidden: '' });
  ui.files = el('div', { class: 'files', hidden: '' });
  ui.fileInput = el('input', { type: 'file', multiple: '', hidden: '' });
  ui.attachBtn = el('button', { class: 'quiet', title: 'Attach files (or paste or drop them here)', hidden: '',
    onclick: () => ui.fileInput.click() }, 'Attach');
  ui.laterBtn = el('button', { class: 'quiet', title: 'Send at a set time', hidden: '',
    onclick: () => { ui.when.hidden = !ui.when.hidden; if (!ui.when.hidden) ui.whenInput.focus(); } }, 'Later');
  ui.whenInput = el('input', { type: 'datetime-local' });
  ui.when = el('div', { class: 'when', hidden: '' }, el('span', {}, 'Send at'), ui.whenInput,
    el('button', { class: 'primary', onclick: scheduleIt }, 'Schedule'),
    el('button', { onclick: () => { ui.when.hidden = true; } }, 'Cancel'));
  ui.grip = el('div', { class: 'grip', title: 'Drag to resize' });
  ui.panel = el('div', { class: 'panel', hidden: '' },
    ui.grip,
    ui.head = el('div', { class: 'head' }, ui.title, ui.newBtn, ui.consoleBtn, ui.closeBtn),
    el('div', { class: 'cfg' }, ui.profileLabel, ui.provider,
      el('label', {}, 'model', ui.model), el('label', {}, 'effort', ui.effort), el('label', {}, 'mode', ui.mode),
      ui.accountLabel, ui.layoutLabel, ui.alphaLabel),
    ui.limits, ui.status, ui.signin, ui.log, ui.chips, ui.pending, ui.files, ui.when,
    el('div', { class: 'composer' }, ui.attachBtn, ui.fileInput, ui.input, ui.laterBtn, ui.sendBtn));
  root.append(ui.css, ui.launcher, ui.panel);

  const feature = name => !!(api.info && api.info.features && api.info.features[name]);
  const busy = () => !!(api.info && api.info.busy);
  ui.input.addEventListener('keydown', e => {
    if (e.isComposing) return;
    // while the agent answers, Tab (or Enter) queues the message when the app allows it
    if (e.key === 'Tab' && !e.shiftKey && busy() && feature('queue') && ui.input.value.trim()) {
      e.preventDefault(); queueIt(); return;
    }
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      if (!busy()) sendOrStop();
      else if (feature('queue') && ui.input.value.trim()) queueIt();
    }
  });
  ui.input.addEventListener('paste', e => {
    const files = e.clipboardData && e.clipboardData.files;
    if (feature('attach') && files && files.length) { e.preventDefault(); for (const f of files) api.attach(f); }
  });
  ui.panel.addEventListener('dragover', e => { if (feature('attach')) e.preventDefault(); });
  ui.panel.addEventListener('drop', e => {
    if (!feature('attach') || !e.dataTransfer || !e.dataTransfer.files.length) return;
    e.preventDefault(); for (const f of e.dataTransfer.files) api.attach(f);
  });
  ui.fileInput.onchange = () => { for (const f of ui.fileInput.files) api.attach(f); ui.fileInput.value = ''; };
  ui.input.addEventListener('input', () => {
    ui.input.style.height = 'auto'; ui.input.style.height = Math.min(ui.input.scrollHeight, 160) + 'px';
  });
  ui.profile.onchange = () => post('settings', { profile: ui.profile.value });
  ui.provider.onchange = () => post('settings', { provider: ui.provider.value });
  ui.account.onchange = () => post('account', { id: ui.account.value });
  for (const role of ['model', 'effort', 'mode']) ui[role].onchange = () => post('settings', { [role]: ui[role].value });

  // resize from the left edge (side and docked)
  ui.grip.addEventListener('pointerdown', e => {
    e.preventDefault(); ui.grip.setPointerCapture(e.pointerId);
    const move = ev => setWidth(window.innerWidth - ev.clientX);
    const up = () => { ui.grip.removeEventListener('pointermove', move); ui.grip.removeEventListener('pointerup', up); remember('width', host.style.getPropertyValue('--aiify-width')); };
    ui.grip.addEventListener('pointermove', move); ui.grip.addEventListener('pointerup', up);
  });
  function setWidth(px) { host.style.setProperty('--aiify-width', Math.max(300, Math.min(px, window.innerWidth - 40)) + 'px'); dock(); }
  const savedWidth = remember('width'); if (savedWidth) host.style.setProperty('--aiify-width', savedWidth);

  // -- layout and opacity -------------------------------------------------------------------
  const inlineTarget = opts.layout === 'inline' && opts.target ? document.querySelector(opts.target) : null;
  let layout = 'overlay';
  const dockStyle = document.createElement('style');
  dockStyle.id = 'aiify-dock';

  // docked: the page itself moves aside, so nothing is covered
  function dock() {
    const on = layout === 'dock' && !ui.panel.hidden;
    if (on && !dockStyle.isConnected) document.head.append(dockStyle);
    dockStyle.textContent = on ? `html { margin-right: ${Math.round(ui.panel.getBoundingClientRect().width)}px !important; }` : '';
  }

  // the floating window: dragged by its title bar, resized from its corner, kept on screen
  function placeFloat() {
    const saved = remember('float') || {};
    const w = Math.min(saved.w || 400, window.innerWidth - 16), h = Math.min(saved.h || Math.min(600, window.innerHeight - 48), window.innerHeight - 16);
    const x = Math.max(8, Math.min(saved.x != null ? saved.x : window.innerWidth - w - 24, window.innerWidth - w - 8));
    const y = Math.max(8, Math.min(saved.y != null ? saved.y : 24, window.innerHeight - h - 8));
    Object.assign(ui.panel.style, { left: x + 'px', top: y + 'px', width: w + 'px', height: h + 'px' });
  }
  function saveFloat() {
    if (layout !== 'float' || ui.panel.hidden) return;
    const r = ui.panel.getBoundingClientRect();
    remember('float', { x: Math.round(r.left), y: Math.round(r.top), w: Math.round(r.width), h: Math.round(r.height) });
  }
  ui.head.addEventListener('pointerdown', e => {
    if (layout !== 'float' || e.button !== 0 || e.target.closest('button, select, input')) return;
    e.preventDefault(); ui.head.setPointerCapture(e.pointerId);
    const r = ui.panel.getBoundingClientRect(), dx = e.clientX - r.left, dy = e.clientY - r.top;
    const move = ev => {
      ui.panel.style.left = Math.max(0, Math.min(ev.clientX - dx, window.innerWidth - 60)) + 'px';
      ui.panel.style.top = Math.max(0, Math.min(ev.clientY - dy, window.innerHeight - 40)) + 'px';
    };
    const up = () => { ui.head.removeEventListener('pointermove', move); ui.head.removeEventListener('pointerup', up); saveFloat(); };
    ui.head.addEventListener('pointermove', move); ui.head.addEventListener('pointerup', up);
  });
  ui.panel.addEventListener('pointerup', saveFloat);              // after a corner resize
  window.addEventListener('resize', () => { if (layout === 'float' && !ui.panel.hidden) placeFloat(); dock(); });

  api.setLayout = name => {
    if (inlineTarget) name = 'inline';
    else if (!LAYOUTS[name]) name = 'overlay';
    layout = name;
    host.setAttribute('data-layout', name);
    ui.layout.value = name in LAYOUTS ? name : 'overlay';
    for (const k of ['left', 'top', 'width', 'height']) ui.panel.style[k] = '';
    if (name === 'float' && !ui.panel.hidden) placeFloat();
    if (!inlineTarget) remember('layout', name);
    dock();
  };
  api.setOpacity = pct => {
    pct = Math.max(30, Math.min(100, Math.round(Number(pct) || 100)));
    host.style.setProperty('--aiify-alpha', String(pct / 100));
    ui.alpha.value = String(pct);
    remember('opacity', pct);
  };
  ui.layout.onchange = () => api.setLayout(ui.layout.value);
  ui.alpha.oninput = () => api.setOpacity(ui.alpha.value);
  ui.layoutLabel.style.display = inlineTarget ? 'none' : '';
  ui.alphaLabel.style.display = inlineTarget ? 'none' : '';

  api.open = () => {
    ui.panel.hidden = false; ui.launcher.hidden = true; remember('open', true);
    if (layout === 'float') placeFloat();
    dock(); setTimeout(() => ui.input.focus(), 0); fire('open', {});
  };
  api.close = () => {
    if (inlineTarget) return;
    saveFloat(); ui.panel.hidden = true; ui.launcher.hidden = noLauncher; remember('open', false); dock(); fire('close', {});
  };
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
  const readFile = file => new Promise((ok, fail) => {
    const r = new FileReader(); r.onload = () => ok(r.result); r.onerror = () => fail(r.error); r.readAsDataURL(file);
  });
  async function attachment(item) {
    if (typeof Blob !== 'undefined' && item instanceof Blob) return { name: item.name || 'pasted', data_url: await readFile(item) };
    return { name: item.name || 'attachment', text: item.text, data_url: item.dataUrl || item.data_url };
  }
  api.attach = async item => post('attach', await attachment(item));
  api.launch = async (name, data, attach) => {
    api.open();
    const files = await Promise.all((attach || []).map(attachment));
    return post('launch', { name, data: data === undefined ? null : data, attach: files });
  };
  document.addEventListener('click', e => {
    const b = e.target.closest && e.target.closest('[data-aiify-launch]');
    if (!b) return;
    let data = null;
    try { data = b.dataset.aiifyData ? JSON.parse(b.dataset.aiifyData) : null; }
    catch (err) { console.error('ai-ify: data-aiify-data is not JSON', err); }
    e.preventDefault();
    api.launch(b.dataset.aiifyLaunch, data);
  });
  function takeInput() {
    const text = ui.input.value.trim();
    if (text) { ui.input.value = ''; ui.input.style.height = 'auto'; }
    return text;
  }
  function sendOrStop() {
    if (busy()) { post('cancel'); return; }
    const text = takeInput(); if (text) api.send(text);
  }
  function queueIt() { const text = takeInput(); if (text) post('queue', { text }); }
  async function scheduleIt() {
    const text = ui.input.value.trim(), when = ui.whenInput.value;
    if (!text || !when) { ui.input.focus(); return; }
    const r = await post('schedule', { text, at: new Date(when).toISOString() });
    if (r.ok) { takeInput(); ui.when.hidden = true; }
  }
  async function openConsole() {
    const r = await post('console');
    if (r.ok) line('sys', 'Opened in a terminal.');
  }

  // -- rendering --------------------------------------------------------------------------
  let current = null, currentText = '', thought = null, tools = {}, perms = {}, hadMessages = false;

  function esc(s) { return String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])); }
  function inline(s) {
    return s.replace(/`([^`]+)`/g, '<code>$1</code>')
      .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
      .replace(/(^|[^*])\*([^*\s][^*]*)\*/g, '$1<em>$2</em>')
      .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
  }
  // Small, safe markdown: everything is escaped first, then a few patterns become tags.
  function isRow(s) { return /^\s*\|.*\|\s*$/.test(s); }
  function cells(s) { return s.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map(c => c.trim()); }
  function markdown(src) {
    const out = [], parts = String(src).split(/```/);
    parts.forEach((part, i) => {
      if (i % 2) { out.push('<pre><code>' + esc(part.replace(/^[\w-]*\n/, '')) + '</code></pre>'); return; }
      let list = null;
      const lines = esc(part).split('\n');
      for (let n = 0; n < lines.length; n++) {
        const raw = lines[n];
        if (isRow(raw) && n + 1 < lines.length && /^\s*\|?[\s:|-]*-[\s:|-]*\|?\s*$/.test(lines[n + 1])) {
          if (list) { out.push(`</${list}>`); list = null; }
          const rows = [cells(raw)];            // a Markdown table: header, rule, rows
          for (n += 2; n < lines.length && isRow(lines[n]); n++) rows.push(cells(lines[n]));
          n--;
          out.push('<table><thead><tr>' + rows[0].map(c => '<th>' + inline(c) + '</th>').join('') + '</tr></thead><tbody>' +
            rows.slice(1).map(r => '<tr>' + r.map(c => '<td>' + inline(c) + '</td>').join('') + '</tr>').join('') +
            '</tbody></table>');
          continue;
        }
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
  function resetLog() { ui.log.innerHTML = ''; current = null; currentText = ''; thought = null; tools = {}; perms = {}; showEmpty(); }

  function render(ev) {
    switch (ev.kind) {
      case 'reset': resetLog(); break;
      case 'user': line('user', ev.text); break;
      case 'text':
        clearEmpty();
        if (!current) { current = el('div', { class: 'msg reply' }); currentText = ''; ui.log.append(current); }
        currentText += ev.text; current.innerHTML = markdown(currentText); scroll(); break;
      case 'thought':                // streamed a few words at a time: one block per run
        if (!thought || ui.log.lastElementChild !== thought) thought = line('thought', '');
        thought.textContent += ev.text || ''; scroll(); break;
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
      case 'launch': line('sys', 'Started from: ' + ev.label); break;
      case 'unqueued':                                  // Stop hands queued messages back
        ui.input.value = [...(ev.texts || []), ui.input.value.trim()].filter(Boolean).join('\n\n');
        ui.input.dispatchEvent(new Event('input')); break;
      case 'ready': ui.status.textContent = `ready · started in ${ev.startup}s`; break;
      case 'error': line('err', ev.text); break;
      case 'done': {
        current = null;
        if (ev.by_app) break;                             // answered by the app itself, no timings
        const parts = [];
        if (ev.stop && ev.stop !== 'end_turn')
          parts.push(ev.stop === 'cancelled' ? 'stopped' : ev.stop === 'auth_required' ? 'not sent: sign in first' : ev.stop);
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

  // Shown while the agent is signed out. The message that met "sign in first" is
  // resent by the app once signing in finishes. Redrawn only when it changes, so a
  // half-typed code survives the frequent info updates.
  const SUBSCRIPTION = { claude: 'Claude', codex: 'ChatGPT' };
  let signinShown = '';
  function showSignin(info) {
    const s = info.signin;
    const key = JSON.stringify(s);
    if (key === signinShown) return;
    signinShown = key;
    ui.signin.hidden = !s;
    ui.signin.innerHTML = '';
    if (!s) return;
    const plan = SUBSCRIPTION[s.provider] || s.provider;
    ui.signin.append(el('strong', {}, `Sign in to ${plan}`));
    const row = el('div', { class: 'opts' });
    if (s.waiting) {
      ui.signin.append(el('div', {}, 'Your browser opened a sign-in page. Finish signing in there; the chat carries on by itself.'));
      if (s.link) ui.signin.append(el('div', {}, "Can't see it? ",
        el('a', { href: s.link, target: '_blank', rel: 'noopener' }, 'Open the sign-in page')));
      if (s.code) {
        const box = el('input', { type: 'text', placeholder: 'Paste the code here', autocomplete: 'off' });
        const send = () => { if (box.value.trim()) post('signin', { code: box.value.trim() }); };
        box.addEventListener('keydown', e => { if (e.key === 'Enter') send(); });
        ui.signin.append(el('div', { class: 'wait' }, 'If the page shows a code instead, paste it here:'),
          el('div', { class: 'code' }, box, el('button', { class: 'primary', onclick: send }, 'Continue')));
      }
      row.append(el('button', { onclick: () => post('signin', { method: s.waiting }) }, 'Start again'));
    } else if (!(s.methods || []).length) {
      ui.signin.append(el('div', {}, 'This agent offers no subscription sign-in here; sign in with its own command, then press New chat.'));
    } else {
      ui.signin.append(el('div', {}, `The assistant uses your own ${plan} subscription. Sign in once on this computer; ` +
        'nothing is charged per message.'));
      for (const m of s.methods) row.append(el('button', { class: 'primary', title: m.description || '',
        onclick: () => post('signin', { method: m.id }) }, s.methods.length > 1 ? 'Sign in: ' + m.name : 'Sign in'));
    }
    ui.signin.append(row);
  }

  // suggested prompts (empty chat), queued / scheduled messages, attachments
  function showExtras(info) {
    const f = info.features || {};
    ui.attachBtn.hidden = !f.attach;
    ui.laterBtn.hidden = !f.schedule;
    if (!f.schedule) ui.when.hidden = true;
    ui.input.placeholder = info.busy && f.queue ? 'Press Tab to send this after the reply' : 'Ask the assistant...';
    const chips = info.suggestions || [];
    ui.chips.innerHTML = ''; ui.chips.hidden = !chips.length;
    for (const c of chips) ui.chips.append(el('button', { title: c.text, onclick: () => api.send(c.text) }, c.label));
    const pending = info.pending || [];
    ui.pending.innerHTML = ''; ui.pending.hidden = !pending.length;
    for (const m of pending) ui.pending.append(el('div', { class: 'item' },
      el('span', { class: 'at' }, m.at ? 'at ' + clock(m.at) : 'after this reply'),
      el('span', { class: 'text', title: m.text }, m.text),
      el('button', { class: 'quiet', title: 'Remove', onclick: () => post('unqueue', { id: m.id }) }, '✕')));
    const files = info.attachments || [];
    ui.files.innerHTML = ''; ui.files.hidden = !files.length;
    for (const a of files) ui.files.append(el('span', { class: 'file', title: a.name },
      el('span', {}, a.name),
      el('button', { class: 'quiet', title: 'Remove', onclick: () => post('detach', { id: a.id }) }, '✕')));
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
    const locked = info.locked || [];
    if (locked.includes('profile')) ui.profileLabel.style.display = 'none';
    ui.provider.style.display = locked.includes('provider') ? 'none' : '';
    for (const role of ['model', 'effort', 'mode']) if (locked.includes(role)) ui[role].parentElement.style.display = 'none';
    showLimits(info);
    showSignin(info);
    showExtras(info);
    ui.sendBtn.textContent = info.busy ? 'Stop' : 'Send';
    ui.sendBtn.className = info.busy ? '' : 'primary';
    ui.launcher.classList.toggle('busy', !!info.busy);
    ui.consoleBtn.disabled = !(info.console && info.console.available);
    ui.consoleBtn.title = info.console && info.console.available ? 'Open this conversation in a terminal'
      : 'Console: ' + ((info.console && info.console.reason) || 'not available');
    if (info.signin) ui.status.textContent = 'signed out';
    else if (!info.ready && !info.busy) ui.status.textContent = 'starting the assistant...';
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
        ui.status.textContent = ev.info.signin ? 'signed out' : ev.info.busy ? 'working...' : ev.info.ready ? 'ready' : 'starting the assistant...';
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
    if (opts.font !== 'system') {
      const face = opts.font || getComputedStyle(document.body).fontFamily;
      if (face) host.style.setProperty('--aiify-font', face);
    }
    (inlineTarget || document.body).append(host);
    resetLog();
    api.setLayout(remember('layout') || opts.layout || 'overlay');
    api.setOpacity(remember('opacity') || opts.opacity || 100);
    if (noLauncher) ui.launcher.hidden = true;
    if (inlineTarget) { ui.closeBtn.hidden = true; api.open(); }
    else if (opts.open === 'true' || remember('open')) api.open();
    connect();
  }
  if (document.body) boot(); else document.addEventListener('DOMContentLoaded', boot);
})();
