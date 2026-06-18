export const CHART_COLORS = {
  orange: '#f59e0b',
  red: '#ef4444',
  amber: '#eab308',
  teal: '#0f766e',
  blue: '#2563eb',
  slate: '#64748b',
  green: '#16a34a',
};

export function chartTextColor() {
  return currentTheme() === 'dark' ? '#cbd5e1' : '#475569';
}

export function chartGridColor() {
  return currentTheme() === 'dark' ? 'rgba(148, 163, 184, 0.22)' : 'rgba(148, 163, 184, 0.24)';
}

function currentTheme() {
  return typeof document === 'undefined' ? 'light' : document.documentElement.dataset.theme;
}

export function formatBucketLabel(value, unit) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value || '');
  if (unit === 'hour') {
    return `${String(date.getMonth() + 1).padStart(2, '0')}/${String(date.getDate()).padStart(2, '0')} ${String(date.getHours()).padStart(2, '0')}:00`;
  }
  return `${String(date.getMonth() + 1).padStart(2, '0')}/${String(date.getDate()).padStart(2, '0')}`;
}

export function percentLabel(value) {
  if (value === null || value === undefined) return '无终态记录';
  return `${Math.round(Number(value) * 1000) / 10}%`;
}

export function buildPushSuccessDataset(points) {
  return {
    label: '推送成功率',
    data: points.map((item) => (item.rate === null || item.rate === undefined ? null : Number(item.rate) * 100)),
    borderColor: CHART_COLORS.teal,
    backgroundColor: 'rgba(15, 118, 110, 0.12)',
    borderWidth: 2.5,
    tension: 0.28,
    // 空桶表示该时段没有终态历史，不应切断相邻真实历史点的趋势线。
    spanGaps: true,
    pointRadius: 3,
    pointHoverRadius: 5,
    pointHitRadius: 10,
    fill: true,
  };
}

export function createPushSuccessLineChartOptions(points) {
  return {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { mode: 'index', intersect: false },
    layout: { padding: { top: 18, right: 16, bottom: 8, left: 4 } },
    plugins: {
      legend: { display: false },
      tooltip: {
        callbacks: {
          label: (ctx) => {
            const point = points[ctx.dataIndex] || {};
            return [
              `成功率: ${percentLabel(point.rate)}`,
              `计入: success ${point.success || 0} / failed ${point.failed || 0}`,
              `参考: skipped ${point.skipped || 0} / pending ${point.pending || 0} / stopped ${point.stopped || 0}`,
            ];
          },
        },
      },
    },
    scales: {
      x: {
        offset: true,
        ticks: {
          color: chartTextColor(),
          maxRotation: 0,
          autoSkip: true,
          maxTicksLimit: 8,
          padding: 8,
        },
        grid: { color: chartGridColor() },
      },
      y: {
        min: 0,
        suggestedMax: 100,
        grace: '8%',
        ticks: {
          color: chartTextColor(),
          callback: (value) => `${value}%`,
          padding: 8,
        },
        grid: { color: chartGridColor() },
      },
    },
  };
}
