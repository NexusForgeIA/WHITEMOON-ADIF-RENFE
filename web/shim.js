/* RailGuard · modo demostración estática.
 * Sustituye al servidor: intercepta las llamadas /api/* del panel y de la app de cabina y las responde con la
 * reproducción de una ejecución REAL del motor grabada con web/record.py. No hay datos en vivo. */
(function () {
  'use strict';
  const Q = new URLSearchParams(location.search);
  const CENTRES = ['madrid', 'barcelona', 'sevilla'];
  const D = window.RG_DEMO = {
    view: Q.get('v') || 'nacional', sid: Q.get('s') || 'base', train: Q.get('train') || null,
    t0: Date.now(), acks: {}, tabAcks: {}, msgs: []
  };
  D.centre = CENTRES.includes(D.view) ? D.view : null;
  try { localStorage.setItem('rg_who', 'Demo'); localStorage.setItem('rg_ctok', 'demo'); } catch (e) {}
  const orig = window.fetch.bind(window);
  let recP = null;
  const rec = () => recP || (recP = orig(new URL('rec/' + D.sid + '.json', document.baseURI)).then(r => r.json()));
  const json = (o, code) => new Response(JSON.stringify(o), { status: code || 200, headers: { 'Content-Type': 'application/json' } });

  function pos(R) {
    const n = R.frames.length;
    let f = (Date.now() - D.t0) / (R.step_s * 1000);
    if (D.sid === 'base') f = f % (n - 1); else f = Math.min(f, n - 1);
    const i = Math.min(Math.floor(f), n - 1);
    return { i, frac: i >= n - 1 ? 0 : f - i, n, done: D.sid !== 'base' && f >= n - 1, sec: Math.round(Math.min(f, n - 1) * R.step_s) };
  }
  const lerp = (ta, tb, k) => {
    if (!k || !tb) return ta;
    const m = {}; tb.forEach(t => { m[t.n] = t; });
    return ta.map(t => { const u = m[t.n]; return u ? Object.assign({}, t, { x: t.x + (u.x - t.x) * k, y: t.y + (u.y - t.y) * k }) : t; });
  };

  function build(R, P, view) {
    const F = R.frames, a = F[P.i], b = F[Math.min(P.i + 1, F.length - 1)];
    const shift = D.t0 - F[0].t, v = a[view], st = R.static[view], nat = a.nacional;
    const s = Object.assign({}, v);
    const all = lerp(nat.trains, b.nacional.trains, P.frac);
    if (view === 'nacional') s.trains = all;
    else {
      const by = {}; all.forEach(t => { by[t.n] = t; });
      const inc = new Set(v.inc);
      s.trains = v.tr.filter(n => by[n]).map(n => Object.assign({}, by[n], { incoming: inc.has(n) }));
      s.barriers = nat.barriers; s.centres = nat.centres;
      const keep = new Set(st.stations.map(x => x.c));
      s.segments = nat.segments.filter(p => keep.has(p[0]) && keep.has(p[1]));
    }
    s.stations = st.stations; s.corridors = st.corridors; s.drivers = [];
    s.scenarios = R.static.nacional.scenarios.map(x => Object.assign({}, x, { active: x.id === D.sid }));
    s.operators = R.static.nacional.operators.map(o => Object.assign({}, o, { trains: v.op_counts[o.id] || 0 }));
    s.events = v.ev.map(i => Object.assign({}, R.events[i], { t: R.events[i].t + shift }));
    const msgs = (v.messages || []).map(m => Object.assign({}, m, { t: m.t + shift }));
    const mine = D.msgs.filter(m => view === 'nacional' || m.to === view || m.to === '*' || m.from === view);
    s.messages = mine.concat(msgs).slice(0, 30);
    s.operator = (v.operator || []).map(it => D.acks[it.key] ? Object.assign({}, it, { ack: true }) : it);
    s.now = Date.now();
    return s;
  }

  function tablet(R, P, opts) {
    const h = (opts && opts.headers) || {};
    const train = String(h['X-Driver-Token'] || '').replace(/^demo-/, '') || D.train || 'T-9009';
    const F = R.frames[P.i], st = F.tablets && F.tablets[train], shift = D.t0 - R.frames[0].t;
    if (!st) return { ok: true, now: Date.now(), driver: 'demo-' + train, train, operator: 'Operador demo (ficticio)', speed_kmh: null,
                      pos_src: 'feed', feed_degraded: false, warn: null, alerts: [], near: [], threshold_km: 3 };
    const o = JSON.parse(JSON.stringify(st)); o.now = Date.now();
    (o.alerts || []).forEach(x => { if (D.tabAcks[x.key]) x.acked = true; if (x.since) x.since += shift; });
    return o;
  }

  function go(extra) { const q = new URLSearchParams(location.search); Object.keys(extra).forEach(k => q.set(k, extra[k])); location.search = q.toString(); }
  D.go = go;
  D.restart = () => { D.t0 = Date.now(); };

  async function handle(u, opts) {
    const path = u.split('?')[0].replace(/^.*?(\/api\/)/, '/api/');
    let body = {}; try { body = opts.body ? JSON.parse(opts.body) : {}; } catch (e) {}
    const R = await rec(), P = pos(R);
    D.last = P;
    if (path === '/api/snapshot') return json(build(R, P, 'nacional'));
    if (path === '/api/centre/snapshot') return json(build(R, P, D.centre || 'nacional'));
    if (path === '/api/tablet/pos') return json(tablet(R, P, opts));
    if (path === '/api/tablet/ack') { D.tabAcks[body.key] = true; return json({ ok: true }); }
    if (path === '/api/scenario') { setTimeout(() => go({ s: body.on ? body.id : 'base' }), 50); return json({ ok: true }); }
    if (path === '/api/reset') { setTimeout(() => go({ s: 'base' }), 50); return json({ ok: true }); }
    if (/\/ack$/.test(path)) { D.acks[body.key] = true; return json({ ok: true, msg: 'Reconocido (demo)' }); }
    if (/\/message$/.test(path)) {
      D.msgs.unshift({ t: Date.now(), from: D.centre || 'nacional', to: body.to, text: String(body.text || '').slice(0, 300) });
      return json({ ok: true, msg: 'enviado (demo)' });
    }
    return json({ ok: false, msg: 'Demostración grabada: esta acción actúa sobre el motor real y aquí no está activa. ' +
      'Ejecute `python3 server.py` (repositorio WHITEMOON-ADIF-RENFE) para probarla en vivo.' });
  }
  window.fetch = function (url, opts) {
    const u = String(url && url.url ? url.url : url);
    return u.indexOf('/api/') < 0 ? orig(url, opts) : handle(u, opts || {});
  };

  document.addEventListener('DOMContentLoaded', () => {
    const $ = id => document.getElementById(id);
    if ($('dv')) { $('dv').value = D.view; $('dv').onchange = () => go({ v: $('dv').value }); }
    if ($('dtab')) $('dtab').href = 'tablet.html?s=' + encodeURIComponent(D.sid === 'base' ? 'convoy_3km' : D.sid);
    if ($('drs')) $('drs').onclick = () => D.restart();
    if ($('dback')) $('dback').href = 'index.html?s=' + encodeURIComponent(D.sid);
    if ($('dsc')) { $('dsc').value = D.sid; $('dsc').onchange = () => go({ s: $('dsc').value, train: '' }); }
    if ($('dtr')) {
      const sets = { convoy_3km: ['T-9009', 'T-9010'], seguimiento: ['T-9003', 'T-9004'], via_unica: ['T-9005', 'T-9006'] }[D.sid] || ['T-9009'];
      $('dtr').replaceChildren(...sets.map(t => { const o = document.createElement('option'); o.value = o.textContent = t; return o; }));
      if (D.train && sets.includes(D.train)) $('dtr').value = D.train;
      const fill = () => { D.train = $('dtr').value; if ($('tok')) $('tok').value = 'demo-' + D.train; };
      $('dtr').onchange = fill; fill();
      if ($('demo')) $('demo').checked = true;
    }
    setInterval(() => {
      const el = $('dprog'); if (!el || !D.last) return;
      const total = (D.last.n - 1) * 2;
      el.textContent = D.sid === 'base' ? '↻ red en calma' : (D.last.done ? '■ fin de la grabación' : '▶ ' + D.last.sec + ' / ' + total + ' s');
    }, 500);
  });
})();
