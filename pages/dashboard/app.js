import {
  ready,
  getSubscriptions,
  unsubscribe,
  updateSubscription,
  getFeedItems,
  refreshFeed,
  refreshFeeds,
  testSubscription,
  batchActivate,
  batchDeactivate,
  batchUnsubscribe,
  getStats,
  checkUpdates,
  getPluginSettings,
  getHandlers,
  setPluginSettings,
  getFeeds,
  getPushHistory,
  getRouteKbStatus,
  syncRouteKb,
  getRouteKbTask,
  deletePushHistory,
  deletePushHistoryBatch,
  cleanupPushHistory,
  clearPushHistory,
  getUserDetails,
  updateUser,
  deleteUser,
  deleteUsers,
  getDataManagementOverview,
  getDataManagementExports,
  clearDataManagementCache,
  clearDataManagementExports,
  deleteDataManagementExport,
  getDataManagementExportContent,
} from './js/api.js';
import { initTheme } from './js/theme.js';

let toastTimer = null;
let routeKbPollTimer = null;

function normalizeUserState(state) {
  return Number(state) < 0 ? -1 : 1;
}

function formatUserState(state) {
  return normalizeUserState(state) < 0 ? '已封禁' : '用户';
}

function formatDate(iso) {
  if (!iso) return '-';
  try {
    const d = new Date(iso);
    return d.toLocaleString('zh-CN', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
  } catch {
    return iso;
  }
}

function formatBytes(value) {
  const bytes = Number(value) || 0;
  if (bytes <= 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  const exponent = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const size = bytes / 1024 ** exponent;
  return `${size.toFixed(size >= 100 || exponent === 0 ? 0 : size >= 10 ? 1 : 2)} ${units[exponent]}`;
}

function prettyJson(value) {
  if (value === undefined) return '';
  if (typeof value === 'string') return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value ?? '');
  }
}

function cloneJsonValue(value) {
  if (value === undefined || value === null) return value;
  if (typeof value !== 'object') return value;
  try {
    return JSON.parse(JSON.stringify(value));
  } catch {
    return Array.isArray(value) ? [...value] : { ...value };
  }
}

function normalizeHandlers(handlers) {
  if (!Array.isArray(handlers)) return [];
  return handlers
    .filter((item) => item && typeof item === 'object')
    .map((item) => ({
      id: String(item.id || '').trim(),
      type: String(item.type || 'builtin').trim() || 'builtin',
      name: String(item.name || '').trim(),
      status: Number.isFinite(Number(item.status)) ? Number(item.status) : -100,
      config: item.config && typeof item.config === 'object' ? { ...item.config } : {},
    }))
    .filter((item) => item.id && item.name);
}

function handlersToEditorState(handlers) {
  const normalized = normalizeHandlers(handlers);
  return {
    handlers: normalized,
    handlers_advanced: true,
    handlers_json: JSON.stringify(normalized, null, 2),
  };
}

function buildHandlersFromEditorState(form) {
  return normalizeHandlers(JSON.parse(form.handlers_json || '[]'));
}

function createEmptyEditForm() {
  return {
    id: 0,
    feed_id: 0,
    feed_title: '',
    feed_link: '',
    user_id: '',
    title: '',
    tags: '',
    target_session: '',
    interval: 10,
    notify: -100,
    state_: true,
    send_mode: -100,
    length_limit: -100,
    display_author: -100,
    display_via: -100,
    display_title: -100,
    display_entry_tags: -100,
    style: -100,
    display_media: -100,
    handlers_mode: 'inherit',
    handlers_json: '[]',
  };
}

function createEditFormFromSub(sub) {
  return {
    id: sub.id,
    feed_id: sub.feed_id,
    feed_title: sub.feed_title,
    feed_link: sub.feed_link,
    user_id: sub.user_id,
    title: sub.title || '',
    tags: sub.tags || '',
    target_session: sub.target_session || '',
    interval: sub.interval ?? -100,
    state_: sub.state === 1,
    notify: sub.notify ?? -100,
    send_mode: sub.send_mode ?? -100,
    length_limit: sub.length_limit ?? -100,
    display_author: sub.display_author ?? -100,
    display_via: sub.display_via ?? -100,
    display_title: sub.display_title ?? -100,
    display_entry_tags: sub.display_entry_tags ?? -100,
    style: sub.style ?? -100,
    display_media: sub.display_media ?? -100,
    handlers_mode: sub.handlers_mode || 'inherit',
    ...handlersToEditorState(sub.handlers),
  };
}

function createEmptyUserEditForm() {
  return {
    user_id: '',
    state: 1,
    interval: -100,
    notify: -100,
    send_mode: -100,
    length_limit: -100,
    display_author: -100,
    display_via: -100,
    display_title: -100,
    display_entry_tags: -100,
    style: -100,
    display_media: -100,
    default_target_session: '',
    handlers_json: '[]',
  };
}

function createDefaultDataOverview() {
  return {
    cache: {
      path: '',
      total_bytes: 0,
      file_count: 0,
      breakdown: [],
    },
    exports: {
      path: '',
      total_bytes: 0,
      file_count: 0,
      breakdown: [],
    },
    totals: {
      cache_bytes: 0,
      exports_bytes: 0,
      combined_bytes: 0,
    },
  };
}

function normalizeBreakdownItems(items) {
  if (!Array.isArray(items)) return [];
  return items
    .map((item, index) => ({
      key: String(item?.key || item?.name || item?.label || `item-${index}`),
      label: String(item?.label || item?.name || item?.key || `项目 ${index + 1}`),
      bytes:
        Number(item?.bytes ?? item?.size ?? item?.size_bytes ?? item?.total_bytes ?? 0) ||
        0,
      file_count: Number(item?.file_count ?? item?.count ?? 0) || 0,
    }))
    .filter((item) => item.bytes > 0);
}

function normalizeDataOverview(raw) {
  const overview = createDefaultDataOverview();
  const cache = raw?.cache || {};
  const exportsData = raw?.exports || {};
  const totals = raw?.totals || {};
  overview.cache = {
    path: String(cache.path || ''),
    total_bytes: Number(cache.total_bytes ?? cache.total_size ?? cache.bytes ?? 0) || 0,
    file_count: Number(cache.file_count ?? cache.count ?? 0) || 0,
    breakdown: normalizeBreakdownItems(cache.breakdown),
  };
  overview.exports = {
    path: String(exportsData.path || ''),
    total_bytes:
      Number(exportsData.total_bytes ?? exportsData.total_size ?? exportsData.bytes ?? 0) ||
      0,
    file_count: Number(exportsData.file_count ?? exportsData.count ?? 0) || 0,
    breakdown: normalizeBreakdownItems(exportsData.breakdown),
  };
  overview.totals = {
    cache_bytes: Number(totals.cache_bytes ?? overview.cache.total_bytes) || 0,
    exports_bytes: Number(totals.exports_bytes ?? overview.exports.total_bytes) || 0,
    combined_bytes:
      Number(
        totals.combined_bytes ??
          totals.total_size ??
          overview.cache.total_bytes + overview.exports.total_bytes
      ) || 0,
  };
  return overview;
}

function normalizeExportFile(item) {
  return {
    name: String(item?.name || item?.filename || ''),
    size_bytes: Number(item?.size_bytes ?? item?.size ?? item?.bytes ?? 0) || 0,
    modified_at: item?.modified_at || item?.mtime || null,
    path: item?.path || '',
  };
}

function normalizePushHistoryItem(item) {
  return {
    ...item,
    media_urls: Array.isArray(item?.media_urls) ? item.media_urls : [],
    handler_trace: Array.isArray(item?.handler_trace) ? item.handler_trace : [],
  };
}

function createEmptySubscriptionFilters() {
  return {
    user_id: '',
    feed_id: '',
    sub_id: '',
    keyword: '',
  };
}

function createEmptyUserFilters() {
  return {
    user_id: '',
    keyword: '',
  };
}

function createEmptyFeedFilters() {
  return {
    feed_id: '',
    keyword: '',
  };
}

function createEmptyPushHistoryFilters() {
  return {
    status: '',
    keyword: '',
    page: 1,
    pageSize: 20,
  };
}

function traceStatusText(step) {
  if (step?.allow === false) return '已过滤';
  return String(step?.status || step?.result || 'ok');
}

function traceReasonText(step) {
  return String(step?.reason || step?.message || step?.error || '').trim();
}

function pieSegments(items) {
  const palette = ['#3c96ca', '#34d399', '#f59e0b', '#ef4444', '#8b5cf6', '#14b8a6', '#64748b'];
  const normalized = normalizeBreakdownItems(items);
  const total = normalized.reduce((sum, item) => sum + item.bytes, 0);
  if (total <= 0) return [];
  let cursor = 0;
  return normalized.map((item, index) => {
    const ratio = item.bytes / total;
    const segment = {
      ...item,
      color: palette[index % palette.length],
      dashArray: `${Math.max(ratio * 100, 0)} ${Math.max(100 - ratio * 100, 0)}`,
      dashOffset: `${25 - cursor}`,
      percent: ratio * 100,
    };
    cursor += ratio * 100;
    return segment;
  });
}

function normalizeHandlerField(field) {
  const rawOptions = Array.isArray(field?.options) ? field.options : [];
  const options = rawOptions.map((item) => {
    if (item && typeof item === 'object') {
      return {
        label: String(item.label || item.name || item.value || '').trim(),
        value: String(item.value || item.label || item.name || '').trim(),
      };
    }
    const value = String(item || '').trim();
    return { label: value, value };
  }).filter((item) => item.value);
  return {
    key: String(field?.key || field?.name || '').trim(),
    type: String(field?.type || 'string').trim(),
    label: String(field?.label || field?.title || field?.key || field?.name || '').trim(),
    description: String(field?.description || '').trim(),
    required: Boolean(field?.required),
    default: cloneJsonValue(field?.default),
    options,
  };
}

function normalizeHandlerRegistryItem(item) {
  const fields = Array.isArray(item?.fields)
    ? item.fields
    : Array.isArray(item?.schema)
      ? item.schema
      : [];
  return {
    type: String(item?.type || 'builtin').trim() || 'builtin',
    name: String(item?.name || '').trim(),
    title: String(item?.display_name || item?.title || item?.name || '未命名处理器').trim(),
    description: String(item?.description || '').trim(),
    default_enabled: Boolean(item?.default_enabled),
    fields: fields.map(normalizeHandlerField).filter((field) => field.key),
  };
}

const store = PetiteVue.reactive({
  subs: [],
  filteredSubs: [],
  stats: {
    total_subscriptions: 0,
    active_subscriptions: 0,
    total_feeds: 0,
    unique_users: 0,
  },
  loading: true,
  subFilters: createEmptySubscriptionFilters(),
  editMode: false,
  selectedIds: [],
  subPagination: { page: 1, pageSize: 20 },

  panelVisible: false,
  panelExpanded: false,
  panelMode: 'detail',
  editForm: createEmptyEditForm(),
  detailSub: {},
  detailItems: [],
  historyDetail: null,
  exportPreview: null,

  activeTab: 'subs',
  users: [],
  userFilters: createEmptyUserFilters(),
  usersLoading: false,
  userEditMode: false,
  selectedUserIds: [],
  feeds: [],
  feedFilters: createEmptyFeedFilters(),
  feedsLoading: false,
  feedEditMode: false,
  selectedFeedIds: [],
  pluginSettingsLoading: false,
  dataManagementLoading: false,
  dataManagementOverview: createDefaultDataOverview(),
  exportFiles: [],
  subscriptionDefaults: {
    interval: 10,
    notify: true,
    send_mode: '自动',
    length_limit: 0,
    display_author: '自动',
    display_via: '自动',
    display_title: '自动',
    display_entry_tags: false,
    style: 'auto',
    display_media: true,
  },
  historyRetentionDays: 30,

  pushHistory: [],
  pushHistoryLoading: false,
  pushHistoryFilter: createEmptyPushHistoryFilters(),
  pushHistoryTotal: 0,
  pushHistoryEditMode: false,
  selectedPushHistoryIds: [],

  routeKbLoading: false,
  routeKbTask: null,
  routeKbStatus: null,
  handlersLoading: false,
  handlersRegistry: [],
  expandedHandlerName: '',

  userEditPanelVisible: false,
  userEditForm: createEmptyUserEditForm(),

  pendingActions: {},
  toast: { show: false, message: '', type: 'success' },
  dialog: {
    show: false,
    title: '',
    message: '',
    okText: '确定',
    okClass: 'btn-danger',
    resolve: null,
  },

  isPending(key) {
    return Boolean(this.pendingActions[key]);
  },

  async runPending(key, action) {
    if (this.isPending(key)) return null;
    this.pendingActions[key] = true;
    try {
      return await action();
    } finally {
      delete this.pendingActions[key];
    }
  },

  async openTab(tab) {
    this.syncBatchModesForTab(tab);
    this.activeTab = tab;
    const loaders = {
      subs: () => this.loadData(false),
      users: () => this.loadUsers(),
      feeds: () => this.loadFeeds(),
      'push-history': () => this.loadPushHistory(),
      'route-kb': () => this.loadRouteKbStatus(),
      handlers: () => this.loadHandlers(),
      settings: () => this.loadSettings(),
      'data-management': () => this.loadDataManagement(),
    };
    const loader = loaders[tab];
    if (!loader) return;
    await this.runPending(`tab:${tab}`, loader);
  },

  syncBatchModesForTab(tab) {
    if (tab !== 'subs') {
      this.editMode = false;
      this.selectedIds = [];
    }
    if (tab !== 'users') {
      this.userEditMode = false;
      this.selectedUserIds = [];
    }
    if (tab !== 'feeds') {
      this.feedEditMode = false;
      this.selectedFeedIds = [];
    }
    if (tab !== 'push-history') {
      this.pushHistoryEditMode = false;
      this.selectedPushHistoryIds = [];
    }
  },

  async loadData(resetPage = true) {
    this.loading = true;
    try {
      const [subResult, statsResult] = await Promise.all([
        getSubscriptions(this.subFilters),
        getStats(),
      ]);
      this.subs = subResult.items || [];
      this.stats = statsResult.stats || this.stats;
      this.filteredSubs = [...this.subs];
      if (resetPage) {
        this.resetSubPage();
        this.selectedIds = [];
      }
      this.clampSubPage();
    } catch (err) {
      this.showToast(`加载失败: ${err.message}`, 'error');
    } finally {
      this.loading = false;
    }
  },

  async loadUsers() {
    this.usersLoading = true;
    try {
      const result = await getUserDetails(this.userFilters);
      this.users = result.items || [];
      this.selectedUserIds = this.selectedUserIds.filter((id) =>
        this.users.some((item) => item.user_id === id)
      );
    } catch (err) {
      this.showToast(`加载用户失败: ${err.message}`, 'error');
    } finally {
      this.usersLoading = false;
    }
  },

  async openSubscriptionsWithFilter(filters = {}) {
    this.subFilters = {
      ...createEmptySubscriptionFilters(),
      ...Object.fromEntries(
        Object.entries(filters).map(([key, value]) => [key, value == null ? '' : String(value)])
      ),
    };
    this.activeTab = 'subs';
    await this.runPending('subs:refresh', () => this.loadData());
  },

  async selectUser(userId) {
    await this.openSubscriptionsWithFilter({ user_id: userId || '' });
  },

  async selectFeed(feedId) {
    await this.openSubscriptionsWithFilter({ feed_id: feedId || '' });
  },

  async selectSubscription(subId) {
    await this.openSubscriptionsWithFilter({ sub_id: subId || '' });
  },

  async loadFeeds() {
    this.feedsLoading = true;
    try {
      const result = await getFeeds(this.feedFilters);
      this.feeds = result.items || [];
      this.selectedFeedIds = this.selectedFeedIds.filter((id) =>
        this.feeds.some((item) => item.id === id)
      );
    } catch (err) {
      this.showToast(`加载 Feed 失败: ${err.message}`, 'error');
    } finally {
      this.feedsLoading = false;
    }
  },

  async loadSettings() {
    this.pluginSettingsLoading = true;
    try {
      const pluginResult = await getPluginSettings();
      if (pluginResult.history_retention_days !== undefined) {
        this.historyRetentionDays = Number(pluginResult.history_retention_days) || 30;
      }
      if (pluginResult.subscription_defaults) {
        this.subscriptionDefaults = {
          ...this.subscriptionDefaults,
          ...pluginResult.subscription_defaults,
        };
      }
    } catch (err) {
      this.showToast(`加载设置失败: ${err.message}`, 'error');
    } finally {
      this.pluginSettingsLoading = false;
    }
  },

  async loadPushHistory() {
    this.pushHistoryLoading = true;
    try {
      const pluginResult = await getPluginSettings();
      if (pluginResult.history_retention_days !== undefined) {
        this.historyRetentionDays = Number(pluginResult.history_retention_days) || 30;
      }
      const result = await getPushHistory({
        status: this.pushHistoryFilter.status,
        keyword: this.pushHistoryFilter.keyword,
        page: this.pushHistoryFilter.page,
        pageSize: this.pushHistoryFilter.pageSize,
      });
      this.pushHistory = (result.items || []).map(normalizePushHistoryItem);
      this.selectedPushHistoryIds = this.selectedPushHistoryIds.filter((id) =>
        this.pushHistory.some((item) => item.id === id)
      );
      this.pushHistoryTotal = result.total || 0;
      if (
        this.pushHistory.length === 0 &&
        this.pushHistoryTotal > 0 &&
        this.pushHistoryFilter.page > this.pushHistoryTotalPages()
      ) {
        this.pushHistoryFilter.page = this.pushHistoryTotalPages();
        await this.loadPushHistory();
      }
    } catch (err) {
      this.showToast(`加载推送历史失败: ${err.message}`, 'error');
    } finally {
      this.pushHistoryLoading = false;
    }
  },

  async loadRouteKbStatus() {
    this.routeKbLoading = true;
    try {
      const result = await getRouteKbStatus();
      this.routeKbStatus = result.status || null;
      this.routeKbTask = this.routeKbStatus ? this.routeKbStatus.task : null;
      this.syncRouteKbPollingState();
    } catch (err) {
      this.showToast(`加载知识库状态失败: ${err.message}`, 'error');
    } finally {
      this.routeKbLoading = false;
    }
  },

  async loadDataManagement() {
    this.dataManagementLoading = true;
    try {
      const [overviewResult, exportsResult] = await Promise.all([
        getDataManagementOverview(),
        getDataManagementExports(),
      ]);
      this.dataManagementOverview = normalizeDataOverview(overviewResult);
      this.exportFiles = (exportsResult.items || []).map(normalizeExportFile);
    } catch (err) {
      this.showToast(`加载数据管理信息失败: ${err.message}`, 'error');
    } finally {
      this.dataManagementLoading = false;
    }
  },

  async loadHandlers() {
    this.handlersLoading = true;
    try {
      const result = await getHandlers();
      this.handlersRegistry = (result.items || []).map(normalizeHandlerRegistryItem);
      if (
        this.expandedHandlerName &&
        !this.handlersRegistry.some((item) => item.name === this.expandedHandlerName)
      ) {
        this.expandedHandlerName = '';
      }
    } catch (err) {
      this.showToast(`加载处理器失败: ${err.message}`, 'error');
    } finally {
      this.handlersLoading = false;
    }
  },

  async savePluginSettings() {
    await this.runPending('plugin-settings:save', async () => {
      const result = await setPluginSettings({
        subscription_defaults: this.subscriptionDefaults,
        history_retention_days: this.historyRetentionDays,
      });
      if (result.history_retention_days !== undefined) {
        this.historyRetentionDays = Number(result.history_retention_days) || 30;
      }
      if (result.subscription_defaults) {
        this.subscriptionDefaults = {
          ...this.subscriptionDefaults,
          ...result.subscription_defaults,
        };
      }
      this.showToast(result.message || '插件设置已保存');
    }).catch((err) => {
      this.showToast(`保存插件设置失败: ${err.message}`, 'error');
    });
  },

  async applySubscriptionFilters() {
    await this.runPending('subs:refresh', () => this.loadData());
  },

  async applyUserFilters() {
    await this.runPending('users:refresh', () => this.loadUsers());
  },

  async clearUserFilters() {
    this.userFilters = createEmptyUserFilters();
    await this.runPending('users:refresh', () => this.loadUsers());
  },

  hasUserFilters() {
    return Object.values(this.userFilters).some((value) => String(value || '').trim() !== '');
  },

  userFilterSummary() {
    const parts = [];
    if (this.userFilters.user_id) parts.push(`用户: ${this.userFilters.user_id}`);
    if (this.userFilters.keyword) parts.push(`关键词: ${this.userFilters.keyword}`);
    return parts.join(' / ');
  },

  async applyFeedFilters() {
    await this.runPending('feeds:refresh', () => this.loadFeeds());
  },

  async clearFeedFilters() {
    this.feedFilters = createEmptyFeedFilters();
    await this.runPending('feeds:refresh', () => this.loadFeeds());
  },

  hasFeedFilters() {
    return Object.values(this.feedFilters).some((value) => String(value || '').trim() !== '');
  },

  feedFilterSummary() {
    const parts = [];
    if (this.feedFilters.feed_id) parts.push(`Feed: ${this.feedFilters.feed_id}`);
    if (this.feedFilters.keyword) parts.push(`关键词: ${this.feedFilters.keyword}`);
    return parts.join(' / ');
  },

  async clearSubscriptionFilters() {
    this.subFilters = createEmptySubscriptionFilters();
    await this.runPending('subs:refresh', () => this.loadData());
  },

  hasSubscriptionFilters() {
    return Object.values(this.subFilters).some((value) => String(value || '').trim() !== '');
  },

  hasPushHistoryFilters() {
    return Boolean(
      String(this.pushHistoryFilter.keyword || '').trim() || String(this.pushHistoryFilter.status || '').trim()
    );
  },

  pushHistoryFilterSummary() {
    const parts = [];
    if (this.pushHistoryFilter.keyword) parts.push(`关键词: ${this.pushHistoryFilter.keyword}`);
    if (this.pushHistoryFilter.status) parts.push(`状态: ${this.pushHistoryFilter.status}`);
    return parts.join(' / ');
  },

  async clearPushHistoryFilters() {
    this.pushHistoryFilter = createEmptyPushHistoryFilters();
    await this.runPending('push-history:refresh', () => this.loadPushHistory());
  },

  subscriptionFilterSummary() {
    const parts = [];
    if (this.subFilters.user_id) parts.push(`用户: ${this.subFilters.user_id}`);
    if (this.subFilters.feed_id) parts.push(`Feed: ${this.subFilters.feed_id}`);
    if (this.subFilters.sub_id) parts.push(`订阅: ${this.subFilters.sub_id}`);
    if (this.subFilters.keyword) parts.push(`关键词: ${this.subFilters.keyword}`);
    return parts.join(' / ');
  },

  resetSubPage() {
    this.subPagination.page = 1;
  },

  clampSubPage() {
    const totalPages = this.subTotalPages();
    if (this.subPagination.page > totalPages) this.subPagination.page = totalPages;
    if (this.subPagination.page < 1) this.subPagination.page = 1;
  },

  subTotalPages() {
    const pageSize = this.subPagination.pageSize || 20;
    return Math.max(1, Math.ceil(this.filteredSubs.length / pageSize));
  },

  showSubPagination() {
    return this.filteredSubs.length > (this.subPagination.pageSize || 20);
  },

  pagedSubs() {
    this.clampSubPage();
    const pageSize = this.subPagination.pageSize || 20;
    const start = (this.subPagination.page - 1) * pageSize;
    return this.filteredSubs.slice(start, start + pageSize);
  },

  subPrevPage() {
    if (this.subPagination.page > 1) {
      this.subPagination.page -= 1;
      this.selectedIds = [];
    }
  },

  subNextPage() {
    if (this.subPagination.page < this.subTotalPages()) {
      this.subPagination.page += 1;
      this.selectedIds = [];
    }
  },

  toggleEditMode() {
    this.editMode = !this.editMode;
    if (!this.editMode) this.selectedIds = [];
  },

  toggleSelect(id) {
    const index = this.selectedIds.indexOf(id);
    if (index >= 0) {
      this.selectedIds.splice(index, 1);
    } else {
      this.selectedIds.push(id);
    }
  },

  async batchActivate() {
    if (this.selectedIds.length === 0) return;
    const count = this.selectedIds.length;
    await this.runPending('batch:activate', async () => {
      await this.runBatchByUser((ids, userId) => batchActivate(ids, userId));
      this.selectedIds = [];
      this.showToast(`已启用 ${count} 个订阅`);
      await this.loadData();
    }).catch((err) => {
      this.showToast(`批量启用失败: ${err.message}`, 'error');
    });
  },

  async batchDeactivate() {
    if (this.selectedIds.length === 0) return;
    const count = this.selectedIds.length;
    await this.runPending('batch:deactivate', async () => {
      await this.runBatchByUser((ids, userId) => batchDeactivate(ids, userId));
      this.selectedIds = [];
      this.showToast(`已禁用 ${count} 个订阅`);
      await this.loadData();
    }).catch((err) => {
      this.showToast(`批量禁用失败: ${err.message}`, 'error');
    });
  },

  async batchUnsubscribe() {
    if (this.selectedIds.length === 0) return;
    const ok = await this.showConfirm(
      `确定取消 ${this.selectedIds.length} 个订阅？此操作不可恢复。`,
      '批量取消订阅',
      '取消订阅'
    );
    if (!ok) return;
    const count = this.selectedIds.length;
    await this.runPending('batch:unsubscribe', async () => {
      await this.runBatchByUser((ids, userId) => batchUnsubscribe(ids, userId));
      this.selectedIds = [];
      this.showToast(`已取消 ${count} 个订阅`);
      await this.loadData();
    }).catch((err) => {
      this.showToast(`批量取消失败: ${err.message}`, 'error');
    });
  },

  toggleUserEditMode() {
    this.userEditMode = !this.userEditMode;
    if (!this.userEditMode) this.selectedUserIds = [];
  },

  toggleFeedEditMode() {
    this.feedEditMode = !this.feedEditMode;
    if (!this.feedEditMode) this.selectedFeedIds = [];
  },

  togglePushHistoryEditMode() {
    this.pushHistoryEditMode = !this.pushHistoryEditMode;
    if (!this.pushHistoryEditMode) this.selectedPushHistoryIds = [];
  },

  toggleUserSelection(userId) {
    const index = this.selectedUserIds.indexOf(userId);
    if (index >= 0) {
      this.selectedUserIds.splice(index, 1);
    } else {
      this.selectedUserIds.push(userId);
    }
  },

  toggleFeedSelection(feedId) {
    const index = this.selectedFeedIds.indexOf(feedId);
    if (index >= 0) {
      this.selectedFeedIds.splice(index, 1);
    } else {
      this.selectedFeedIds.push(feedId);
    }
  },

  areAllUsersSelected() {
    return this.users.length > 0 && this.selectedUserIds.length === this.users.length;
  },

  areAllFeedsSelected() {
    return this.feeds.length > 0 && this.selectedFeedIds.length === this.feeds.length;
  },

  toggleAllUserSelection() {
    if (this.areAllUsersSelected()) {
      this.selectedUserIds = [];
      return;
    }
    this.selectedUserIds = this.users.map((item) => item.user_id).filter(Boolean);
  },

  toggleAllFeedSelection() {
    if (this.areAllFeedsSelected()) {
      this.selectedFeedIds = [];
      return;
    }
    this.selectedFeedIds = this.feeds.map((item) => Number(item.id || 0)).filter((id) => id > 0);
  },

  async deleteSelectedUsers() {
    if (this.selectedUserIds.length === 0) return;
    const count = this.selectedUserIds.length;
    const ok = await this.showConfirm(
      `确定删除选中的 ${count} 个用户？此操作会同时删除这些用户的所有订阅，不可恢复。`,
      '批量删除用户',
      '删除'
    );
    if (!ok) return;
    await this.runPending('users:delete-batch', async () => {
      const result = await deleteUsers(this.selectedUserIds);
      this.selectedUserIds = [];
      this.showToast(result.message || `已删除 ${count} 个用户`);
      await this.loadUsers();
    }).catch((err) => {
      this.showToast(`批量删除用户失败: ${err.message}`, 'error');
    });
  },

  async refreshSelectedFeeds() {
    if (this.selectedFeedIds.length === 0) return;
    const count = this.selectedFeedIds.length;
    await this.runPending('feeds:refresh-batch', async () => {
      const result = await refreshFeeds(this.selectedFeedIds);
      this.showToast(result.message || `已刷新 ${count} 个 Feed`);
      this.selectedFeedIds = [];
      await this.loadFeeds();
    }).catch((err) => {
      this.showToast(`批量刷新 Feed 失败: ${err.message}`, 'error');
    });
  },

  openDetailPanel(sub) {
    this.panelMode = 'detail';
    this.detailSub = { ...sub };
    this.detailItems = [];
    this.historyDetail = null;
    this.panelVisible = true;
  },

  openEditPanel(sub) {
    this.panelMode = 'edit';
    this.panelExpanded = false;
    this.detailItems = [];
    this.historyDetail = null;
    this.editForm = createEditFormFromSub(sub);
    this.panelVisible = true;
  },

  openPushHistoryDetail(item) {
    this.historyDetail = normalizePushHistoryItem(item);
    this.exportPreview = null;
    this.detailItems = [];
    this.panelMode = 'history-detail';
    this.panelExpanded = true;
    this.panelVisible = true;
  },

  async openExportPreview(name) {
    if (!name) return;
    await this.runPending(`data-management:export-preview:${name}`, async () => {
      const result = await getDataManagementExportContent(name);
      this.exportPreview = {
        name: result.name || name,
        content: String(result.content || ''),
        size: Number(result.size || 0) || 0,
      };
      this.historyDetail = null;
      this.detailItems = [];
      this.panelMode = 'export-preview';
      this.panelExpanded = true;
      this.panelVisible = true;
    }).catch((err) => {
      this.showToast(`预览导出文件失败: ${err.message}`, 'error');
    });
  },

  switchToEdit(sub) {
    this.openEditPanel(sub);
  },

  async loadDetailItems(feedId) {
    if (!feedId) return;
    await this.runPending(`detail:items:${feedId}`, async () => {
      const result = await getFeedItems(feedId, 1, 10);
      this.detailItems = result.items || [];
    }).catch((err) => {
      this.showToast(`加载条目失败: ${err.message}`, 'error');
    });
  },

  async handleRefreshDetail(feedId) {
    if (!feedId) return;
    await this.runPending(`feed:refresh:${feedId}`, async () => {
      await refreshFeed(feedId);
      this.showToast('Feed 刷新完成');
      if (this.activeTab === 'feeds') await this.loadFeeds();
    }).catch((err) => {
      this.showToast(`刷新失败: ${err.message}`, 'error');
    });
  },

  async handleTestDetail(subId) {
    if (!subId) return;
    const targetSession =
      this.panelMode === 'edit'
        ? this.editForm.target_session
        : this.detailSub.target_session;
    const platformName =
      this.panelMode === 'edit'
        ? this.editForm.platform_name
        : this.detailSub.platform_name;
    await this.runPending(`sub:test:${subId}`, async () => {
      const result = await testSubscription(
        subId,
        this.currentSubUserId(),
        targetSession,
        platformName
      );
      this.showToast(result.message || '测试完成');
    }).catch((err) => {
      this.showToast(`测试失败: ${err.message}`, 'error');
    });
  },

  async handleEditSub() {
    await this.runPending(`sub:save:${this.editForm.id}`, async () => {
      const options = {};
      if (this.editForm.title !== undefined) options.title = this.editForm.title;
      if (this.editForm.tags !== undefined) options.tags = this.editForm.tags;
      if (this.editForm.interval !== undefined) options.interval = this.editForm.interval;
      if (this.editForm.target_session !== undefined) {
        options.target_session = this.editForm.target_session;
      }
      if (this.editForm.length_limit !== undefined) {
        options.length_limit = this.editForm.length_limit;
      }
      options.handlers_mode = this.editForm.handlers_mode || 'inherit';
      options.handlers =
        options.handlers_mode === 'override'
          ? buildHandlersFromEditorState(this.editForm)
          : [];
      options.state = this.editForm.state_ ? 1 : 0;
      options.notify = this.editForm.notify;
      options.send_mode = this.editForm.send_mode;
      options.display_author = this.editForm.display_author;
      options.display_via = this.editForm.display_via;
      options.display_title = this.editForm.display_title;
      options.display_entry_tags = this.editForm.display_entry_tags;
      options.style = this.editForm.style;
      options.display_media = this.editForm.display_media;

      await updateSubscription(this.editForm.id, options, this.currentSubUserId());
      this.showToast('订阅已更新');
      this.closePanel();
      await this.loadData();
    }).catch((err) => {
      this.showToast(`更新失败: ${err.message}`, 'error');
    });
  },

  async handleDeleteSub() {
    const id = this.panelMode === 'edit' ? this.editForm.id : this.detailSub.id;
    if (!id) return;
    const ok = await this.showConfirm(
      '确定删除此订阅？此操作不可恢复。',
      '删除订阅',
      '删除'
    );
    if (!ok) return;
    await this.runPending(`sub:delete:${id}`, async () => {
      await unsubscribe(id, this.currentSubUserId());
      this.showToast('订阅已删除');
      this.closePanel();
      await this.loadData();
    }).catch((err) => {
      this.showToast(`删除失败: ${err.message}`, 'error');
    });
  },

  closePanel() {
    this.panelVisible = false;
    this.panelExpanded = false;
    this.panelMode = 'detail';
    this.historyDetail = null;
    this.exportPreview = null;
  },

  showToast(message, type = 'success', duration = 3000) {
    if (toastTimer) clearTimeout(toastTimer);
    this.toast.show = true;
    this.toast.message = message;
    this.toast.type = type;
    toastTimer = setTimeout(() => {
      this.toast.show = false;
    }, duration);
  },

  showConfirm(message, title = '确认', okText = '确定', okClass = 'btn-danger') {
    this.dialog.title = title;
    this.dialog.message = message;
    this.dialog.okText = okText;
    this.dialog.okClass = okClass;
    this.dialog.show = true;
    return new Promise((resolve) => {
      this.dialog.resolve = (result) => {
        this.dialog.show = false;
        resolve(result);
      };
    });
  },

  async handleRouteKbSync() {
    if (this.isRouteKbTaskRunning()) {
      this.showToast('当前已有知识库同步任务在运行，请等待完成后再试', 'error');
      this.startRouteKbPolling();
      return;
    }
    await this.runPending('route-kb:sync', async () => {
      const result = await syncRouteKb();
      this.routeKbTask = result.task || null;
      if (this.routeKbStatus) this.routeKbStatus.task = this.routeKbTask;
      this.syncRouteKbPollingState();
      this.showToast('知识库同步任务已启动');
    }).catch((err) => {
      this.showToast(`启动同步失败: ${err.message}`, 'error');
    });
  },

  async refreshRouteKbTask() {
    await this.runPending('route-kb:task', async () => {
      const result = await getRouteKbTask();
      this.routeKbTask = result.task || null;
      if (this.routeKbStatus) this.routeKbStatus.task = this.routeKbTask;
      this.syncRouteKbPollingState();
    }).catch((err) => {
      this.showToast(`刷新同步任务失败: ${err.message}`, 'error');
    });
  },

  isRouteKbTaskRunning() {
    return Boolean(
      this.routeKbTask && ['queued', 'running'].includes(this.routeKbTask.status)
    );
  },

  startRouteKbPolling() {
    if (routeKbPollTimer) return;
    routeKbPollTimer = setInterval(async () => {
      if (this.activeTab !== 'route-kb') return;
      await this.refreshRouteKbTask();
      if (!this.isRouteKbTaskRunning()) {
        this.stopRouteKbPolling();
        await this.loadRouteKbStatus();
      }
    }, 3000);
  },

  stopRouteKbPolling() {
    if (!routeKbPollTimer) return;
    clearInterval(routeKbPollTimer);
    routeKbPollTimer = null;
  },

  syncRouteKbPollingState() {
    if (this.isRouteKbTaskRunning()) {
      this.startRouteKbPolling();
      return;
    }
    this.stopRouteKbPolling();
  },

  async deletePushHistoryItem(id) {
    const ok = await this.showConfirm('确定删除此记录？', '删除记录', '删除');
    if (!ok) return;
    await this.runPending(`push-history:delete:${id}`, async () => {
      const result = await deletePushHistory(id);
      this.selectedPushHistoryIds = this.selectedPushHistoryIds.filter(
        (selectedId) => selectedId !== id
      );
      this.showToast(result.message || '记录已删除');
      await this.loadPushHistory();
    }).catch((err) => {
      this.showToast(`删除失败: ${err.message}`, 'error');
    });
  },

  togglePushHistorySelect(id) {
    const index = this.selectedPushHistoryIds.indexOf(id);
    if (index >= 0) {
      this.selectedPushHistoryIds.splice(index, 1);
    } else {
      this.selectedPushHistoryIds.push(id);
    }
  },

  isPushHistorySelected(id) {
    return this.selectedPushHistoryIds.includes(id);
  },

  areAllPushHistorySelected() {
    return this.pushHistory.length > 0 && this.selectedPushHistoryIds.length === this.pushHistory.length;
  },

  toggleAllPushHistorySelection() {
    if (this.areAllPushHistorySelected()) {
      this.selectedPushHistoryIds = [];
      return;
    }
    this.selectedPushHistoryIds = this.pushHistory
      .map((item) => Number(item.id || 0))
      .filter((id) => id > 0);
  },

  async deleteSelectedPushHistory() {
    if (this.selectedPushHistoryIds.length === 0) return;
    const count = this.selectedPushHistoryIds.length;
    const ok = await this.showConfirm(
      `确定删除选中的 ${count} 条推送历史？此操作不可恢复。`,
      '批量删除推送历史',
      '删除'
    );
    if (!ok) return;
    await this.runPending('push-history:delete-batch', async () => {
      const result = await deletePushHistoryBatch(this.selectedPushHistoryIds);
      this.selectedPushHistoryIds = [];
      this.showToast(result.message || `已删除 ${count} 条记录`);
      await this.loadPushHistory();
    }).catch((err) => {
      this.showToast(`批量删除失败: ${err.message}`, 'error');
    });
  },

  async cleanupPushHistory() {
    const ok = await this.showConfirm(
      `确定清理 ${this.historyRetentionDays} 天前的推送历史？`,
      '清理历史',
      '清理'
    );
    if (!ok) return;
    await this.runPending('push-history:cleanup', async () => {
      const result = await cleanupPushHistory(this.historyRetentionDays);
      this.showToast(result.message || `已按 ${this.historyRetentionDays} 天范围清理历史记录`);
      await this.loadPushHistory();
    }).catch((err) => {
      this.showToast(`清理失败: ${err.message}`, 'error');
    });
  },

  async clearPushHistory() {
    const ok = await this.showConfirm(
      '确定清空全部推送历史？该操作会删除成功、失败和待重试记录。',
      '清空历史',
      '清空'
    );
    if (!ok) return;
    await this.runPending('push-history:clear', async () => {
      const result = await clearPushHistory();
      this.showToast(result.message || '已清空推送历史');
      this.selectedPushHistoryIds = [];
      await this.loadPushHistory();
      await this.loadStats();
    }).catch((err) => {
      this.showToast(`清空失败: ${err.message}`, 'error');
    });
  },

  async savePushHistorySettings() {
    await this.runPending('push-history:settings-save', async () => {
      const result = await setPluginSettings({
        history_retention_days: this.historyRetentionDays,
      });
      if (result.history_retention_days !== undefined) {
        this.historyRetentionDays = Number(result.history_retention_days) || 30;
      }
      this.showToast('自动清理设置已保存，定时调度将在下次重载后完全按新配置运行');
    }).catch((err) => {
      this.showToast(`保存自动清理设置失败: ${err.message}`, 'error');
    });
  },

  pushHistoryPrevPage() {
    if (this.pushHistoryFilter.page > 1) {
      this.pushHistoryFilter.page -= 1;
      this.loadPushHistory();
    }
  },

  pushHistoryNextPage() {
    const maxPage = this.pushHistoryTotalPages();
    if (this.pushHistoryFilter.page < maxPage) {
      this.pushHistoryFilter.page += 1;
      this.loadPushHistory();
    }
  },

  pushHistoryTotalPages() {
    const pageSize = this.pushHistoryFilter.pageSize || 20;
    return Math.max(1, Math.ceil(this.pushHistoryTotal / pageSize));
  },

  showPushHistoryPagination() {
    return this.pushHistoryTotal > (this.pushHistoryFilter.pageSize || 20);
  },

  async openPushHistorySubscriptions(item) {
    if (this.pushHistoryEditMode) {
      const id = Number(item?.id || 0);
      if (id > 0) this.togglePushHistorySelect(id);
      return;
    }
    const subId = Number(item?.sub_id || 0);
    if (!subId) {
      return;
    }
    await this.selectSubscription(subId);
  },

  openUserEditPanel(user) {
    this.userEditForm = {
      user_id: user.user_id,
      state: normalizeUserState(user.state ?? 1),
      interval: user.interval ?? -100,
      notify: user.notify ?? -100,
      send_mode: user.send_mode ?? -100,
      length_limit: user.length_limit ?? -100,
      display_author: user.display_author ?? -100,
      display_via: user.display_via ?? -100,
      display_title: user.display_title ?? -100,
      display_entry_tags: user.display_entry_tags ?? -100,
      style: user.style ?? -100,
      display_media: user.display_media ?? -100,
      default_target_session: user.default_target_session || '',
      ...handlersToEditorState(user.handlers),
    };
    this.userEditPanelVisible = true;
  },

  closeUserEditPanel() {
    this.userEditPanelVisible = false;
  },

  async handleSaveUserEdit() {
    await this.runPending(`user:save:${this.userEditForm.user_id}`, async () => {
      const settings = {
        state: normalizeUserState(this.userEditForm.state),
        interval: this.userEditForm.interval,
        notify: this.userEditForm.notify,
        send_mode: this.userEditForm.send_mode,
        length_limit: this.userEditForm.length_limit,
        display_author: this.userEditForm.display_author,
        display_via: this.userEditForm.display_via,
        display_title: this.userEditForm.display_title,
        display_entry_tags: this.userEditForm.display_entry_tags,
        style: this.userEditForm.style,
        display_media: this.userEditForm.display_media,
        default_target_session: this.userEditForm.default_target_session.trim(),
        handlers: buildHandlersFromEditorState(this.userEditForm),
      };
      await updateUser(this.userEditForm.user_id, settings);
      this.showToast('用户配置已更新');
      this.closeUserEditPanel();
      await this.loadUsers();
    }).catch((err) => {
      this.showToast(`更新失败: ${err.message}`, 'error');
    });
  },

  async handleDeleteUser(userId) {
    const ok = await this.showConfirm(
      `确定删除用户 ${userId}？此操作将同时删除该用户的所有订阅，不可恢复。`,
      '删除用户',
      '删除'
    );
    if (!ok) return;
    await this.runPending(`user:delete:${userId}`, async () => {
      await deleteUser(userId);
      this.showToast('用户已删除');
      await this.loadUsers();
    }).catch((err) => {
      this.showToast(`删除失败: ${err.message}`, 'error');
    });
  },

  openPushHistorySettingsPanel() {
    this.historyDetail = null;
    this.exportPreview = null;
    this.detailItems = [];
    this.panelMode = 'history-settings';
    this.panelExpanded = true;
    this.panelVisible = true;
  },

  async refreshDataManagement() {
    await this.runPending('data-management:refresh', () => this.loadDataManagement()).catch(
      () => {}
    );
  },

  async refreshHandlers() {
    await this.runPending('handlers:refresh', () => this.loadHandlers()).catch((err) => {
      this.showToast(`刷新处理器失败: ${err.message}`, 'error');
    });
  },

  handlerTypeLabel(type) {
    return String(type || '').trim() === 'builtin' ? '内置' : '扩展';
  },

  handlerStatusLabel(handler) {
    return handler?.default_enabled ? '默认启用' : '默认关闭';
  },

  handlerFieldCountText(handler) {
    const count = Array.isArray(handler?.fields) ? handler.fields.length : 0;
    return count > 0 ? `${count} 个配置项` : '无额外配置';
  },

  isHandlerExpanded(name) {
    return String(this.expandedHandlerName || '') === String(name || '');
  },

  toggleHandlerCard(name) {
    const normalized = String(name || '');
    this.expandedHandlerName = this.isHandlerExpanded(normalized) ? '' : normalized;
  },

  handlerDefaultValueText(value) {
    if (value === undefined) return '-';
    if (value === null) return 'null';
    if (typeof value === 'boolean') return value ? 'true' : 'false';
    if (typeof value === 'string') return value || '""';
    if (typeof value === 'number') return String(value);
    return prettyJson(value);
  },

  async handleClearCache() {
    const ok = await this.showConfirm(
      '确定清理插件缓存目录？这会删除媒体缓存与临时转换产物。',
      '清理缓存',
      '清理'
    );
    if (!ok) return;
    await this.runPending('data-management:cache-clear', async () => {
      const result = await clearDataManagementCache();
      this.showToast(result.message || '缓存已清理');
      await this.loadDataManagement();
    }).catch((err) => {
      this.showToast(`清理缓存失败: ${err.message}`, 'error');
    });
  },

  async handleClearExports() {
    const ok = await this.showConfirm(
      '确定删除全部导出 TOML 文件？此操作不可恢复。',
      '清空导出',
      '清空'
    );
    if (!ok) return;
    await this.runPending('data-management:exports-clear', async () => {
      const result = await clearDataManagementExports();
      this.showToast(result.message || '导出文件已清空');
      await this.loadDataManagement();
    }).catch((err) => {
      this.showToast(`清空导出失败: ${err.message}`, 'error');
    });
  },

  async handleDeleteExportFile(name) {
    const ok = await this.showConfirm(
      `确定删除导出文件 ${name}？`,
      '删除导出文件',
      '删除'
    );
    if (!ok) return;
    await this.runPending(`data-management:export-delete:${name}`, async () => {
      const result = await deleteDataManagementExport(name);
      this.showToast(result.message || '导出文件已删除');
      await this.loadDataManagement();
    }).catch((err) => {
      this.showToast(`删除导出文件失败: ${err.message}`, 'error');
    });
  },

  currentSubUserId() {
    const subUserId =
      this.panelMode === 'edit' ? this.editForm.user_id : this.detailSub.user_id;
    return subUserId || this.subFilters.user_id || undefined;
  },

  selectedSubsByUser() {
    const selected = new Set(this.selectedIds);
    return this.filteredSubs
      .filter((sub) => selected.has(sub.id))
      .reduce((groups, sub) => {
        const userId = sub.user_id || this.subFilters.user_id || undefined;
        const key = userId || '';
        if (!groups[key]) groups[key] = { userId, ids: [] };
        groups[key].ids.push(sub.id);
        return groups;
      }, {});
  },

  async runBatchByUser(action) {
    const groups = Object.values(this.selectedSubsByUser());
    for (const group of groups) {
      await action(group.ids, group.userId);
    }
  },

  applyHandlersJson(form) {
    try {
      const normalized = normalizeHandlers(JSON.parse(form.handlers_json || '[]'));
      form.handlers_json = JSON.stringify(normalized, null, 2);
      this.showToast('处理链 JSON 已应用');
    } catch (err) {
      this.showToast(`处理链 JSON 格式错误: ${err.message}`, 'error');
    }
  },

  panelTitle() {
    if (this.panelMode === 'edit') return '编辑订阅';
    if (this.panelMode === 'history-detail') return '推送历史详情';
    if (this.panelMode === 'history-settings') return '推送历史设置';
    if (this.panelMode === 'export-preview') return '导出文件预览';
    return '订阅详情';
  },

  closePanelDisabled() {
    if (this.panelMode === 'edit') return this.isPending(`sub:save:${this.editForm.id}`);
    if (this.panelMode === 'history-detail') return false;
    return false;
  },

  historyTraceSteps() {
    return Array.isArray(this.historyDetail?.handler_trace)
      ? this.historyDetail.handler_trace
      : [];
  },

  historyTraceStatus(step) {
    return traceStatusText(step);
  },

  historyTraceReason(step) {
    return traceReasonText(step);
  },

  cacheSegments() {
    return pieSegments(this.dataManagementOverview.cache.breakdown);
  },

  exportSegments() {
    return pieSegments(this.dataManagementOverview.exports.breakdown);
  },

  pieSegments(items) {
    return pieSegments(items);
  },

  formatDate,
  formatUserState,
  formatBytes,
  prettyJson,
});

window.store = store;

let pollTimer = null;

initTheme();
ready()
  .then(async () => {
    await store.loadData();
    pollTimer = setInterval(async () => {
      const { changed } = await checkUpdates();
      if (changed) store.loadData(false);
    }, 10000);
    window.addEventListener('beforeunload', () => {
      if (pollTimer) clearInterval(pollTimer);
      if (routeKbPollTimer) clearInterval(routeKbPollTimer);
    });
  })
  .catch((err) => store.showToast(`初始化失败: ${err.message}`, 'error'));

PetiteVue.createApp(store).mount('.container');
