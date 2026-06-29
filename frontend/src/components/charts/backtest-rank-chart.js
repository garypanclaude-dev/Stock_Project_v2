// 回測：排名分組超額報酬柱狀圖。

export function renderBacktestRankChart(canvas, byRankGroup, forwardDays) {
  if (!byRankGroup || !forwardDays) return null;
  const groups = ['1-5', '6-10', '11-15', '16-20'];
  const colors = ['#3b82f6', '#06b6d4', '#f59e0b', '#64748b'];
  const labels = forwardDays.map(d => `${d}天`);
  const datasets = groups.map((g, gi) => ({
    label: `排名 ${g}`,
    data: forwardDays.map(d => {
      const stats = byRankGroup[g]?.[String(d)];
      return stats ? stats.avg_excess : 0;
    }),
    backgroundColor: colors[gi] + '99',
    borderColor: colors[gi],
    borderWidth: 1,
  }));
  const ctx = canvas.getContext('2d');
  return new Chart(ctx, {
    type: 'bar',
    data: { labels, datasets },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { labels: { color: '#94a3b8', boxWidth: 14, font: { size: 11 } } },
        tooltip: {
          backgroundColor: '#1e293b', titleColor: '#e2e8f0', bodyColor: '#cbd5e1',
          callbacks: { label: ctx => `${ctx.dataset.label}: ${ctx.parsed.y>=0?'+':''}${ctx.parsed.y.toFixed(2)}%` },
        },
      },
      scales: {
        x: { ticks: { color: '#94a3b8', font: { size: 11 } }, grid: { color: '#1e293b' } },
        y: { ticks: { color: '#64748b', font: { size: 10 }, callback: v => `${v>=0?'+':''}${parseFloat(v.toFixed(2))}%` }, grid: { color: '#1e293b' } },
      },
    },
  });
}
