// ETF 配息柱狀圖：X = 除息日、Y = 每股配息額。

export function renderEtfDividendChart(canvas, dividends) {
  if (!dividends?.length) return null;
  const sorted = [...dividends].sort((a, b) => a.ex_date.localeCompare(b.ex_date));
  const labels = sorted.map(d => d.ex_date);
  const values = sorted.map(d => d.dividend);

  return new Chart(canvas.getContext('2d'), {
    type: 'bar',
    data: {
      labels,
      datasets: [{
        label: '每股配息',
        data: values,
        backgroundColor: 'rgba(52, 211, 153, 0.6)',
        borderColor: 'rgb(16, 185, 129)',
        borderWidth: 1,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: ctx => `$${ctx.parsed.y.toFixed(4)}`,
          },
        },
      },
      scales: {
        x: {
          ticks: {
            color: '#64748b',
            font: { size: 10 },
            maxRotation: 45,
            autoSkipPadding: 10,
          },
          grid: { display: false },
        },
        y: {
          ticks: { color: '#64748b', font: { size: 10 } },
          grid: { color: 'rgba(100, 116, 139, 0.1)' },
        },
      },
    },
  });
}
