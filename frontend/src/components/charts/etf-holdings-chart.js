// ETF 持股相關圖表：前 10 大持股長條 + 產業分布圓餅。

const SECTOR_LABELS_ZH = {
  technology: '科技',
  financial_services: '金融',
  consumer_cyclical: '非必需消費',
  consumer_defensive: '必需消費',
  communication_services: '通訊服務',
  industrials: '工業',
  basic_materials: '原物料',
  energy: '能源',
  utilities: '公用事業',
  healthcare: '醫療保健',
  realestate: '不動產',
};

const SECTOR_COLORS = [
  '#10b981', '#3b82f6', '#f59e0b', '#ec4899', '#8b5cf6',
  '#06b6d4', '#84cc16', '#ef4444', '#a78bfa', '#f97316',
  '#14b8a6',
];

export function renderEtfHoldingsChart(canvas, holdings) {
  if (!holdings?.length) return null;
  const sorted = [...holdings].sort((a, b) => (a.rank || 99) - (b.rank || 99));
  const labels = sorted.map(h => `${h.constituent.replace('.TW', '')}`);
  const weights = sorted.map(h => (h.weight || 0) * 100);

  return new Chart(canvas.getContext('2d'), {
    type: 'bar',
    data: {
      labels,
      datasets: [{
        label: '權重 %',
        data: weights,
        backgroundColor: 'rgba(59, 130, 246, 0.6)',
        borderColor: 'rgb(37, 99, 235)',
        borderWidth: 1,
      }],
    },
    options: {
      indexAxis: 'y',
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: ctx => {
              const h = sorted[ctx.dataIndex];
              return `${h.name || h.constituent}: ${ctx.parsed.x.toFixed(2)}%`;
            },
          },
        },
      },
      scales: {
        x: {
          ticks: { color: '#64748b', font: { size: 10 }, callback: v => v + '%' },
          grid: { color: 'rgba(100, 116, 139, 0.1)' },
        },
        y: {
          ticks: { color: '#cbd5e1', font: { size: 10 } },
          grid: { display: false },
        },
      },
    },
  });
}

export function renderEtfSectorChart(canvas, sectors) {
  if (!sectors?.length) return null;
  const sorted = [...sectors].filter(s => s.weight > 0).sort((a, b) => b.weight - a.weight);
  const labels = sorted.map(s => SECTOR_LABELS_ZH[s.sector] || s.sector);
  const values = sorted.map(s => s.weight * 100);

  return new Chart(canvas.getContext('2d'), {
    type: 'doughnut',
    data: {
      labels,
      datasets: [{
        data: values,
        backgroundColor: SECTOR_COLORS.slice(0, sorted.length),
        borderColor: '#0f172a',
        borderWidth: 2,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      cutout: '50%',
      plugins: {
        legend: {
          position: 'right',
          labels: { color: '#cbd5e1', font: { size: 10 }, boxWidth: 12, padding: 6 },
        },
        tooltip: {
          callbacks: {
            label: ctx => `${ctx.label}: ${ctx.parsed.toFixed(2)}%`,
          },
        },
      },
    },
  });
}
