import assert from 'node:assert/strict';
import test from 'node:test';

import {
  buildPushSuccessDataset,
  createPushSuccessLineChartOptions,
  formatBucketLabel,
} from '../../pages/dashboard/store/modules/charts.js';

test('推送成功率折线图会连接有数据的历史节点', () => {
  const points = [
    { bucket: '2026-06-11T00:00:00Z', rate: 0.89 },
    { bucket: '2026-06-12T00:00:00Z', rate: null },
    { bucket: '2026-06-15T00:00:00Z', rate: 1 },
    { bucket: '2026-06-16T00:00:00Z', rate: 0.94 },
  ];

  const dataset = buildPushSuccessDataset(points);

  assert.deepEqual(dataset.data, [89, null, 100, 94]);
  assert.equal(dataset.spanGaps, true);
});

test('推送成功率折线图为坐标轴和顶部点保留舒展空间', () => {
  const options = createPushSuccessLineChartOptions([]);

  assert.deepEqual(options.layout.padding, { top: 18, right: 16, bottom: 8, left: 4 });
  assert.equal(options.scales.y.suggestedMax, 100);
  assert.equal(options.scales.y.grace, '8%');
  assert.equal(options.elements?.line?.spanGaps, undefined);
});

test('时间桶标签按日展示，避免横轴过度拥挤', () => {
  assert.equal(formatBucketLabel('2026-06-16T00:00:00Z', 'day'), '06/16');
});
