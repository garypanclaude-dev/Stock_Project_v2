// 同業 / 自選股相對表現折線圖。

const PEER_COLORS = ['#3b82f6','#22c55e','#f59e0b','#a855f7','#ef4444','#06b6d4','#ec4899','#84cc16'];

export function renderRelativePerformance(canvas, perfData) {
  if (!perfData?.labels) return null;
  const ctx = canvas.getContext('2d');
  const syms = Object.keys(perfData.series);
  const datasets = syms.map((sym, i) => ({
    label: sym.replace(/\.(TW|SS|SZ)$/, ''),
    data: perfData.series[sym],
    borderColor: PEER_COLORS[i % PEER_COLORS.length],
    borderWidth: sym.includes('SPY') || sym.includes('0050') ? 2 : 1.5,
    borderDash: sym.includes('SPY') || sym.includes('0050') ? [5,3] : [],
    pointRadius: 0, tension: 0.3, fill: false,
  }));

  const labels = perfData.labels.length > 60
    ? perfData.labels.map((l,i) => i % 10 === 0 ? l : '')
    : perfData.labels.length > 30
      ? perfData.labels.map((l,i) => i % 5 === 0 ? l : '')
      : perfData.labels;

  return new Chart(ctx, {
    type: 'line', data: { labels, datasets },
    options: {
      responsive: true, maintainAspectRatio: false, animation: { duration: 300 },
      scales: {
        x: { grid:{color:'#1e293b'}, ticks:{color:'#64748b',font:{size:9},maxRotation:0}, border:{color:'#334155'} },
        y: { position:'right', grid:{color:'#1e293b80'}, ticks:{color:'#64748b',font:{size:10},callback:v=>v.toFixed(0)+'%'}, border:{color:'#334155'} },
      },
      plugins: {
        legend: { display:true, position:'top', labels:{color:'#94a3b8',boxWidth:10,boxHeight:3,font:{size:10},usePointStyle:false,padding:8} },
        tooltip: { backgroundColor:'#0f172a', borderColor:'#334155', borderWidth:1, bodyColor:'#94a3b8', padding:8,
          callbacks:{ label: item => `  ${item.dataset.label}: ${item.raw?.toFixed(1)}%` } },
      },
    },
  });
}
