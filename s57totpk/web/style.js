// MapLibre style for the composite ENC tiles, S-52-like. All presentation
// decisions were made in Python (s52.py) and stored as `_xxx` properties;
// this file only maps them onto layers. Zoom values in the data are 256-px
// tile zooms; MapLibre zoom is one less (512-px world).
/* exported buildStyle */
'use strict';

function buildStyle(cfg) {
  const P = cfg.palette;
  const origin = location.origin;
  const tokens = Object.keys(P);
  const col = (prop, dflt = 'CHBLK') => ['match', ['coalesce', ['get', prop], ''], ...tokens.flatMap(t => [t, P[t]]), P[dflt]];
  const minz = prop => ['>=', ['zoom'], ['-', ['coalesce', ['get', prop], 0], 1]];
  const mz = minz('_mz');
  const font = ['match', ['coalesce', ['get', '_tf'], 'R'], 'I', ['literal', ['Italic']], 'B', ['literal', ['Bold']], ['literal', ['Regular']]];
  const halo = cfg.halo || P.DEPDW;
  const dash = {s: null, d: [4, 2.5], o: [0.1, 2.2], l: [9, 2.5, 2, 2.5]};

  const layers = [{id: 'background', type: 'background', paint: {'background-color': 'rgba(0,0,0,0)'}}];
  layers.push({
    id: 'area-fill', type: 'fill', source: 'enc', 'source-layer': 'enc',
    filter: ['all', ['has', '_fill'], mz],
    layout: {'fill-sort-key': ['coalesce', ['get', '_p'], 0]},
    paint: {'fill-color': col('_fill', 'NODTA'), 'fill-antialias': false,
      'fill-opacity': ['coalesce', ['get', '_op'], 1]},
  });
  for (const [k, arr] of Object.entries(dash)) {
    const lyr = {
      id: 'line-' + k, type: 'line', source: 'enc', 'source-layer': 'enc',
      filter: ['all', ['has', '_lc'], ['==', ['get', '_ld'], k], mz],
      layout: {'line-sort-key': ['coalesce', ['get', '_p'], 0], 'line-join': 'round',
        'line-cap': k === 'o' ? 'round' : 'butt'},
      paint: {'line-color': col('_lc'), 'line-width': ['coalesce', ['get', '_lw'], 1]},
    };
    if (arr) lyr.paint['line-dasharray'] = arr;
    layers.push(lyr);
  }
  layers.push({
    id: 'line-labels', type: 'symbol', source: 'enc', 'source-layer': 'enc', minzoom: 11,
    filter: ['all', ['==', ['geometry-type'], 'LineString'], ['has', '_txt'], mz],
    layout: {'symbol-placement': 'line', 'text-field': ['get', '_txt'], 'text-font': ['Regular'],
      'text-size': 10, 'symbol-spacing': 300, 'text-max-angle': 30, 'text-padding': 2},
    paint: {'text-color': col('_tc', 'DEPCN'), 'text-halo-color': halo, 'text-halo-width': 1.2},
  });
  layers.push({
    id: 'soundings', type: 'symbol', source: 'enc', 'source-layer': 'enc',
    filter: ['all', ['==', ['get', 'OBJL'], 'SOUNDG'], ['has', '_snd'], mz],
    layout: {
      'text-field': ['format', ['get', '_snd'], {}, ['coalesce', ['get', '_sndf'], ''], {'font-scale': 0.72}],
      'text-font': ['Regular'], 'text-size': 11, 'text-padding': 1, 'text-allow-overlap': false,
      'symbol-sort-key': ['to-number', ['get', '_snd']],
    },
    paint: {'text-color': col('_sndc', 'SNDG1'), 'text-halo-color': halo, 'text-halo-width': 0.8},
  });
  layers.push({
    id: 'symbols', type: 'symbol', source: 'enc', 'source-layer': 'enc',
    filter: ['all', ['has', '_sym'], mz],
    layout: {
      'icon-image': ['get', '_sym'], 'icon-allow-overlap': true, 'icon-ignore-placement': true,
      'icon-rotation-alignment': 'map', 'icon-anchor': 'center',
      'icon-rotate': ['coalesce', ['get', '_rot'], ['case', ['==', ['slice', ['get', '_sym'], 0, 3], 'lt|'], 135, 0]],
      'symbol-sort-key': ['coalesce', ['get', '_p'], 0], 'symbol-z-order': 'source',
    },
  });
  layers.push({
    id: 'danger-depths', type: 'symbol', source: 'enc', 'source-layer': 'enc',
    filter: ['all', ['has', '_snd'], ['!=', ['get', 'OBJL'], 'SOUNDG'], mz, ['>=', ['zoom'], 11]],
    layout: {
      'text-field': ['format', ['get', '_snd'], {}, ['coalesce', ['get', '_sndf'], ''], {'font-scale': 0.72}],
      'text-font': ['Regular'], 'text-size': 10, 'text-offset': [0, 1.25], 'text-anchor': 'top',
      'text-allow-overlap': false, 'text-optional': true,
    },
    paint: {'text-color': col('_sndc', 'SNDG2'), 'text-halo-color': halo, 'text-halo-width': 0.8},
  });
  // labels next to a symbol
  layers.push({
    id: 'labels-sym', type: 'symbol', source: 'enc', 'source-layer': 'enc',
    filter: ['all', ['==', ['geometry-type'], 'Point'], ['has', '_txt'], ['has', '_sym'], mz, minz('_tz')],
    layout: {
      'text-field': ['get', '_txt'], 'text-font': font, 'text-size': 10.5,
      'text-anchor': 'left', 'text-offset': [0.9, 0.35], 'text-justify': 'left',
      'text-max-width': 14, 'text-padding': 2, 'symbol-sort-key': ['-', 100, ['coalesce', ['get', '_p'], 0]],
    },
    paint: {'text-color': col('_tc'), 'text-halo-color': halo, 'text-halo-width': 1.2},
  });
  // free-standing labels (area names, seabed, spot heights)
  layers.push({
    id: 'labels', type: 'symbol', source: 'enc', 'source-layer': 'enc',
    filter: ['all', ['==', ['geometry-type'], 'Point'], ['has', '_txt'], ['!', ['has', '_sym']], mz, minz('_tz')],
    layout: {
      'text-field': ['get', '_txt'], 'text-font': font, 'text-size': ['case', ['==', ['get', 'OBJL'], 'SEAARE'], 12, 10.5],
      'text-max-width': 10, 'text-padding': 3, 'symbol-sort-key': ['coalesce', ['get', '_p'], 0],
    },
    paint: {'text-color': col('_tc'), 'text-halo-color': halo, 'text-halo-width': 1.2},
  });

  return {
    version: 8,
    name: 'S-52 ' + cfg.scheme,
    glyphs: origin + '/glyphs/{fontstack}/{range}.pbf',
    sources: {enc: {type: 'vector', tiles: [origin + '/tiles/{z}/{x}/{y}.pbf'], minzoom: 0, maxzoom: cfg.vmaxzoom || 15}},
    layers,
  };
}

if (typeof module !== 'undefined') module.exports = {buildStyle};
