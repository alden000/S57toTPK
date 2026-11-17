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
  map.on('error', e => { window.lastError = String(e && e.error && e.error.message || e); });

  if (preview) {
    map.addControl(new maplibregl.NavigationControl());
    if (b) map.fitBounds([[b[0], b[1]], [b[2], b[3]]], {duration: 0});
    const info = document.getElementById('info');
    const upd = () => { const c = map.getCenter(); info.textContent = `tile zoom ${(map.getZoom() + 1).toFixed(2)}  ${c.lat.toFixed(5)}, ${c.lng.toFixed(5)}  scheme ${cfg.scheme}`; };
    map.on('move', upd); upd();
    map.on('click', e => {
      const f = map.queryRenderedFeatures(e.point);
      console.log(f.map(x => x.properties));
      info.textContent = f.slice(0, 4).map(x => `${x.properties.OBJL} ${x.properties.OBJNAM || ''}`).join(' | ');
    });
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
  await new Promise(r => (map.loaded() ? r() : map.once('load', r)));
  window.ready = true;
})().catch(e => { window.lastError = String(e); });
