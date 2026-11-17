// Cuts a strip of the rendered block into tiles and PNG-encodes them, off
// the main thread. Message: {id, bitmap, ts, cols, row}; reply: {id, row, tiles:[{col, buf|null}]}
'use strict';
self.onmessage = async (e) => {
  const {id, bitmap, ts, cols, row} = e.data;
  const c = new OffscreenCanvas(ts, ts);
  const ctx = c.getContext('2d', {willReadFrequently: true});
  const tiles = [];
  const transfer = [];
  for (let i = 0; i < cols; i++) {
    ctx.clearRect(0, 0, ts, ts);
    ctx.drawImage(bitmap, i * ts, 0, ts, ts, 0, 0, ts, ts);
    const px = ctx.getImageData(0, 0, ts, ts).data;
    let any = false;
    for (let k = 3; k < px.length; k += 4) { if (px[k] !== 0) { any = true; break; } }
    if (!any) { tiles.push({col: i, buf: null}); continue; }  // outside the chart
    const buf = await (await c.convertToBlob({type: 'image/png'})).arrayBuffer();
    tiles.push({col: i, buf});
    transfer.push(buf);
  }
  bitmap.close();
  self.postMessage({id, row, tiles}, transfer);
};
