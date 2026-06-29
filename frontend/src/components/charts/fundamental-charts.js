// 基本面圖表：年營收 YoY、股利歷史、PE 河流圖。
// 每個函式回傳 Chart instance（無資料時回傳 null）。

export function renderAnnualGrowth(canvas, annualRevenueGrowth) {
  if (!annualRevenueGrowth?.length) return null;
  const sorted = [...annualRevenueGrowth].sort((a, b) => a.year - b.year);
  const labels = sorted.map(r => String(r.year));
  const yoys = sorted.map(r => r.yoy_pct ?? null);
  const ctx = canvas.getContext('2d');
  return new Chart(ctx, {
    type: 'bar',
    data: { labels, datasets: [{
      data: yoys, label: 'YoY %',
      backgroundColor: yoys.map(v => v == null ? '#475569' : v >= 0 ? 'rgba(34,197,94,.7)' : 'rgba(239,68,68,.7)'),
      borderWidth: 0,
    }]},
    options: { responsive: true, maintainAspectRatio: false, animation: { duration: 300 },
      scales: {
        x: { grid: { display: false }, ticks: { color: '#64748b', font: { size: 10 } }, border: { color: '#334155' } },
        y: { position: 'right', grid: { color: '#1e293b80' }, ticks: { color: '#64748b', font: { size: 10 }, callback: v => v + '%' }, border: { color: '#334155' } },
      },
      plugins: { legend: { display: false },
        tooltip: { callbacks: { label: i => `  YoY: ${i.raw != null ? i.raw.toFixed(2) + '%' : '–'}` }, backgroundColor: '#0f172a', borderColor: '#334155', borderWidth: 1, bodyColor: '#94a3b8', padding: 8 } }
    }
  });
}

export function renderDividendHistory(canvas, history) {
  if (!history?.length) return null;
  const labels = history.map(r => String(r.year));
  const amounts = history.map(r => r.amount);
  const ctx = canvas.getContext('2d');
  return new Chart(ctx, {
    type: 'bar',
    data: { labels, datasets: [{ data: amounts, backgroundColor: 'rgba(16,185,129,.7)', borderWidth: 0 }] },
    options: { responsive: true, maintainAspectRatio: false, animation: { duration: 300 },
      scales: {
        x: { grid: { display: false }, ticks: { color: '#64748b', font: { size: 10 } }, border: { color: '#334155' } },
        y: { position: 'right', grid: { color: '#1e293b80' }, ticks: { color: '#64748b', font: { size: 10 }, callback: v => '$' + v }, border: { color: '#334155' } },
      },
      plugins: { legend: { display: false },
        tooltip: { callbacks: { label: i => `  $${i.raw}` }, backgroundColor: '#0f172a', borderColor: '#334155', borderWidth: 1, bodyColor: '#94a3b8', padding: 8 } }
    }
  });
}

export function renderPeHistory(canvas, peHist) {
  if (!peHist?.labels || !peHist?.series) return null;
  const labels = peHist.labels;
  const series = peHist.series;
  const median = Array(labels.length).fill(peHist.median);
  const p25 = Array(labels.length).fill(peHist.p25);
  const p75 = Array(labels.length).fill(peHist.p75);
  const ctx = canvas.getContext('2d');
  return new Chart(ctx, {
    type: 'line',
    data: { labels, datasets: [
      { label: 'P75', data: p75, borderColor: 'rgba(148,163,184,.25)', borderWidth: 1, pointRadius: 0, fill: false, borderDash: [3,3] },
      { label: 'P25', data: p25, borderColor: 'rgba(148,163,184,.25)', borderWidth: 1, pointRadius: 0, fill: '-1', backgroundColor: 'rgba(148,163,184,.06)', borderDash: [3,3] },
      { label: 'Median', data: median, borderColor: 'rgba(148,163,184,.5)', borderWidth: 1, pointRadius: 0, fill: false, borderDash: [5,3] },
      { label: 'PE', data: series, borderColor: '#a78bfa', borderWidth: 1.5, pointRadius: 0, tension: 0.3, spanGaps: true, fill: false },
    ]},
    options: { responsive: true, maintainAspectRatio: false, animation: { duration: 300 },
      scales: {
        x: { grid: { color: '#1e293b' }, ticks: { color: '#64748b', font: { size: 9 }, maxRotation: 0, callback: (v, i) => i % 12 === 0 ? labels[i] : '' }, border: { color: '#334155' } },
        y: { position: 'right', grid: { color: '#1e293b80' }, ticks: { color: '#64748b', font: { size: 10 } }, border: { color: '#334155' } },
      },
      plugins: { legend: { display: false },
        tooltip: { callbacks: { label: i => `  ${i.dataset.label}: ${i.raw != null ? i.raw.toFixed(1) : '–'}` }, backgroundColor: '#0f172a', borderColor: '#334155', borderWidth: 1, bodyColor: '#94a3b8', padding: 8 } }
    }
  });
}
