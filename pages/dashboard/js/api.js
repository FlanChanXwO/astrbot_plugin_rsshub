function getBridge() {
  return typeof window !== 'undefined' ? window.AstrBotPluginPage || null : null;
}

function requireBridge() {
  const bridge = getBridge();
  if (!bridge) {
    throw new Error('AstrBotPluginPage bridge not available');
  }
  return bridge;
}

function buildDirectApiUrl(path, params = {}) {
  const normalizedPath = String(path || '').replace(/^\/+/, '');
  const url = new URL(`/astrbot_plugin_rsshub/${normalizedPath}`, window.location.origin);
  for (const [key, value] of Object.entries(params || {})) {
    if (value === undefined || value === null || value === '') continue;
    if (Array.isArray(value)) {
      for (const item of value) {
        if (item !== undefined && item !== null && item !== '') {
          url.searchParams.append(key, String(item));
        }
      }
      continue;
    }
    url.searchParams.set(key, String(value));
  }
  return url;
}

function toBridgePayload(value) {
  if (value === undefined || value === null) {
    return value;
  }
  if (typeof structuredClone === 'function') {
    try {
      return structuredClone(value);
    } catch (_error) {
      // Fall back to plain objects for reactive or otherwise non-cloneable values.
    }
  }
  return cloneBridgeValue(value, new WeakSet());
}

function cloneBridgeValue(value, seen) {
  if (value === undefined || value === null || typeof value !== 'object') {
    return value;
  }
  if (seen.has(value)) {
    throw new Error('Bridge payload contains circular references');
  }
  seen.add(value);
  if (Array.isArray(value)) {
    const cloned = value.map((item) => cloneBridgeValue(item, seen));
    seen.delete(value);
    return cloned;
  }
  const cloned = {};
  for (const [key, item] of Object.entries(value)) {
    cloned[key] = cloneBridgeValue(item, seen);
  }
  seen.delete(value);
  return cloned;
}

function normalizeFilterValue(value) {
  if (value && typeof value === 'object' && Array.isArray(value.values)) {
    return normalizeFilterValue([...value.values, value.input]);
  }
  if (Array.isArray(value)) {
    return value
      .map((item) => String(item ?? '').trim())
      .filter(Boolean);
  }
  const normalized = String(value ?? '').trim();
  return normalized ? [normalized] : [];
}

function setArrayParam(params, key, value) {
  const normalized = normalizeFilterValue(value);
  if (normalized.length > 0) {
    params[key] = normalized;
  }
}

function setTextParam(params, key, value) {
  const normalized = String(value ?? '').trim();
  if (normalized) {
    params[key] = normalized;
  }
}

export async function ready() {
  for (let attempt = 0; attempt < 50; attempt += 1) {
    const bridge = getBridge();
    if (bridge) {
      return await bridge.ready();
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error('AstrBotPluginPage bridge not available');
}

async function handleResponse(result) {
  if (result && result.ok !== undefined) {
    if (!result.ok) throw new Error(result.error || result.message || '操作失败');
    return result;
  }
  return result;
}

async function apiGet(path, params = {}) {
  const bridge = requireBridge();
  const result = await bridge.apiGet(path, toBridgePayload(params));
  return await handleResponse(result);
}

async function apiPost(path, payload = {}) {
  const bridge = requireBridge();
  const result = await bridge.apiPost(path, toBridgePayload(payload));
  return await handleResponse(result);
}

async function apiPostRaw(path, payload = {}) {
  const bridge = requireBridge();
  return await bridge.apiPost(path, toBridgePayload(payload));
}

export async function getSubscriptions(filters = {}) {
  const params = {};
  setArrayParam(params, 'user_id', filters.user_id);
  if (filters.feed_id !== undefined && filters.feed_id !== null && filters.feed_id !== '') {
    setArrayParam(params, 'feed_id', filters.feed_id);
  }
  setArrayParam(params, 'feed_link', filters.feed_link);
  if (filters.sub_id !== undefined && filters.sub_id !== null && filters.sub_id !== '') {
    setArrayParam(params, 'sub_id', filters.sub_id);
  }
  setTextParam(params, 'keyword', filters.keyword);
  const r = await apiGet('subscriptions', params);
  return { items: r.items || [], total: r.total || 0 };
}

export async function getFeeds(filters = {}) {
  const params = {};
  setArrayParam(params, 'feed_id', filters.feed_id);
  setTextParam(params, 'keyword', filters.keyword);
  const r = await apiGet('feeds', params);
  return { items: r.items || [], total: r.total || 0 };
}

export async function getSuggestions(scope, field, q = '', limit = 10) {
  const params = { scope, field, limit };
  setTextParam(params, 'q', q);
  const r = await apiGet('suggestions', params);
  return { items: r.items || [] };
}

export async function unsubscribe(subId, userId, deletePushHistory = false) {
  const payload = { sub_id: subId };
  if (userId) payload.user_id = userId;
  if (deletePushHistory) payload.delete_push_history = true;
  return await apiPost('unsubscribe', payload);
}

export async function updateSubscription(subId, options, userId) {
  const payload = { sub_id: subId, options };
  if (userId) payload.user_id = userId;
  return await apiPost('subscriptions/update', payload);
}

export async function getFeedItems(feedId, page = 1, pageSize = 20) {
  return await apiGet('feeds/items', { feed_id: feedId, page, page_size: pageSize });
}

export async function refreshFeed(feedId) {
  return await apiPost('feeds/refresh', { feed_id: feedId });
}

export async function refreshFeeds(feedIds) {
  return await apiPost('feeds/refresh', { feed_ids: feedIds });
}

export async function updateFeed(feedId, options) {
  return await apiPost('feeds/update', { feed_id: feedId, options });
}

export async function deleteFeed(feedId, deletePushHistory = false) {
  return await apiPost('feeds/delete', {
    feed_id: feedId,
    delete_push_history: Boolean(deletePushHistory),
  });
}

export async function deleteFeeds(feedIds, deletePushHistory = false) {
  return await apiPost('feeds/delete', {
    feed_ids: feedIds,
    delete_push_history: Boolean(deletePushHistory),
  });
}

export async function getPluginSettings() {
  return await apiGet('plugin-settings');
}

export async function getHandlers() {
  const r = await apiGet('handlers');
  return { items: r.items || [] };
}

export async function setPluginSettings({
  subscription_defaults = {},
  history_retention_days,
} = {}) {
  const payload = { subscription_defaults };
  if (history_retention_days !== undefined) {
    payload.history_retention_days = history_retention_days;
  }
  return await apiPost('plugin-settings', payload);
}

export async function testSubscription(subId, userId, targetSession, platformName) {
  const payload = { sub_id: subId };
  if (userId) payload.user_id = userId;
  if (targetSession) payload.target_session = targetSession;
  if (platformName) payload.platform_name = platformName;
  return await apiPost('test-subscription', payload);
}

export async function batchActivate(subIds, userId) {
  const payload = { sub_ids: subIds };
  if (userId) payload.user_id = userId;
  return await apiPost('batch/activate', payload);
}

export async function batchDeactivate(subIds, userId) {
  const payload = { sub_ids: subIds };
  if (userId) payload.user_id = userId;
  return await apiPost('batch/deactivate', payload);
}

export async function batchUnsubscribe(subIds, userId, deletePushHistory = false) {
  const payload = { sub_ids: subIds };
  if (userId) payload.user_id = userId;
  if (deletePushHistory) payload.delete_push_history = true;
  return await apiPost('batch/unsubscribe', payload);
}

export async function getStats() {
  return await apiGet('stats');
}

let previousCounter = 0;

export async function getPushHistory({
  status = '',
  feedLink = '',
  keyword = '',
  page = 1,
  pageSize = 20,
} = {}) {
  const params = { page, page_size: pageSize };
  if (status) params.status = status;
  setArrayParam(params, 'feed_link', feedLink);
  setTextParam(params, 'keyword', keyword);
  const r = await apiGet('push-history', params);
  return {
    items: r.items || [],
    total: r.total || 0,
    page: r.page || 1,
    page_size: r.page_size || pageSize,
  };
}

export async function getRouteKbStatus() {
  return await apiGet('route-kb/status');
}

export async function syncRouteKb() {
  return await apiPost('route-kb/sync', {});
}

export async function getRouteKbTask() {
  return await apiGet('route-kb/task');
}

export async function deletePushHistory(historyId) {
  return await apiPost('push-history/delete', { history_id: historyId });
}

export async function deletePushHistoryBatch(historyIds) {
  return await apiPost('push-history/delete', { history_ids: historyIds });
}

export async function retryPushHistory(historyId) {
  return await apiPostRaw('push-history/retry', { history_id: historyId });
}

export async function cleanupPushHistory(days = 30) {
  return await apiPost('push-history/cleanup', { days });
}

export async function clearPushHistory() {
  return await apiPost('push-history/clear', {});
}

export async function getUserDetails(filters = {}) {
  const params = {};
  setArrayParam(params, 'user_id', filters.user_id);
  setTextParam(params, 'keyword', filters.keyword);
  const r = await apiGet('users/detail', params);
  return { items: r.items || [], total: r.total || 0 };
}

export async function updateUser(userId, settings) {
  return await apiPost('users/update', { user_id: userId, settings });
}

export async function deleteUser(userId, deletePushHistory = false) {
  return await apiPost('users/delete', {
    user_id: userId,
    delete_push_history: Boolean(deletePushHistory),
  });
}

export async function deleteUsers(userIds, deletePushHistory = false) {
  return await apiPost('users/delete', {
    user_ids: userIds,
    delete_push_history: Boolean(deletePushHistory),
  });
}

export async function getDataManagementOverview() {
  return await apiGet('data-management/overview');
}

export async function getDataManagementExports() {
  const r = await apiGet('data-management/exports');
  return { items: r.items || [] };
}

export async function clearDataManagementCache() {
  return await apiPost('data-management/cache/clear', {});
}

export async function clearDataManagementExports() {
  return await apiPost('data-management/exports/clear', {});
}

export async function deleteDataManagementExport(name) {
  return await apiPost('data-management/exports/delete', { name });
}

export async function getDataManagementExportContent(name) {
  return await apiGet('data-management/exports/content', { name });
}

export async function checkUpdates() {
  try {
    const r = await apiGet('updates');
    const counter = r?.counter ?? 0;
    const changed = counter !== previousCounter;
    previousCounter = counter;
    return { changed };
  } catch {
    return { changed: false };
  }
}
