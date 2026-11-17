// Chart symbols drawn on the device (Canvas 2D) - no remote sprites.
// Every image is drawn with the charted position at the image centre, so
// all symbols use icon-anchor "center". Keys come from the `_sym` property
// made by s52.py, e.g. "boy|2|3,4,3|1", "lts|180|270|LITRD|1".
/* exported drawSymbol */
'use strict';

const S57COL = {1: 'CHWHT', 2: 'CHBLK', 3: 'CHRED', 4: 'CHGRN', 5: 'RESBL', 6: 'CHYLW',
  7: 'CHGRD', 8: 'CHBRN', 9: 'CHYLW', 10: 'CHMGD', 11: 'CHCOR', 12: 'CHMGD', 13: 'CHMGF'};

function colourList(P, s) {
  const out = String(s || '').split(',').map(x => parseInt(x, 10)).filter(x => !isNaN(x))
    .map(c => P[S57COL[c]] || P.CHGRD);
  return out.length ? out : [P.CHGRD];
}

function makeCanvas(w, h, ratio) {
  const c = document.createElement('canvas');
  c.width = Math.ceil(w * ratio); c.height = Math.ceil(h * ratio);
  const ctx = c.getContext('2d');
  ctx.scale(ratio, ratio);
  ctx.lineJoin = 'round'; ctx.lineCap = 'round';
  return [c, ctx];
}

// fill the current path with colour bands (COLPAT), then stroke it
function fillBands(ctx, P, path, bbox, colours, colpat) {
  const [x0, y0, x1, y1] = bbox;
  const n = colours.length;
  ctx.save();
  path(); ctx.clip();
  const pat = parseInt(String(colpat || '').split(',')[0], 10);
  if (n === 1) {
    ctx.fillStyle = colours[0]; ctx.fillRect(x0 - 1, y0 - 1, x1 - x0 + 2, y1 - y0 + 2);
  } else if (pat === 2) { // vertical stripes
    const w = (x1 - x0) / n;
    colours.forEach((c, i) => { ctx.fillStyle = c; ctx.fillRect(x0 + i * w, y0 - 1, w + 0.5, y1 - y0 + 2); });
  } else if (pat === 3) { // diagonal
    const span = (x1 - x0) + (y1 - y0);
    for (let i = 0; i < 12; i++) {
      ctx.fillStyle = colours[i % n];
      ctx.beginPath();
      const a = x0 - (y1 - y0) + i * span / 6, b = a + span / 6;
      ctx.moveTo(a, y1 + 1); ctx.lineTo(b, y1 + 1); ctx.lineTo(b + (y1 - y0) + 2, y0 - 1); ctx.lineTo(a + (y1 - y0) + 2, y0 - 1);
      ctx.fill();
    }
  } else if (pat === 4) { // squared
    const hw = (x1 - x0) / 2, hh = (y1 - y0) / 2;
    for (let i = 0; i < 4; i++) {
      ctx.fillStyle = colours[(i + (i > 1 ? 1 : 0)) % n];
      ctx.fillRect(x0 + (i % 2) * hw, y0 + Math.floor(i / 2) * hh, hw + 0.5, hh + 0.5);
    }
  } else { // horizontal bands (default for several colours)
    const h = (y1 - y0) / n;
    colours.forEach((c, i) => { ctx.fillStyle = c; ctx.fillRect(x0 - 1, y0 + i * h, x1 - x0 + 2, h + 0.5); });
  }
  ctx.restore();
  path(); ctx.lineWidth = 1; ctx.strokeStyle = P.CHBLK; ctx.stroke();
}

function positionMark(ctx, P, cx, cy, r = 1.6) {
  ctx.beginPath(); ctx.arc(cx, cy, r, 0, 2 * Math.PI);
  ctx.lineWidth = 1; ctx.strokeStyle = P.CHBLK; ctx.stroke();
}

function buoy(P, shape, cols, pat, ratio) {
  const W = 28, H = 40, cx = W / 2, cy = H / 2;
  const [c, ctx] = makeCanvas(W, H, ratio);
  const colours = colourList(P, cols);
  const base = cy - 1.5; // waterline just above the position circle
  let path, bbox;
  switch (shape) {
    case 1: // conical
      path = () => { ctx.beginPath(); ctx.moveTo(cx - 5, base); ctx.lineTo(cx, base - 11); ctx.lineTo(cx + 5, base); ctx.closePath(); };
      bbox = [cx - 5, base - 11, cx + 5, base]; break;
    case 2: case 8: // can, ice buoy
      path = () => { ctx.beginPath(); ctx.rect(cx - 4.5, base - 10, 9, 10); };
      bbox = [cx - 4.5, base - 10, cx + 4.5, base]; break;
    case 3: // spherical
      path = () => { ctx.beginPath(); ctx.arc(cx, base - 5, 5, Math.PI * 0.85, Math.PI * 0.15); ctx.closePath(); };
      bbox = [cx - 5, base - 10, cx + 5, base]; break;
    case 5: // spar
      path = () => { ctx.beginPath(); ctx.rect(cx - 1.6, base - 13, 3.2, 13); };
      bbox = [cx - 1.6, base - 13, cx + 1.6, base]; break;
    case 6: // barrel
      path = () => { ctx.beginPath(); ctx.ellipse(cx, base - 3.5, 6.5, 3.5, 0, 0, 2 * Math.PI); };
      bbox = [cx - 6.5, base - 7, cx + 6.5, base]; break;
    case 7: // super-buoy
      path = () => { ctx.beginPath(); ctx.moveTo(cx - 8, base); ctx.lineTo(cx - 6, base - 5); ctx.lineTo(cx + 6, base - 5); ctx.lineTo(cx + 8, base); ctx.closePath(); };
      bbox = [cx - 8, base - 5, cx + 8, base]; break;
    default: // 4 pillar and unknown
      path = () => { ctx.beginPath(); ctx.moveTo(cx - 5, base); ctx.lineTo(cx - 2, base - 13); ctx.lineTo(cx + 2, base - 13); ctx.lineTo(cx + 5, base); ctx.closePath(); };
      bbox = [cx - 5, base - 13, cx + 5, base];
  }
  fillBands(ctx, P, path, bbox, colours, pat);
  ctx.beginPath(); ctx.moveTo(cx - 7, base); ctx.lineTo(cx + 7, base); ctx.lineWidth = 1; ctx.strokeStyle = P.CHBLK; ctx.stroke();
  positionMark(ctx, P, cx, cy);
  return c;
}

function beacon(P, shape, cols, pat, ratio) {
  const W = 28, H = 44, cx = W / 2, cy = H / 2;
  const [c, ctx] = makeCanvas(W, H, ratio);
  const colours = colourList(P, cols);
  const base = cy - 1.6;
  let path, bbox;
  switch (shape) {
    case 3: // tower
      path = () => { ctx.beginPath(); ctx.moveTo(cx - 4, base); ctx.lineTo(cx - 2.5, base - 14); ctx.lineTo(cx + 2.5, base - 14); ctx.lineTo(cx + 4, base); ctx.closePath(); };
      bbox = [cx - 4, base - 14, cx + 4, base]; break;
    case 4: { // lattice
      const p = () => { ctx.beginPath(); ctx.moveTo(cx - 5, base); ctx.lineTo(cx, base - 15); ctx.lineTo(cx + 5, base); };
      p(); ctx.lineWidth = 1.2; ctx.strokeStyle = colours[0] === P.CHWHT ? P.CHBLK : colours[0]; ctx.stroke();
      ctx.beginPath(); ctx.moveTo(cx - 3.3, base - 5); ctx.lineTo(cx + 3.3, base - 5); ctx.moveTo(cx - 1.7, base - 10); ctx.lineTo(cx + 1.7, base - 10); ctx.stroke();
      positionMark(ctx, P, cx, cy);
      return c;
    }
    case 6: // cairn
      path = () => { ctx.beginPath(); ctx.arc(cx, base, 5, Math.PI, 0); ctx.closePath(); };
      bbox = [cx - 5, base - 5, cx + 5, base]; break;
    case 7: // buoyant beacon
      path = () => { ctx.beginPath(); ctx.moveTo(cx - 5, base); ctx.lineTo(cx - 2, base - 13); ctx.lineTo(cx + 2, base - 13); ctx.lineTo(cx + 5, base); ctx.closePath(); };
      bbox = [cx - 5, base - 13, cx + 5, base]; break;
    default: // 1 stake/pole, 2 withy, 5 pile
      path = () => { ctx.beginPath(); ctx.rect(cx - 1.5, base - 15, 3, 15); };
      bbox = [cx - 1.5, base - 15, cx + 1.5, base];
  }
  fillBands(ctx, P, path, bbox, colours, pat);
  positionMark(ctx, P, cx, cy);
  return c;
}

function topmark(P, shape, cols, ratio) {
  // drawn above the buoy/beacon body: base of the topmark 16 px above the position
  const W = 28, H = 60, cx = W / 2, cy = H / 2;
  const [c, ctx] = makeCanvas(W, H, ratio);
  const col = colourList(P, cols)[0];
  const b = cy - 17; // bottom of topmark
  ctx.fillStyle = col; ctx.strokeStyle = P.CHBLK; ctx.lineWidth = 1;
  const tri = (y, up) => { ctx.beginPath(); if (up) { ctx.moveTo(cx - 3.5, y); ctx.lineTo(cx, y - 6); ctx.lineTo(cx + 3.5, y); } else { ctx.moveTo(cx - 3.5, y - 6); ctx.lineTo(cx, y); ctx.lineTo(cx + 3.5, y - 6); } ctx.closePath(); ctx.fill(); ctx.stroke(); };
  const ball = (y) => { ctx.beginPath(); ctx.arc(cx, y - 3, 3, 0, 2 * Math.PI); ctx.fill(); ctx.stroke(); };
  ctx.beginPath(); ctx.moveTo(cx, b + 2); ctx.lineTo(cx, b); ctx.stroke();
  switch (shape) {
    case 1: tri(b, true); break;
    case 2: tri(b, false); break;
    case 4: ball(b); ball(b - 7); break;
    case 5: case 21: ctx.beginPath(); ctx.rect(cx - 2.5, b - 7, 5, 7); ctx.fill(); ctx.stroke(); break;
    case 6: case 20: case 19: ctx.beginPath(); ctx.rect(cx - 3.5, b - 6, 7, 6); ctx.fill(); ctx.stroke(); break;
    case 7: ctx.lineWidth = 1.6; ctx.strokeStyle = col === P.CHWHT ? P.CHBLK : col; ctx.beginPath(); ctx.moveTo(cx - 3.5, b - 7); ctx.lineTo(cx + 3.5, b); ctx.moveTo(cx + 3.5, b - 7); ctx.lineTo(cx - 3.5, b); ctx.stroke(); break;
    case 8: ctx.lineWidth = 1.6; ctx.strokeStyle = col === P.CHWHT ? P.CHBLK : col; ctx.beginPath(); ctx.moveTo(cx, b - 8); ctx.lineTo(cx, b); ctx.moveTo(cx - 3.5, b - 5); ctx.lineTo(cx + 3.5, b - 5); ctx.stroke(); break;
    case 10: tri(b - 6, true); tri(b, false); break;     // points together (W card.)
    case 11: tri(b - 6, false); tri(b, true); break;     // bases together (E card.)
    case 12: ctx.beginPath(); ctx.moveTo(cx, b - 9); ctx.lineTo(cx + 3.5, b - 4.5); ctx.lineTo(cx, b); ctx.lineTo(cx - 3.5, b - 4.5); ctx.closePath(); ctx.fill(); ctx.stroke(); break;
    case 13: tri(b - 7, true); tri(b, true); break;      // N card.
    case 14: tri(b - 7, false); tri(b, false); break;    // S card.
    case 22: case 23: ctx.beginPath(); ctx.moveTo(cx - 4, b); ctx.lineTo(cx - 2, b - 6); ctx.lineTo(cx + 2, b - 6); ctx.lineTo(cx + 4, b); ctx.closePath(); ctx.fill(); ctx.stroke(); break;
    default: ball(b);
  }
  return c;
}

function flare(P, tok, ratio) {
  // drawn pointing up from the centre; the layer rotates it (135 deg default)
  const W = 40, H = 40, cx = W / 2, cy = H / 2;
  const [c, ctx] = makeCanvas(W, H, ratio);
  ctx.beginPath();
  ctx.moveTo(cx, cy - 1);
  ctx.bezierCurveTo(cx - 4.5, cy - 9, cx - 3.8, cy - 16, cx, cy - 16.5);
  ctx.bezierCurveTo(cx + 3.8, cy - 16, cx + 4.5, cy - 9, cx, cy - 1);
  ctx.fillStyle = P[tok] || P.LITYW; ctx.fill();
  ctx.lineWidth = 0.8; ctx.strokeStyle = P.CHBLK; ctx.stroke();
  return c;
}

function sectorLight(P, s1, s2, tok, big, ratio) {
  const r = big ? 36 : 26, leg = r + 12;
  const W = 2 * leg + 8, cx = W / 2, cy = W / 2;
  const [c, ctx] = makeCanvas(W, W, ratio);
  const ang = b => ((b + 180) % 360) * Math.PI / 180 - Math.PI / 2; // bearing from seaward -> canvas
  let a1 = ang(s1), a2 = ang(s2);
  if (Math.abs(((s2 - s1) % 360 + 360) % 360) < 0.01) a2 = a1 + 2 * Math.PI;
  ctx.setLineDash([3, 2]); ctx.lineWidth = 0.9; ctx.strokeStyle = P.CHBLK;
  for (const a of [a1, a2]) { ctx.beginPath(); ctx.moveTo(cx, cy); ctx.lineTo(cx + leg * Math.cos(a), cy + leg * Math.sin(a)); ctx.stroke(); }
  ctx.setLineDash([]);
  ctx.beginPath(); ctx.arc(cx, cy, r, a1, a2, false); ctx.lineWidth = 4.5; ctx.strokeStyle = P.OUTLW; ctx.stroke();
  ctx.beginPath(); ctx.arc(cx, cy, r, a1, a2, false); ctx.lineWidth = 3; ctx.strokeStyle = P[tok] || P.LITYW; ctx.stroke();
  return c;
}

function simple(P, key, ratio) {
  const W = 28, H = 28, cx = W / 2, cy = H / 2;
  const [c, ctx] = makeCanvas(W, H, ratio);
  const st = (col, w = 1) => { ctx.strokeStyle = col; ctx.lineWidth = w; ctx.stroke(); };
  const parts = key.split('|');
  switch (parts[0]) {
    case 'isodgr':
      ctx.beginPath(); ctx.arc(cx, cy, 6.5, 0, 2 * Math.PI); ctx.fillStyle = P.DEPVS; ctx.fill(); st(P.ISDNG, 1.6);
      ctx.beginPath(); ctx.moveTo(cx - 3.5, cy - 3.5); ctx.lineTo(cx + 3.5, cy + 3.5); ctx.moveTo(cx + 3.5, cy - 3.5); ctx.lineTo(cx - 3.5, cy + 3.5); st(P.ISDNG, 1.6);
      break;
    case 'wrk': {
      const t = parts[1];
      if (t === 'hull') {
        ctx.beginPath(); ctx.moveTo(cx - 8, cy); ctx.quadraticCurveTo(cx, cy + 6, cx + 8, cy); ctx.closePath(); ctx.fillStyle = P.CHBLK; ctx.fill();
        ctx.beginPath(); ctx.moveTo(cx - 3, cy); ctx.lineTo(cx - 3, cy - 5); ctx.moveTo(cx + 2, cy); ctx.lineTo(cx + 2, cy - 4); st(P.CHBLK, 1);
      } else if (t === 'mast') {
        ctx.beginPath(); ctx.moveTo(cx - 7, cy); ctx.lineTo(cx + 7, cy); ctx.moveTo(cx - 2, cy); ctx.lineTo(cx - 2, cy - 7); ctx.moveTo(cx + 3, cy); ctx.lineTo(cx + 3, cy - 6); st(P.CHBLK, 1.2);
      } else {
        const col = t === 'nd' ? P.CHGRD : P.CHBLK;
        if (t === 'd') { ctx.setLineDash([1, 2]); ctx.beginPath(); ctx.ellipse(cx, cy, 10, 6, 0, 0, 2 * Math.PI); st(P.CHBLK, 1); ctx.setLineDash([]); }
        ctx.beginPath(); ctx.moveTo(cx - 7, cy); ctx.lineTo(cx + 7, cy);
        for (const dx of [-3.5, 0, 3.5]) { ctx.moveTo(cx + dx, cy - 3); ctx.lineTo(cx + dx, cy + 3); }
        st(col, 1.2);
      }
      break;
    }
    case 'rock': {
      const t = parts[1];
      ctx.beginPath();
      if (t === 'cov') {
        for (let i = 0; i < 3; i++) { const a = i * Math.PI / 3; ctx.moveTo(cx - 5 * Math.cos(a), cy - 5 * Math.sin(a)); ctx.lineTo(cx + 5 * Math.cos(a), cy + 5 * Math.sin(a)); }
      } else { ctx.moveTo(cx - 5, cy); ctx.lineTo(cx + 5, cy); ctx.moveTo(cx, cy - 5); ctx.lineTo(cx, cy + 5); }
      st(P.CHBLK, 1.3);
      if (t === 'awash' || t === 'uw') {
        ctx.fillStyle = P.CHBLK;
        for (const [dx, dy] of [[-3, -3], [3, -3], [-3, 3], [3, 3]]) { ctx.beginPath(); ctx.arc(cx + dx, cy + dy, 0.8, 0, 2 * Math.PI); ctx.fill(); }
      }
      break;
    }
    case 'obstn':
      ctx.setLineDash([1, 2]); ctx.beginPath(); ctx.arc(cx, cy, 6.5, 0, 2 * Math.PI); st(P.CHBLK, 1.1); ctx.setLineDash([]);
      if (parts[1] === 'foul') { ctx.beginPath(); ctx.moveTo(cx - 3, cy - 4); ctx.lineTo(cx - 3, cy + 4); ctx.moveTo(cx + 3, cy - 4); ctx.lineTo(cx + 3, cy + 4); ctx.moveTo(cx - 4, cy - 1.5); ctx.lineTo(cx + 4, cy - 1.5); ctx.moveTo(cx - 4, cy + 1.5); ctx.lineTo(cx + 4, cy + 1.5); st(P.CHBLK, 0.9); }
      break;
    case 'achare': {
      const col = P.CHMGF === undefined ? P.CHMGD : P.CHMGD;
      ctx.beginPath(); ctx.moveTo(cx, cy - 6); ctx.lineTo(cx, cy + 6); ctx.moveTo(cx - 3.5, cy - 3); ctx.lineTo(cx + 3.5, cy - 3);
      ctx.moveTo(cx - 6, cy + 1); ctx.quadraticCurveTo(cx - 5, cy + 6.5, cx, cy + 6.5); ctx.quadraticCurveTo(cx + 5, cy + 6.5, cx + 6, cy + 1);
      st(col, 1.4); ctx.beginPath(); ctx.arc(cx, cy - 7.5, 1.5, 0, 2 * Math.PI); st(col, 1.2);
      break;
    }
    case 'resare':
      ctx.beginPath(); ctx.arc(cx, cy, 6, 0, 2 * Math.PI); st(P.CHMGD, 1.4);
      ctx.beginPath(); ctx.moveTo(cx - 3.5, cy); ctx.lineTo(cx + 3.5, cy); st(P.CHMGD, 1.8);
      break;
    case 'ctnare': case 'mipare':
      ctx.beginPath(); ctx.moveTo(cx, cy - 7); ctx.lineTo(cx + 7, cy + 5); ctx.lineTo(cx - 7, cy + 5); ctx.closePath(); st(P.CHMGD, 1.3);
      ctx.beginPath(); ctx.moveTo(cx, cy - 3); ctx.lineTo(cx, cy + 1); st(P.CHMGD, 1.6);
      ctx.beginPath(); ctx.arc(cx, cy + 3, 0.6, 0, 2 * Math.PI); st(P.CHMGD, 1.4);
      break;
    case 'cblare': case 'pipare':
      ctx.beginPath(); ctx.moveTo(cx - 7, cy); ctx.bezierCurveTo(cx - 3, cy - 5, cx + 3, cy + 5, cx + 7, cy); st(P.CHMGD, 1.3);
      if (parts[0] === 'pipare') { ctx.beginPath(); ctx.arc(cx - 7, cy, 1.5, 0, 2 * Math.PI); ctx.arc(cx + 7, cy, 1.5, 0, 2 * Math.PI); st(P.CHMGD, 1); }
      break;
    case 'dmpgrd': case 'marcul': case 'fshfac':
      ctx.beginPath(); ctx.moveTo(cx - 6, cy - 4); ctx.lineTo(cx + 6, cy - 4); ctx.lineTo(cx, cy + 5); ctx.closePath(); st(P.CHGRD, 1.2); break;
    case 'pilbop':
      ctx.beginPath(); ctx.arc(cx, cy, 8, 0, 2 * Math.PI); st(P.CHMGD, 1.4);
      ctx.beginPath(); ctx.arc(cx, cy, 1.4, 0, 2 * Math.PI); ctx.fillStyle = P.CHMGD; ctx.fill(); break;
    case 'tsslpt': case 'curent':
      ctx.beginPath(); ctx.moveTo(cx, cy - 10); ctx.lineTo(cx + 5, cy - 3); ctx.lineTo(cx + 2, cy - 3); ctx.lineTo(cx + 2, cy + 10); ctx.lineTo(cx - 2, cy + 10); ctx.lineTo(cx - 2, cy - 3); ctx.lineTo(cx - 5, cy - 3); ctx.closePath();
      st(parts[0] === 'tsslpt' ? P.TRFCD : P.CHGRD, 1.2); break;
    case 'litves':
      ctx.beginPath(); ctx.moveTo(cx - 8, cy); ctx.lineTo(cx + 8, cy); ctx.lineTo(cx + 5, cy + 4); ctx.lineTo(cx - 5, cy + 4); ctx.closePath(); ctx.fillStyle = P.CHBLK; ctx.fill();
      ctx.beginPath(); ctx.moveTo(cx, cy); ctx.lineTo(cx, cy - 8); st(P.CHBLK, 1.3); break;
    case 'daymar':
      ctx.beginPath(); ctx.rect(cx - 3.5, cy - 9, 7, 6); ctx.fillStyle = P.CHGRD; ctx.fill(); st(P.CHBLK, 1);
      ctx.beginPath(); ctx.moveTo(cx, cy - 3); ctx.lineTo(cx, cy); st(P.CHBLK, 1); break;
    case 'fogsig':
      for (const r of [4, 7, 10]) { ctx.beginPath(); ctx.arc(cx, cy, r, -Math.PI * 0.75, -Math.PI * 0.25); st(P.CHMGD, 1.1); }
      break;
    case 'radio':
      ctx.beginPath(); ctx.arc(cx, cy, 7, 0, 2 * Math.PI); st(P.CHMGD, 1.4); break;
    case 'tank':
      ctx.beginPath(); ctx.arc(cx, cy, 3.5, 0, 2 * Math.PI); ctx.fillStyle = P.CHBRN; ctx.fill(); st(P.CHBLK, 1); break;
    case 'pile': case 'elev':
      ctx.beginPath(); ctx.arc(cx, cy, 1.4, 0, 2 * Math.PI); ctx.fillStyle = P.CHBLK; ctx.fill(); break;
    case 'morfac': case 'ofsplf': case 'pylon': case 'crane':
      ctx.beginPath(); ctx.rect(cx - 3, cy - 3, 6, 6); st(P.CHBLK, 1.1);
      if (parts[0] !== 'morfac') { ctx.beginPath(); ctx.arc(cx, cy, 0.8, 0, 2 * Math.PI); ctx.fillStyle = P.CHBLK; ctx.fill(); }
      break;
    case 'stn': case 'smcfac': case 'hrbfac': case 'spring':
      ctx.beginPath(); ctx.arc(cx, cy, 4, 0, 2 * Math.PI); st(P.CHMGD, 1.2);
      ctx.beginPath(); ctx.arc(cx, cy, 1, 0, 2 * Math.PI); ctx.fillStyle = P.CHMGD; ctx.fill(); break;
    case 'bui': {
      const consp = parts[1] === '1';
      ctx.beginPath(); ctx.rect(cx - 3, cy - 3, 6, 6); ctx.fillStyle = consp ? P.CHBLK : P.CHBRN; ctx.fill(); st(P.CHBLK, 0.8); break;
    }
    default:
      return null;
  }
  return c;
}

function landmark(P, cat, consp, ratio) {
  const W = 28, H = 40, cx = W / 2, cy = H / 2;
  const [c, ctx] = makeCanvas(W, H, ratio);
  const col = consp ? P.CHBLK : P.LANDF;
  const st = (w = 1.2) => { ctx.strokeStyle = col; ctx.lineWidth = w; ctx.stroke(); };
  const b = cy - 2.5;
  ctx.beginPath();
  switch (cat) {
    case 3: ctx.rect(cx - 2, b - 12, 4, 12); st(); ctx.beginPath(); ctx.moveTo(cx + 1, b - 13); ctx.quadraticCurveTo(cx + 5, b - 16, cx + 8, b - 15); st(0.8); break; // chimney
    case 5: ctx.moveTo(cx, b); ctx.lineTo(cx, b - 13); ctx.lineTo(cx + 6, b - 11); ctx.lineTo(cx, b - 9); st(); break; // flagstaff
    case 4: case 7: case 16: case 8: ctx.moveTo(cx, b); ctx.lineTo(cx, b - 13); ctx.moveTo(cx - 3, b - 9); ctx.lineTo(cx, b - 13); ctx.lineTo(cx + 3, b - 9); st(); break; // mast etc
    case 9: case 10: case 11: case 12: case 13: ctx.moveTo(cx - 3, b); ctx.lineTo(cx, b - 13); ctx.lineTo(cx + 3, b); st(); break;
    case 14: ctx.moveTo(cx, b); ctx.lineTo(cx, b - 12); ctx.moveTo(cx - 4, b - 8); ctx.lineTo(cx + 4, b - 8); st(); break;
    case 15: ctx.arc(cx, b, 6, Math.PI, 0); st(); break;
    case 18: case 19: ctx.moveTo(cx - 5, b - 13); ctx.lineTo(cx + 5, b - 3); ctx.moveTo(cx + 5, b - 13); ctx.lineTo(cx - 5, b - 3); st(); break;
    case 20: ctx.moveTo(cx - 3, b); ctx.lineTo(cx, b - 15); ctx.lineTo(cx + 3, b); st(); break;
    case 17: case 6: ctx.moveTo(cx - 4, b); ctx.lineTo(cx - 2.5, b - 13); ctx.lineTo(cx + 2.5, b - 13); ctx.lineTo(cx + 4, b); st(); break;
    case 1: case 21: ctx.moveTo(cx - 5, b); ctx.lineTo(cx, b - 7); ctx.lineTo(cx + 5, b); st(); break;
    default: break;
  }
  ctx.beginPath(); ctx.arc(cx, cy, 2.5, 0, 2 * Math.PI); ctx.strokeStyle = col; ctx.lineWidth = 1.1; ctx.stroke();
  ctx.beginPath(); ctx.arc(cx, cy, 0.7, 0, 2 * Math.PI); ctx.fillStyle = col; ctx.fill();
  return c;
}

function drawSymbol(id, P, ratio) {
  const p = id.split('|');
  let c = null;
  switch (p[0]) {
    case 'boy': c = buoy(P, parseInt(p[1], 10) || 0, p[2], p[3], ratio); break;
    case 'bcn': c = beacon(P, parseInt(p[1], 10) || 0, p[2], p[3], ratio); break;
    case 'top': c = topmark(P, parseInt(p[1], 10) || 0, p[2], ratio); break;
    case 'lt': c = flare(P, p[1], ratio); break;
    case 'lts': c = sectorLight(P, parseFloat(p[1]), parseFloat(p[2]), p[3], p[4] === '1', ratio); break;
    case 'lmk': c = landmark(P, parseInt(p[1], 10) || 0, p[2] === '1', ratio); break;
    default: c = simple(P, id, ratio);
  }
  if (!c) return null;
  return c.getContext('2d').getImageData(0, 0, c.width, c.height);
}

if (typeof module !== 'undefined') module.exports = {drawSymbol};
