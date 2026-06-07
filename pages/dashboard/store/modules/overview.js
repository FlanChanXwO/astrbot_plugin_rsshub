import { getDashboardCharts, getStats } from '../../js/api.js';

const CHART_COLORS = {
  orange: '#f59e0b',
  red: '#ef4444',
  amber: '#eab308',
  teal: '#0f766e',
  blue: '#2563eb',
  slate: '#64748b',
  green: '#16a34a',
};

const FEED_HEALTH_LABELS = {
  healthy: '健康',
  warning: '需关注',
  stale: '陈旧',
  disabled: '未启用',
};

const FEED_SHARE_COLORS = [
  '#f59e0b',
  '#f97316',
  '#eab308',
  '#0f766e',
  '#2563eb',
  '#dc2626',
  '#7c3aed',
  '#0891b2',
  '#94a3b8',
];

const chartInstances = {};

const doughnutLabelPlugin = {
  id: 'rsshubDoughnutLabels',
  afterDatasetsDraw(chart) {
    if (chart.config.type !== 'doughnut') return;
    const dataset = chart.data.datasets[0];
    const meta = chart.getDatasetMeta(0);
    const total = dataset.data.reduce((sum, value) => sum + Number(value || 0), 0);
    if (!total) return;
    const { ctx, chartArea } = chart;
    ctx.save();
    ctx.font = '12px system-ui, -apple-system, BlinkMacSystemFont, sans-serif';
    ctx.lineWidth = 1;
    meta.data.forEach((arc, index) => {
      const value = Number(dataset.data[index] || 0);
      if (!value || value / total < 0.04) return;
      const props = arc.getProps(['startAngle', 'endAngle', 'outerRadius', 'x', 'y'], true);
      const angle = (props.startAngle + props.endAngle) / 2;
      const color = dataset.backgroundColor[index];
      const startX = props.x + Math.cos(angle) * (props.outerRadius + 4);
      const startY = props.y + Math.sin(angle) * (props.outerRadius + 4);
      const midX = props.x + Math.cos(angle) * (props.outerRadius + 24);
      const midY = props.y + Math.sin(angle) * (props.outerRadius + 24);
      const rightSide = Math.cos(angle) >= 0;
      const endX = midX + (rightSide ? 22 : -22);
      const label = String(chart.data.labels[index] || '');
      const boundedX = Math.max(chartArea.left + 4, Math.min(chartArea.right - 4, endX));
      ctx.strokeStyle = color;
      ctx.fillStyle = color;
      ctx.beginPath();
      ctx.moveTo(startX, startY);
      ctx.lineTo(midX, midY);
      ctx.lineTo(boundedX, midY);
      ctx.stroke();
      ctx.textAlign = rightSide ? 'left' : 'right';
      ctx.textBaseline = 'middle';
      ctx.fillText(label.length > 22 ? `${label.slice(0, 21)}...` : label, boundedX + (rightSide ? 5 : -5), midY);
    });
    ctx.restore();
  },
};

function chartTextColor() {
  return document.documentElement.dataset.theme === 'dark' ? '#cbd5e1' : '#475569';
}

function chartGridColor() {
  return document.documentElement.dataset.theme === 'dark' ? 'rgba(148, 163, 184, 0.22)' : 'rgba(148, 163, 184, 0.24)';
}

function formatBucketLabel(value, unit) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value || '');
  if (unit === 'hour') {
    return `${String(date.getMonth() + 1).padStart(2, '0')}/${String(date.getDate()).padStart(2, '0')} ${String(date.getHours()).padStart(2, '0')}:00`;
  }
  return `${String(date.getMonth() + 1).padStart(2, '0')}/${String(date.getDate()).padStart(2, '0')}`;
}

function percentLabel(value) {
  if (value === null || value === undefined) return '无终态记录';
  return `${Math.round(Number(value) * 1000) / 10}%`;
}

function destroyChart(instance) {
  if (!instance || typeof instance.destroy !== 'function') return;
  instance.destroy();
}

function getChartCtor() {
  return typeof window !== 'undefined' ? window.Chart : null;
}

export const overviewModule = {
  async loadOverview(resetStats = false) {
    this.overviewChartsLoading = true;
    try {
      const [statsResult, chartResult] = await Promise.all([
        getStats(),
        getDashboardCharts(this.overviewRange),
      ]);
      this.stats = statsResult.stats || this.stats;
      this.overviewCharts = {
        ...this.overviewCharts,
        ...chartResult,
      };
      if (resetStats) this.feedShareLegendPage = 1;
      this.renderOverviewChartsSoon();
    } catch (err) {
      this.showToast(`概览加载失败: ${err.message}`, 'error');
    } finally {
      this.overviewChartsLoading = false;
    }
  },

  async setOverviewRange(range) {
    if (this.overviewRange === range) return;
    this.overviewRange = range;
    this.feedShareLegendPage = 1;
    await this.runPending('overview:refresh', () => this.loadOverview(true));
  },

  renderOverviewChartsSoon() {
    window.requestAnimationFrame(() => this.renderOverviewCharts());
  },

  renderOverviewCharts() {
    if (this.activeTab !== 'overview') return;
    const ChartCtor = getChartCtor();
    if (!ChartCtor) {
      this.showToast('Chart.js 未加载，无法绘制概览图表', 'error');
      return;
    }
    if (!ChartCtor.registry.plugins.get('rsshubDoughnutLabels')) {
      ChartCtor.register(doughnutLabelPlugin);
    }
    this.renderPushSuccessChart(ChartCtor);
    this.renderFeedHealthChart(ChartCtor);
    this.renderFeedShareChart(ChartCtor);
  },

  renderPushSuccessChart(ChartCtor) {
    const canvas = document.getElementById('overview-push-success-chart');
    if (!canvas) return;
    destroyChart(chartInstances.pushSuccess);
    const data = this.overviewCharts.push_success || { points: [], unit: 'day' };
    const points = data.points || [];
    const labels = points.map((item) => formatBucketLabel(item.bucket, data.unit));
    const rates = points.map((item) => (item.rate === null || item.rate === undefined ? null : Number(item.rate) * 100));
    chartInstances.pushSuccess = new ChartCtor(canvas, {
      type: 'line',
      data: {
        labels,
        datasets: [
          {
            label: '推送成功率',
            data: rates,
            borderColor: CHART_COLORS.teal,
            backgroundColor: 'rgba(15, 118, 110, 0.12)',
            borderWidth: 2,
            tension: 0.32,
            spanGaps: false,
            pointRadius: 2,
            pointHoverRadius: 4,
            fill: true,
          },
        ],
      },
      options: this.lineChartOptions(points),
    });
  },

  renderFeedHealthChart(ChartCtor) {
    const canvas = document.getElementById('overview-feed-health-chart');
    if (!canvas) return;
    destroyChart(chartInstances.feedHealth);
    const buckets = this.feedHealthBuckets();
    chartInstances.feedHealth = new ChartCtor(canvas, {
      type: 'bar',
      data: {
        labels: buckets.map((item) => item.label),
        datasets: [
          {
            label: 'Feed 数量',
            data: buckets.map((item) => item.count),
            backgroundColor: buckets.map((item) => item.color),
            borderRadius: 6,
            maxBarThickness: 46,
          },
        ],
      },
      options: this.barChartOptions(),
    });
  },

  renderFeedShareChart(ChartCtor) {
    const canvas = document.getElementById('overview-feed-share-chart');
    if (!canvas) return;
    destroyChart(chartInstances.feedShare);
    const items = this.feedShareItems();
    chartInstances.feedShare = new ChartCtor(canvas, {
      type: 'doughnut',
      data: {
        labels: items.map((item) => item.title),
        datasets: [
          {
            data: items.map((item) => item.count),
            backgroundColor: items.map((_, index) => FEED_SHARE_COLORS[index % FEED_SHARE_COLORS.length]),
            borderColor: document.documentElement.dataset.theme === 'dark' ? '#0f172a' : '#ffffff',
            borderWidth: 3,
            hoverOffset: 6,
          },
        ],
      },
      options: this.doughnutChartOptions(items),
    });
  },

  lineChartOptions(points) {
    return {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (ctx) => {
              const point = points[ctx.dataIndex] || {};
              return [
                `成功率: ${percentLabel(point.rate)}`,
                `success ${point.success || 0} / failed ${point.failed || 0} / skipped ${point.skipped || 0}`,
                `pending ${point.pending || 0} / stopped ${point.stopped || 0}`,
              ];
            },
          },
        },
      },
      scales: {
        x: { ticks: { color: chartTextColor(), maxRotation: 0, autoSkip: true }, grid: { color: chartGridColor() } },
        y: { min: 0, max: 100, ticks: { color: chartTextColor(), callback: (value) => `${value}%` }, grid: { color: chartGridColor() } },
      },
    };
  },

  barChartOptions() {
    return {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: (ctx) => `Feed 数量: ${ctx.parsed.y}` } },
      },
      scales: {
        x: { ticks: { color: chartTextColor() }, grid: { display: false } },
        y: { beginAtZero: true, ticks: { color: chartTextColor(), precision: 0 }, grid: { color: chartGridColor() } },
      },
    };
  },

  doughnutChartOptions(items) {
    return {
      responsive: true,
      maintainAspectRatio: false,
      cutout: '58%',
      layout: { padding: { left: 28, right: 56, top: 20, bottom: 20 } },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (ctx) => {
              const item = items[ctx.dataIndex] || {};
              return `${item.title}: ${item.count || 0} 个订阅 (${percentLabel(item.ratio || 0)})`;
            },
          },
        },
      },
    };
  },

  destroyOverviewCharts() {
    destroyChart(chartInstances.pushSuccess);
    destroyChart(chartInstances.feedHealth);
    destroyChart(chartInstances.feedShare);
    chartInstances.pushSuccess = null;
    chartInstances.feedHealth = null;
    chartInstances.feedShare = null;
  },

  feedHealthBuckets() {
    const raw = this.overviewCharts.feed_health?.buckets || [];
    const colors = {
      healthy: CHART_COLORS.green,
      warning: CHART_COLORS.amber,
      stale: CHART_COLORS.red,
      disabled: CHART_COLORS.slate,
    };
    return ['healthy', 'warning', 'stale', 'disabled'].map((status) => {
      const match = raw.find((item) => item.status === status);
      return {
        status,
        label: FEED_HEALTH_LABELS[status] || status,
        count: Number(match?.count || 0),
        color: colors[status],
      };
    });
  },

  feedShareItems() {
    return this.overviewCharts.feed_share?.items || [];
  },

  feedShareLegendItems() {
    const pageSize = 8;
    const start = (this.feedShareLegendPage - 1) * pageSize;
    return this.feedShareItems().slice(start, start + pageSize);
  },

  feedShareLegendTotalPages() {
    return Math.max(1, Math.ceil(this.feedShareItems().length / 8));
  },

  setFeedShareLegendPage(page) {
    const next = Math.max(1, Math.min(this.feedShareLegendTotalPages(), page));
    this.feedShareLegendPage = next;
  },

  feedShareColor(index) {
    const globalIndex = (this.feedShareLegendPage - 1) * 8 + index;
    return FEED_SHARE_COLORS[globalIndex % FEED_SHARE_COLORS.length];
  },

  feedSharePercent(item) {
    return percentLabel(item?.ratio || 0);
  },
};
