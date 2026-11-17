// Page driver. In render mode the Python side calls window.renderView();
// with ?preview the map is interactive for checking the symbology.
/* global maplibregl, buildStyle, drawSymbol */
'use strict';

(async function () {
  const q = new URLSearchParams(location.search);
  const preview = q.has('preview');
  const cfg = await (await fetch('/config.json')).json();
  if (q.get('scheme') && cfg.palettes) { cfg.scheme = q.get('scheme'); cfg.palette = cfg.palettes[cfg.scheme]; }
  const ratio = preview ? window.devicePixelRatio : (cfg.pixelRatio || window.devicePixelRatio);
  if (preview) document.body.classList.add('preview');

  const b = cfg.bounds || [-180, -80, 180, 80];
  const map = new maplibregl.Map({
    container: 'map',
    style: buildStyle(cfg),
    center: [(b[0] + b[2]) / 2, (b[1] + b[3]) / 2],
    zoom: 8,
    interactive: preview,
    attributionControl: false,
    pixelRatio: ratio,
    fadeDuration: 0,
    renderWorldCopies: false,
    maxTileCacheSize: 400,
    maxCanvasSize: [8192, 8192],   // default 4096 would clip big render blocks at pixelRatio 2
    localIdeographFontFamily: false,
    canvasContextAttributes: {antialias: true, preserveDrawingBuffer: true},
  });
  window.map = map;
  map.on('styleimagemissing', e => {
    if (map.hasImage(e.id)) return;
    let img = null;
    try { img = drawSymbol(e.id, cfg.palette, ratio); } catch (err) { console.error(e.id, err); }
    if (img) map.addImage(e.id, img, {pixelRatio: ratio});
    else map.addImage(e.id, {width: 1, height: 1, data: new Uint8Array(4)});
  });
  // Tile/source load errors are retried by MapLibre and must not abort the
  // render; only style-level errors are fatal.
  window.softErrors = [];
  map.on('error', e => {
    const msg = String(e && e.error && e.error.message || e);
    if (e && (e.sourceId || e.tile)) { window.softErrors.push(msg); console.warn('tile error: ' + msg); }
    else window.lastError = msg;
  });

  if (preview) {
    map.addControl(new maplibregl.NavigationControl(), 'top-right');
    if (b) map.fitBounds([[b[0], b[1]], [b[2], b[3]]], {duration: 0});
    const info = document.getElementById('info');
    const scaleAt = z => Math.round(591657527.591555 * Math.cos(map.getCenter().lat * Math.PI / 180) / Math.pow(2, z) / 1000) * 1000;
    const upd = () => {
      const z = map.getZoom() + 1;
      info.textContent = `Zoom level ${z.toFixed(1)} (about 1:${scaleAt(z).toLocaleString('en-US')})`;
    };
    map.on('move', upd); upd();
    map.on('click', e => {
      if (document.body.classList.contains('drawing')) return;
      const f = map.queryRenderedFeatures(e.point).filter(x => x.properties && x.properties.OBJL);
      if (f.length) info.textContent = f.slice(0, 3).map(x => `${x.properties.OBJL}${x.properties.OBJNAM ? ' ' + x.properties.OBJNAM : ''}`).join(' | ');
    });
    for (const btn of document.querySelectorAll('.schemes button')) {
      if (btn.dataset.s === cfg.scheme) btn.classList.add('on');
      btn.onclick = () => { const u = new URL(location.href); u.searchParams.set('scheme', btn.dataset.s); location.href = u.toString(); };
    }
    if (q.has('select')) setupSelect(map);
  }

  function setupSelect(map) {
    document.body.classList.add('select');
    const drawBtn = document.getElementById('draw'), useBtn = document.getElementById('use');
    const msg = document.getElementById('selmsg'), done = document.getElementById('done');
    let start = null, box = null;
    const empty = {type: 'FeatureCollection', features: []};
    const rect = (a, c) => ({type: 'Feature', geometry: {type: 'Polygon', coordinates: [[
      [a.lng, a.lat], [c.lng, a.lat], [c.lng, c.lat], [a.lng, c.lat], [a.lng, a.lat]]]}});
    const addLayers = () => {
      if (map.getSource('sel')) return;
      map.addSource('sel', {type: 'geojson', data: empty});
      map.addLayer({id: 'sel-fill', type: 'fill', source: 'sel', paint: {'fill-color': '#ff6a00', 'fill-opacity': 0.15}});
      map.addLayer({id: 'sel-line', type: 'line', source: 'sel', paint: {'line-color': '#ff6a00', 'line-width': 2.5}});
    };
    map.loaded() ? addLayers() : map.once('load', addLayers);
    const describe = () => {
      const [w, s, e, n] = box;
      const km = (a, b2) => (Math.abs(a - b2) * 111.32);
      const wkm = km(w, e) * Math.cos((s + n) / 2 * Math.PI / 180), hkm = km(s, n);
      msg.textContent = `Area about ${wkm.toFixed(1)} km × ${hkm.toFixed(1)} km.`;
    };
    drawBtn.onclick = () => {
      document.body.classList.add('drawing');
      map.dragPan.disable();
      msg.textContent = 'Press and drag on the map to draw the box.';
      done.textContent = '';
    };
    map.on('mousedown', e => {
      if (!document.body.classList.contains('drawing')) return;
      start = e.lngLat;
    });
    map.on('mousemove', e => {
      if (!start) return;
      map.getSource('sel').setData({type: 'FeatureCollection', features: [rect(start, e.lngLat)]});
    });
    map.on('mouseup', e => {
      if (!start) return;
      const a = start, c = e.lngLat;
      start = null;
      document.body.classList.remove('drawing');
      map.dragPan.enable();
      box = [Math.min(a.lng, c.lng), Math.min(a.lat, c.lat), Math.max(a.lng, c.lng), Math.max(a.lat, c.lat)];
      if (box[2] - box[0] < 1e-4 || box[3] - box[1] < 1e-4) { box = null; msg.textContent = 'That box is too small; try again.'; return; }
      map.getSource('sel').setData({type: 'FeatureCollection', features: [rect(a, c)]});
      useBtn.disabled = false;
      describe();
    });
    useBtn.onclick = async () => {
      if (!box) return;
      const r = await fetch('/selection', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({bbox: box})});
      done.textContent = r.ok ? 'Area saved. You can close this tab and go back to the converter.' : 'Could not save the area (is the converter still open?)';
    };
  }

  function idle() {
    return new Promise(resolve => {
      const done = () => resolve();
      map.once('idle', done);
      map.triggerRepaint();
    });
  }

  // Render one view. lng/lat = centre, zoom = MapLibre zoom.
  window.renderView = async function (lng, lat, zoom, fmt) {
    const p = idle();
    map.jumpTo({center: [lng, lat], zoom});
    await p;
    return map.getCanvas().toDataURL(fmt || 'image/png');
  };
  // Render one block and return its tiles, already cut and PNG-encoded by a
  // pool of workers: [{i, j, png: base64}] (fully transparent tiles left out).
  const pool = [];
  const nWorkers = Math.max(2, Math.min(8, (navigator.hardwareConcurrency || 4) - 1));
  for (let k = 0; k < nWorkers; k++) pool.push(new Worker('tileworker.js'));
  let seq = 0;
  const b64 = buf => {
    const u = new Uint8Array(buf); let s = '';
    for (let k = 0; k < u.length; k += 0x8000) s += String.fromCharCode.apply(null, u.subarray(k, k + 0x8000));
    return btoa(s);
  };
  window.renderBlock = async function (lng, lat, zoom, block, marginCss) {
    const p = idle();
    map.jumpTo({center: [lng, lat], zoom});
    await p;
    const canvas = map.getCanvas();
    const ts = 256 * ratio, m = marginCss * ratio;
    const id = ++seq;
    const jobs = [];
    for (let j = 0; j < block; j++) {
      const bmp = await createImageBitmap(canvas, m, m + j * ts, block * ts, ts, {premultiplyAlpha: 'none'});
      const w = pool[j % pool.length];
      jobs.push(new Promise(res => {
        const on = e => { if (e.data.id === id && e.data.row === j) { w.removeEventListener('message', on); res(e.data); } };
        w.addEventListener('message', on);
        w.postMessage({id, bitmap: bmp, ts, cols: block, row: j}, [bmp]);
      }));
    }
    const out = [];
    for (const r of await Promise.all(jobs)) {
      for (const t of r.tiles) if (t.buf) out.push({i: t.col, j: r.row, png: b64(t.buf)});
    }
    return out;
  };
  await new Promise(r => (map.loaded() ? r() : map.once('load', r)));
  window.ready = true;
})().catch(e => { window.lastError = String(e); });
