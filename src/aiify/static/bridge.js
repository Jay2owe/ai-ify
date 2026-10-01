/* ai-ify page bridge: runs the agent's on-screen operations in this page.
 *
 * panel.js loads this file (unless <script ... data-bridge="false">) and shares
 * its websocket. Host pages use:
 *   window.aiify.registerTool({name, description, inputSchema, execute})  // named UI command
 *   window.aiify.setState(() => ({view: 'plots', selected: [...]}))       // what is on screen
 *   <button data-agent="export-button">   names a control (a stable ref)
 *   <div data-agent="off">                the agent never sees or touches this region
 *
 * The control tree comes from Alibaba's page-controller (MIT, vendor/page-controller.js).
 */
(function () {
  'use strict';
  const api = window.aiify = window.aiify || {};
  if (api.bridge) return;
  api.bridge = true;
  const prefix = api.prefix || '/aiify';
  const tools = new Map();
  let stateFn = null;

  // -- registration (panel.js queues calls made before this file loaded) ----------------
  api.registerTool = function (tool) {
    if (!tool || typeof tool.name !== 'string' || typeof tool.execute !== 'function')
      throw new Error('registerTool needs {name, execute}');
    tools.set(tool.name, tool);
    try {
      const mc = navigator.modelContext;
      if (mc && typeof mc.registerTool === 'function') mc.registerTool(tool);
    } catch (e) { /* the browser's own registry is optional */ }
    announce('bridge.tools');
    return () => { tools.delete(tool.name); announce('bridge.tools'); };
  };
  api.unregisterTool = name => { tools.delete(name); announce('bridge.tools'); };
  api.setState = fn => { stateFn = typeof fn === 'function' ? fn : () => fn; };
  for (const t of api._pendingTools || []) api.registerTool(t);
  if (api._pendingState) api.setState(api._pendingState);
  delete api._pendingTools; delete api._pendingState;

  function toolList() {
    return [...tools.values()].map(t => ({ name: t.name, description: t.description || '', inputSchema: t.inputSchema || null }));
  }
  function announce(type) {
    if (api.post) api.post(type, { tools: toolList(), url: location.href, title: document.title });
  }

  // -- change tracking: numbered refs go stale after any change ---------------------------
  const OURS = new Set(['aiify-root', 'aiify-flash', 'playwright-highlight-container']);
  let mutations = 0, changeTimer = null;
  function ours(node) {
    for (let n = node; n; n = n.parentNode) if (n.id && OURS.has(n.id)) return true;
    return false;
  }
  const observer = new MutationObserver(records => {
    let real = false;
    for (const r of records) {
      if (ours(r.target)) continue;
      const nodes = [...r.addedNodes, ...r.removedNodes];
      if (nodes.length && nodes.every(ours)) continue;
      real = true; break;
    }
    if (!real) return;
    mutations++;
    clearTimeout(changeTimer);
    changeTimer = setTimeout(() => api.post && api.post('bridge.changed', {}), 300);
  });
  function observe() {
    observer.observe(document.body, { subtree: true, childList: true, attributes: true, characterData: true });
  }

  // -- the control tree -------------------------------------------------------------------
  let lib = null, controller = null, snapshot = 0, snapMutations = -1, numbered = new Map();

  async function load() {
    if (!lib) {
      lib = await import(prefix + '/vendor/page-controller.js');
      controller = new lib.PageController({
        viewportExpansion: -1, highlightOpacity: 0, highlightLabelOpacity: 0,
        interactiveBlacklist: [() => document.getElementById('aiify-root')],
      });
    }
    return lib;
  }

  function off(el) {
    for (let n = el; n; n = n.parentElement || (n.getRootNode && n.getRootNode().host) || null)
      if (n.nodeType === 1 && n.getAttribute('data-agent') === 'off') return true;
    return false;
  }
  function visible(el) {
    if (!el.isConnected) return false;
    const r = el.getBoundingClientRect(), s = getComputedStyle(el);
    return (r.width > 0 || r.height > 0) && s.visibility !== 'hidden' && s.display !== 'none';
  }
  const ROLES = { A: 'link', BUTTON: 'button', SELECT: 'combobox', TEXTAREA: 'textbox', SUMMARY: 'button',
    OPTION: 'option', DETAILS: 'group', LABEL: 'label' };
  function role(el) {
    const explicit = el.getAttribute('role'); if (explicit) return explicit;
    if (el.tagName === 'INPUT') {
      const t = (el.type || 'text').toLowerCase();
      return { checkbox: 'checkbox', radio: 'radio', range: 'slider', button: 'button', submit: 'button',
        reset: 'button', number: 'spinbutton', search: 'searchbox', file: 'file' }[t] || 'textbox';
    }
    if (el.isContentEditable) return 'textbox';
    return ROLES[el.tagName] || el.tagName.toLowerCase();
  }
  function clip(s, n) { s = String(s || '').replace(/\s+/g, ' ').trim(); return s.length > n ? s.slice(0, n - 1) + '…' : s; }
  function label(el) {
    const by = el.getAttribute('aria-labelledby');
    const labelled = by && by.split(/\s+/).map(id => document.getElementById(id)).filter(Boolean).map(e => e.innerText).join(' ');
    return clip(el.getAttribute('aria-label') || labelled || (el.labels && el.labels[0] && labelText(el.labels[0]))
      || el.getAttribute('placeholder') || el.getAttribute('title') || el.getAttribute('alt')
      || (el.tagName === 'SELECT' ? '' : el.innerText) || el.getAttribute('name') || el.value || '', 80);
  }
  // a <label>'s own words, without the text of the control inside it (a select's options)
  function labelText(lbl) {
    const copy = lbl.cloneNode(true);
    copy.querySelectorAll('select, input, textarea, button').forEach(c => c.remove());
    return copy.textContent;
  }
  function value(el) {
    if (el.tagName === 'SELECT') return el.selectedOptions[0] ? el.selectedOptions[0].text : '';
    if (el.type === 'checkbox' || el.type === 'radio') return el.checked;
    if ('value' in el && el.tagName !== 'BUTTON' && el.tagName !== 'LI') return el.value;
    if (el.isContentEditable) return clip(el.innerText, 200);
    return undefined;
  }
  function entry(ref, el) {
    const row = { ref, role: role(el), label: label(el) };
    const v = value(el); if (v !== undefined && v !== '') row.value = v;
    if (el.tagName === 'SELECT') row.options = [...el.options].map(o => o.text).slice(0, 30);
    if (el.disabled) row.disabled = true;
    return row;
  }

  async function tree({ match } = {}) {
    await load();
    await controller.updateTree();
    if (window._highlightCleanupFunctions) {             // page-controller draws (invisible) boxes; remove them
      for (const f of window._highlightCleanupFunctions) try { f(); } catch (e) { /* gone already */ }
      window._highlightCleanupFunctions = [];
    }
    snapshot++; snapMutations = mutations; numbered = new Map();
    const rows = [], seen = new Set();
    for (const el of document.querySelectorAll('[data-agent]')) {
      const name = el.getAttribute('data-agent');
      if (name === 'off' || off(el) || !visible(el) || seen.has(el)) continue;
      seen.add(el); rows.push(entry(name, el));
    }
    let n = 0;
    for (const node of controller.selectorMap.values()) {
      const el = node.ref;
      if (!el || seen.has(el) || off(el) || !visible(el)) continue;
      if (el.tagName === 'LABEL' && el.control) continue;          // its control is listed instead
      seen.add(el); n++;
      numbered.set('e' + n, el); rows.push(entry('e' + n, el));
    }
    const q = (match || '').toLowerCase();
    const elements = q ? rows.filter(r => (r.ref + ' ' + r.role + ' ' + r.label).toLowerCase().includes(q)) : rows;
    return { snapshot, elements };
  }

  class OpError extends Error { constructor(code, message) { super(message); this.code = code; } }

  function resolve(target) {
    if (typeof target !== 'string' || !target) throw new OpError('invalid', 'target must be a ref from ui.tree');
    if (/^e\d+$/.test(target)) {
      if (!numbered.has(target)) throw new OpError('stale_ref', `${target} is not in the latest ui.tree; ask for a new tree`);
      if (mutations !== snapMutations) throw new OpError('stale_ref', `the page changed since ui.tree; ${target} may point elsewhere now - ask for a new tree`);
      const el = numbered.get(target);
      if (!el.isConnected) throw new OpError('stale_ref', `${target} is no longer on the page`);
      return el;
    }
    const named = [...document.querySelectorAll('[data-agent]')].find(e => e.getAttribute('data-agent') === target);
    if (!named || target === 'off') throw new OpError('not_found', `no control named ${target}; see ui.tree`);
    if (off(named)) throw new OpError('denied', `${target} is in a region the agent may not touch`);
    return named;
  }
  function guard(el, ref) {
    if (off(el)) throw new OpError('denied', `${ref} is in a region the agent may not touch`);
    if (el.disabled) throw new OpError('failed', `${ref} is disabled`);
  }

  // brief outline over whatever the agent touched
  function flash(el) {
    const r = el.getBoundingClientRect();
    let box = document.getElementById('aiify-flash');
    if (!box) {
      box = document.createElement('div'); box.id = 'aiify-flash';
      box.style.cssText = 'position:fixed;pointer-events:none;z-index:2147482999;border:2px solid #f59f00;' +
        'border-radius:4px;box-shadow:0 0 0 4px rgba(245,159,0,.25);transition:opacity .6s;';
      document.body.appendChild(box);
    }
    Object.assign(box.style, { left: (r.left - 3) + 'px', top: (r.top - 3) + 'px',
      width: (r.width + 6) + 'px', height: (r.height + 6) + 'px', opacity: '1' });
    clearTimeout(box._t); box._t = setTimeout(() => { box.style.opacity = '0'; }, 1200);
  }

  async function settle() { await new Promise(r => setTimeout(r, 150)); }

  const OPS = {
    'ui.tree': tree,
    async 'ui.click'({ target }) {
      await load(); const el = resolve(target); guard(el, target);
      await lib.scrollIntoViewIfNeeded(el); flash(el); await lib.clickElement(el);
      return { clicked: target };
    },
    async 'ui.fill'({ target, value: v }) {
      await load(); const el = resolve(target); guard(el, target);
      if (v == null) throw new OpError('invalid', 'ui.fill needs a value');
      if (el.type === 'checkbox' || el.type === 'radio') {
        const want = v === true || /^(true|on|yes|1)$/i.test(String(v));
        if (el.checked !== want) { flash(el); await lib.clickElement(el); }
        return { filled: target, value: el.checked };
      }
      await lib.scrollIntoViewIfNeeded(el); flash(el);
      if (el.tagName === 'SELECT') return OPS['ui.select']({ target, value: v });
      await lib.inputTextElement(el, String(v));
      return { filled: target, value: value(el) };
    },
    async 'ui.select'({ target, value: v }) {
      await load(); const el = resolve(target); guard(el, target);
      if (el.tagName !== 'SELECT') throw new OpError('invalid', `${target} is not a list; use ui.click or ui.fill`);
      const want = String(v);
      const opt = [...el.options].find(o => o.text.trim() === want || o.value === want)
        || [...el.options].find(o => o.text.trim().toLowerCase() === want.toLowerCase());
      if (!opt) throw new OpError('not_found', `${target} has no option ${want}; options: ${[...el.options].map(o => o.text).join(', ')}`);
      flash(el); el.value = opt.value;
      el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true }));
      return { selected: target, value: opt.text };
    },
    async 'ui.scroll'({ target, direction }) {
      await load();
      const el = target ? resolve(target) : null;
      if (el) guard(el, target);
      const amount = (direction === 'up' ? -1 : 1) * Math.round(window.innerHeight * 0.8);
      const msg = await lib.scrollVertically(amount, el);
      return { scrolled: target || 'page', direction: direction === 'up' ? 'up' : 'down', note: msg };
    },
    async 'ui.read'({ target }) {
      const el = resolve(target); guard(el, target); flash(el);
      return Object.assign(entry(target, el), { text: clip(el.innerText || el.textContent, 4000) });
    },
    async 'ui.do'({ name, params }) {
      const tool = tools.get(name);
      if (!tool) throw new OpError('not_found', `no UI command ${name}; available: ${[...tools.keys()].join(', ') || 'none'}`);
      params = params || {};
      const schema = tool.inputSchema || {};
      for (const key of schema.required || []) if (!(key in params)) throw new OpError('invalid', `${name} needs ${key}`);
      for (const [key, spec] of Object.entries(schema.properties || {}))
        if (key in params && spec && Array.isArray(spec.enum) && !spec.enum.includes(params[key]))
          throw new OpError('invalid', `${key} must be one of ${spec.enum.join(', ')}`);
      const result = await tool.execute(params);
      return result === undefined ? { done: name } : result;
    },
    async 'ui.state'() {
      if (!stateFn) return { page: location.pathname, title: document.title };
      return await stateFn();
    },
  };
  const READ_ONLY = new Set(['ui.tree', 'ui.read', 'ui.state']);

  async function run(req) {
    const op = OPS[req.op];
    const before = mutations;
    if (!op) return { ok: false, code: 'unknown_op', error: `the page cannot do ${req.op}` };
    try {
      const result = await op(req);
      if (!READ_ONLY.has(req.op)) await settle();
      const reply = { ok: true, result };
      if (!READ_ONLY.has(req.op) && mutations !== before) reply.screen_changed = true;
      return reply;
    } catch (e) {
      return { ok: false, code: e.code || 'failed', error: e.message || String(e) };
    }
  }

  function start() {
    observe();
    if (api.on) {
      api.on('ui.request', async ev => {
        const reply = await run(ev);
        api.post('ui.reply', Object.assign({ id: ev.id }, reply));
      });
      api.on('hello', () => announce('bridge.hello'));
    }
    announce('bridge.hello');
  }
  api._bridgeRun = run;                                   // for tests
  if (document.body) start(); else document.addEventListener('DOMContentLoaded', start);
})();
