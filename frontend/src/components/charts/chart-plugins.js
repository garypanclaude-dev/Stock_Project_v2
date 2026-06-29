// Chart.js 自訂繪圖外掛：K 棒、型態標記。
// 從舊 app.js 抽出，純畫圖邏輯，不持有狀態。

// activeOverlays 由外部以模組變數注入：避免 plugin 與 app state 直接耦合。
let _activeOverlaysRef = null;

export function bindActiveOverlays(setRef) {
  _activeOverlaysRef = setRef;
}

export const CandlestickPlugin = {
  id: 'candlestick',
  afterDatasetsDraw(chart) {
    const { ctx, scales: { x, y } } = chart;
    const klines = chart._klines;
    if (!klines) return;
    const meta = chart.getDatasetMeta(0);
    meta.data.forEach((bar, i) => {
      const k = klines[i]; if (!k || bar.x == null) return;
      const xc = bar.x;
      const bull = k.close >= k.open;
      const color = bull ? '#22c55e' : '#ef4444';
      const hw = Math.max(3, Math.min(7, Math.round(chart.width / klines.length * 0.3)));
      ctx.save();
      ctx.beginPath(); ctx.strokeStyle = color; ctx.lineWidth = 1.5;
      ctx.moveTo(xc, y.getPixelForValue(k.high)); ctx.lineTo(xc, y.getPixelForValue(k.low)); ctx.stroke();
      const openY = y.getPixelForValue(k.open), closeY = y.getPixelForValue(k.close);
      const by = Math.min(openY, closeY), bh = Math.max(Math.abs(openY - closeY), 2);
      ctx.fillStyle = bull ? 'rgba(34,197,94,.75)' : 'rgba(239,68,68,.9)';
      ctx.fillRect(xc - hw, by, hw * 2, bh);
      ctx.strokeStyle = color; ctx.lineWidth = 1; ctx.strokeRect(xc - hw, by, hw * 2, bh);
      ctx.restore();
    });
  }
};

export const PatternMarkerPlugin = {
  id: 'pattern-markers',
  afterDatasetsDraw(chart) {
    const patterns = chart._patterns;
    const klines = chart._klines;
    if (!patterns || !patterns.length || !klines) return;
    if (_activeOverlaysRef && !_activeOverlaysRef().has('patterns')) return;
    const { ctx, scales: { y } } = chart;
    const meta = chart.getDatasetMeta(0);
    const byDate = {};
    patterns.forEach(p => {
      const idx = klines.findIndex(k => k.date === p.date);
      if (idx < 0) return;
      (byDate[idx] = byDate[idx] || []).push(p);
    });
    Object.entries(byDate).forEach(([idxStr, pats]) => {
      const idx = +idxStr;
      const bar = meta.data[idx];
      if (!bar) return;
      const xc = bar.x;
      const k = klines[idx];
      pats.forEach((p, stackI) => {
        const size = 6;
        const offset = 10 + stackI * (size * 2 + 2);
        ctx.save();
        ctx.fillStyle = p.color;
        if (p.direction === 'bullish') {
          const yPos = y.getPixelForValue(k.low) + offset;
          ctx.beginPath();
          ctx.moveTo(xc, yPos); ctx.lineTo(xc - size, yPos + size); ctx.lineTo(xc + size, yPos + size);
          ctx.closePath(); ctx.fill();
        } else if (p.direction === 'bearish') {
          const yPos = y.getPixelForValue(k.high) - offset;
          ctx.beginPath();
          ctx.moveTo(xc, yPos); ctx.lineTo(xc - size, yPos - size); ctx.lineTo(xc + size, yPos - size);
          ctx.closePath(); ctx.fill();
        } else {
          const yPos = y.getPixelForValue(k.high) - offset;
          ctx.beginPath();
          ctx.moveTo(xc, yPos - size/2); ctx.lineTo(xc + size/2, yPos);
          ctx.lineTo(xc, yPos + size/2); ctx.lineTo(xc - size/2, yPos);
          ctx.closePath(); ctx.fill();
        }
        ctx.restore();
      });
    });
  }
};

export function thinLabels(klines) {
  return klines.map((k, i) => {
    if (klines.length > 120) return i % 20 === 0 ? k.date.slice(5) : '';
    if (klines.length > 60)  return i % 10 === 0 ? k.date.slice(5) : '';
    if (klines.length > 30)  return i % 5  === 0 ? k.date.slice(5) : '';
    return k.date.slice(5);
  });
}
