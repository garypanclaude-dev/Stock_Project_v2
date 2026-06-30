// DCA 模擬器折線圖：累積投入 vs 目標 ETF 含息市值 vs 對照 0050 含息市值。
//
// 三條線：
//   - 累積投入（灰色基線）
//   - 目標 ETF 含息市值（綠粗線）
//   - 0050 對照含息市值（藍虛線）

export function renderEtfDcaChart(canvas, targetResult, benchmarkResult) {
  if (!targetResult?.timeline?.length) return null;

  const labels = targetResult.timeline.map(p => p.date);
  const invested = targetResult.timeline.map(p => p.invested);
  const targetMv = targetResult.timeline.map(p => p.market_value + (p.cash_div_received || 0));

  const datasets = [
    {
      label: '累積投入本金',
      data: invested,
      borderColor: 'rgb(148, 163, 184)',
      backgroundColor: 'rgba(148, 163, 184, 0.08)',
      borderWidth: 1.5,
      borderDash: [2, 2],
      fill: false,
      pointRadius: 0,
      tension: 0,
    },
    {
      label: `${targetResult.symbol.replace('.TW', '')} 含息市值`,
      data: targetMv,
      borderColor: 'rgb(16, 185, 129)',
      backgroundColor: 'rgba(16, 185, 129, 0.1)',
      borderWidth: 2.5,
      fill: true,
      pointRadius: 0,
      tension: 0.1,
    },
  ];

  if (benchmarkResult?.timeline?.length) {
    const benchMv = benchmarkResult.timeline.map(p => p.market_value + (p.cash_div_received || 0));
    datasets.push({
      label: `${benchmarkResult.symbol.replace('.TW', '')} 對照含息市值`,
      data: benchMv,
      borderColor: 'rgb(96, 165, 250)',
      borderWidth: 1.8,
      borderDash: [5, 4],
      fill: false,
      pointRadius: 0,
      tension: 0.1,
    });
  }

  return new Chart(canvas.getContext('2d'), {
    type: 'line',
    data: { labels, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: {
          labels: { color: '#cbd5e1', font: { size: 11 }, boxWidth: 14 },
        },
        tooltip: {
          callbacks: {
            label: ctx => {
              const v = ctx.parsed.y;
              const txt = v >= 1e8 ? `${(v / 1e8).toFixed(2)} 億`
                        : v >= 1e4 ? `${(v / 1e4).toFixed(1)} 萬`
                        : v.toLocaleString();
              return `${ctx.dataset.label}: ${txt}`;
            },
          },
        },
      },
      scales: {
        x: {
          ticks: { color: '#64748b', font: { size: 10 }, maxTicksLimit: 8 },
          grid: { display: false },
        },
        y: {
          ticks: {
            color: '#64748b',
            font: { size: 10 },
            callback: v => v >= 1e6 ? (v / 1e4).toFixed(0) + ' 萬' : v.toLocaleString(),
          },
          grid: { color: 'rgba(100, 116, 139, 0.1)' },
        },
      },
    },
  });
}
