import assert from 'node:assert/strict';
import test from 'node:test';

import { deleteTemplate, getBundles, getTemplateOptions } from '../../pages/dashboard/js/api.js';
import { bundlesPageTemplate } from '../../pages/dashboard/components/pages/bundles.js';
import { pushHistoryPageTemplate } from '../../pages/dashboard/components/pages/push-history.js';
import { mainPanelTemplate } from '../../pages/dashboard/components/overlays/main-panel.js';
import { bundlesModule } from '../../pages/dashboard/store/modules/bundles.js';
import {
  safeTemplateRepositoryUrl,
  templatesModule,
} from '../../pages/dashboard/store/modules/templates.js';
import { pushHistoryModule } from '../../pages/dashboard/store/modules/push-history.js';
import { subscriptionsModule } from '../../pages/dashboard/store/modules/subscriptions.js';

test('Bundle 页面 API 按后端契约查询列表和严格模板候选', async () => {
  const calls = [];
  globalThis.window = {
    AstrBotPluginPage: {
      async apiGet(path, params) {
        calls.push({ path, params });
        if (path === 'bundles') {
          return { ok: true, items: [{ id: 7 }], total: 1, page: 1, page_size: 20 };
        }
        return { ok: true, items: [{ id: 'astrbot_plugin_rsshub_card_bundle' }], total: 1 };
      },
    },
  };

  const bundles = await getBundles({ userId: 'owner-1', keyword: 'daily' });
  const options = await getTemplateOptions('bundle', 7, 'owner-1');

  assert.deepEqual(bundles, {
    items: [{ id: 7 }],
    total: 1,
    page: 1,
    page_size: 20,
  });
  assert.deepEqual(options, {
    items: [{ id: 'astrbot_plugin_rsshub_card_bundle' }],
    total: 1,
  });
  assert.deepEqual(calls, [
    {
      path: 'bundles',
      params: { user_id: 'owner-1', keyword: 'daily', page: 1, page_size: 20 },
    },
    {
      path: 'templates/options',
      params: { owner_type: 'bundle', owner_id: 7, user_id: 'owner-1' },
    },
  ]);
});

test('Bundle 列表加载失败时保留可重试的页面错误状态', async () => {
  globalThis.window = {
    AstrBotPluginPage: {
      async apiGet() {
        throw new Error('网络不可用');
      },
    },
  };
  const store = {
    bundleFilters: { keyword: '', userId: '' },
    bundlePagination: { page: 1, pageSize: 20 },
    bundlesLoading: false,
    bundleLoadError: '',
    bundles: [],
    bundlesTotal: 0,
    showToast() {},
    ...bundlesModule,
  };

  await store.loadBundles();

  assert.equal(store.bundlesLoading, false);
  assert.equal(store.bundleLoadError, '网络不可用');
});

test('模板页面安装 HTTP URL 前必须确认风险并传递明文确认标记', async () => {
  const calls = [];
  globalThis.window = {
    AstrBotPluginPage: {
      async apiPost(path, payload) {
        calls.push({ path, payload });
        return { ok: true, template: { id: 'installed' } };
      },
      async apiGet() {
        return { ok: true, items: [], total: 0 };
      },
    },
  };
  const store = {
    templateInstallUrl: 'http://templates.example/card.zip',
    templateInstallError: '',
    templates: [],
    templatesTotal: 0,
    templatesLoading: false,
    showConfirm: async (message) => {
      assert.match(message, /HTTP/);
      return true;
    },
    showToast() {},
    runPending: async (_key, action) => await action(),
    ...templatesModule,
  };

  await store.installTemplateFromPage();

  assert.deepEqual(calls, [
    {
      path: 'templates/install',
      payload: {
        url: 'http://templates.example/card.zip',
        allow_insecure_http: true,
      },
    },
  ]);
});

test('推送历史按 batch 分组并按 output_order 展示批次输出', () => {
  const store = {
    pushHistory: [
      {
        id: 3,
        batch_id: 9,
        bundle_id: 4,
        output_order: 2,
        output_kind: 'standard',
        status: 'waiting',
        source_context: { bundle: { id: 4 }, feeds: [{ id: 1 }, { id: 2 }] },
      },
      {
        id: 2,
        batch_id: 9,
        bundle_id: 4,
        output_order: 0,
        output_kind: 'card',
        status: 'success',
        source_context: { bundle: { id: 4 }, feeds: [{ id: 1 }, { id: 2 }] },
      },
      { id: 1, status: 'success' },
    ],
    ...pushHistoryModule,
  };

  const groups = store.pushHistoryGroups();

  assert.deepEqual(groups.map((group) => group.key), ['batch:9', 'history:1']);
  assert.deepEqual(groups[0].items.map((item) => item.id), [2, 3]);
  assert.equal(groups[0].batchId, 9);
  assert.equal(groups[0].bundleId, 4);
  assert.equal(groups[0].memberCount, 2);
  assert.equal(groups[0].hasUnresolvedOutput, true);
});

test('推送历史详情展示批次快照、输入输出 XML 和输出顺序', () => {
  assert.match(mainPanelTemplate, /historyDetail\?\.batch_id/);
  assert.match(mainPanelTemplate, /historyDetail\?\.output_order/);
  assert.match(mainPanelTemplate, /historyDetail\?\.template_snapshot/);
  assert.match(mainPanelTemplate, /historyDetail\?\.document_snapshot/);
  assert.match(mainPanelTemplate, /historyDetail\?\.input_xml/);
  assert.match(mainPanelTemplate, /historyDetail\?\.input_xmls/);
  assert.match(mainPanelTemplate, /historyDetail\?\.output_xml/);
  assert.match(mainPanelTemplate, /historyDetail\?\.source_context/);
  assert.match(pushHistoryPageTemplate, /group\.template\.metadata/);
});

test('关闭推送历史详情后不读取空的 handler trace', () => {
  assert.match(mainPanelTemplate, /historyDetail\?\.handler_trace/);
});

test('状态筛选只返回批次成功输出时仍保留 pending 批次保护', () => {
  const store = {
    pushHistory: [
      { id: 8, batch_id: 12, batch_status: 'pending', status: 'success' },
    ],
    ...pushHistoryModule,
  };

  assert.equal(store.pushHistoryGroups()[0].hasUnresolvedOutput, true);
});

test('卡片预览只有在开启卡片且选择严格候选后可用', () => {
  const store = {
    editForm: {
      send_card: false,
      template_id: '',
      template_options: [],
    },
    ...subscriptionsModule,
  };

  assert.equal(store.subscriptionCardConfigurationValid(), true);
  assert.equal(store.subscriptionPreviewConfigurationValid(), false);

  store.editForm.send_card = true;
  assert.equal(store.subscriptionCardConfigurationValid(), false);
  store.editForm.template_id = 'template-1';
  store.editForm.template_options = [{ id: 'template-1' }];
  assert.equal(store.subscriptionPreviewConfigurationValid(), true);
});

test('订阅模板候选加载时不应复用旧的选择器', () => {
  const store = {
    editForm: { template_options_loading: true },
    ...subscriptionsModule,
  };

  assert.equal(store.subscriptionTemplateOptionsReady(), false);
  store.editForm.template_options_loading = false;
  assert.equal(store.subscriptionTemplateOptionsReady(), true);
});

test('Web API 的模板冲突错误会保留 error_code 和 details 供页面展示', async () => {
  globalThis.window = {
    AstrBotPluginPage: {
      async apiPost() {
        return {
          ok: false,
          error: '模板正在被引用',
          error_code: 'CARD_TEMPLATE_IN_USE',
          details: [{ owner_type: 'bundle', owner_id: 7 }],
        };
      },
    },
  };

  await assert.rejects(deleteTemplate('template-1'), (error) => {
    assert.equal(error.code, 'CARD_TEMPLATE_IN_USE');
    assert.deepEqual(error.details, [{ owner_type: 'bundle', owner_id: 7 }]);
    return true;
  });
});

test('模板仓库链接只允许 HTTP(S) 协议', () => {
  assert.equal(safeTemplateRepositoryUrl('https://example.com/repo'), 'https://example.com/repo');
  assert.equal(safeTemplateRepositoryUrl('http://example.com/repo'), 'http://example.com/repo');
  assert.equal(safeTemplateRepositoryUrl('javascript:alert(1)'), '');
  assert.equal(safeTemplateRepositoryUrl('data:text/html,<script>alert(1)</script>'), '');
});

test('预览抽屉卸载期间的绑定必须允许预览对象暂时为空', () => {
  assert.match(bundlesPageTemplate, /bundlePreview\?\.src/);
  assert.match(bundlesPageTemplate, /bundlePreview\?\.entryCount/);
  assert.match(mainPanelTemplate, /editForm\.card_preview\?\.src/);
  assert.match(mainPanelTemplate, /editForm\.card_preview\?\.entryCount/);
});
