// ETF 績效折線圖：含息（Adj Close）vs 不含息（Close）累積報酬。

export function renderEtfPerformanceChart(canvas, priceHistory) {
  if (!priceHistory?.length) return null;

  const valid = priceHistory.filter(p => p.close != null);
  if (!valid.length) return null;

  const base = valid[0];
  const baseClose = base.close;
  const baseAdj = base.adj_close ?? base.close;

  const labels = valid.map(p => p.date);
  const closeSeries = valid.map(p => (p.close / baseClose - 1) * 100);
  const adjSeries = valid.map(p => ((p.adj_close ?? p.close) / baseAdj - 1) * 100);

  return new Chart(canvas.getContext('2d'), {
    type: 'line',
    data: {
      labels,
      datasets: [
        {
          label: '含息（再投入）',
          data: adjSeries,
          borderColor: 'rgb(16, 185, 129)',
          backgroundColor: 'rgba(16, 185, 129, 0.08)',
          borderWidth: 2,
          fill: true,
          pointRadius: 0,
          tension: 0.1,
        },
        {
          label: '不含息（純價格）',
          data: closeSeries,
          borderColor: 'rgb(148, 163, 184)',
          borderWidth: 1.5,
          borderDash: [4, 3],
          pointRadius: 0,
          tension: 0.1,
          fill: false,
        },
      ],
    },
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
            label: ctx => `${ctx.dataset.label}: ${ctx.parsed.y >= 0 ? '+' : ''}${ctx.parsed.y.toFixed(2)}%`,
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
            color: '#64748b', font: { size: 10 },
            callback: v => `${v >= 0 ? '+' : ''}${v}%`,
          },
          grid: { color: 'rgba(100, 116, 139, 0.1)' },
        },
      },
    },
  });
}
