// 綜合評分甜甜圈圖。

export function renderScoreDonut(canvas, value, color) {
  const ctx = canvas.getContext('2d');
  return new Chart(ctx, {
    type: 'doughnut',
    data: {
      datasets: [{
        data: [value, 100 - value],
        backgroundColor: [color, '#1e293b'],
        borderWidth: 0,
        cutout: '78%',
      }],
    },
    options: {
      responsive: true, maintainAspectRatio: true,
      animation: { duration: 600, easing: 'easeOutQuart' },
      plugins: { legend: { display: false }, tooltip: { enabled: false } },
    },
  });
}
