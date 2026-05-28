// Dashboard store 的纯数据转换与表单工厂，避免页面模块重复维护同一套边界。
export function normalizeUserState(state) {
  return Number(state) < 0 ? -1 : 1;
}

export function formatUserState(state) {
  return normalizeUserState(state) < 0 ? '已封禁' : '用户';
}

export function formatDate(iso) {
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

export function formatBytes(value) {
  const bytes = Number(value) || 0;
  if (bytes <= 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  const exponent = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const size = bytes / 1024 ** exponent;
  return `${size.toFixed(size >= 100 || exponent === 0 ? 0 : size >= 10 ? 1 : 2)} ${units[exponent]}`;
}

export function prettyJson(value) {
  if (value === undefined) return '';
  if (typeof value === 'string') return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value ?? '');
  }
}

export function cloneJsonValue(value) {
  if (value === undefined || value === null) return value;
  if (typeof value !== 'object') return value;
  try {
    return JSON.parse(JSON.stringify(value));
  } catch {
    return Array.isArray(value) ? [...value] : { ...value };
  }
}

export function normalizeHandlers(handlers) {
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

export function handlersToEditorState(handlers) {
  const normalized = normalizeHandlers(handlers);
  return {
    handlers: normalized,
    handlers_advanced: true,
    handlers_json: JSON.stringify(normalized, null, 2),
  };
}

export function buildHandlersFromEditorState(form) {
  return normalizeHandlers(JSON.parse(form.handlers_json || '[]'));
}

export function createTagFilter() {
  return {
    values: [],
    input: '',
  };
}

export function normalizeTagValues(value) {
  if (Array.isArray(value)) {
    return value.map((item) => String(item ?? '').trim()).filter(Boolean);
  }
  const normalized = String(value ?? '').trim();
  return normalized ? [normalized] : [];
}

export function normalizeTextFilterValue(value) {
  if (Array.isArray(value)) {
    return value.map((item) => String(item ?? '').trim()).filter(Boolean).join(' ');
  }
  return String(value ?? '').trim();
}

export function splitTagInputValue(value) {
  return String(value ?? '')
    .split(/[\n\r\t]+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

export function createInheritedNumberValue(value, fallback) {
  const number = Number(value);
  if (number === -100) {
    return { mode: 'inherit', value: fallback };
  }
  return {
    mode: 'custom',
    value: Number.isFinite(number) ? number : fallback,
  };
}

export function inheritedNumberToPayload(field) {
  return field?.mode === 'inherit' ? -100 : Number(field?.value ?? 0);
}

export function createEmptyEditForm() {
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
    interval_control: createInheritedNumberValue(10, 10),
    length_limit_control: createInheritedNumberValue(-100, 0),
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

export function createEditFormFromSub(sub) {
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
    interval_control: createInheritedNumberValue(sub.interval ?? -100, 10),
    length_limit_control: createInheritedNumberValue(sub.length_limit ?? -100, 0),
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

export function createEmptyUserEditForm() {
  return {
    user_id: '',
    state: 1,
    interval: -100,
    notify: -100,
    send_mode: -100,
    length_limit: -100,
    interval_control: createInheritedNumberValue(-100, 10),
    length_limit_control: createInheritedNumberValue(-100, 0),
    display_author: -100,
    display_via: -100,
    display_title: -100,
    display_entry_tags: -100,
    style: -100,
    display_media: -100,
    handlers_json: '[]',
  };
}

export function createEmptyFeedEditForm() {
  return {
    id: 0,
    title: '',
    link: '',
    state: 1,
  };
}

export function createDefaultDataOverview() {
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

export function normalizeBreakdownItems(items) {
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

export function normalizeDataOverview(raw) {
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

export function normalizeExportFile(item) {
  return {
    name: String(item?.name || item?.filename || ''),
    size_bytes: Number(item?.size_bytes ?? item?.size ?? item?.bytes ?? 0) || 0,
    modified_at: item?.modified_at || item?.mtime || null,
    path: item?.path || '',
  };
}

export function normalizePushHistoryItem(item) {
  return {
    ...item,
    media_urls: Array.isArray(item?.media_urls) ? item.media_urls : [],
    handler_trace: Array.isArray(item?.handler_trace) ? item.handler_trace : [],
  };
}

export function createEmptySubscriptionFilters() {
  return {
    user_id: createTagFilter(),
    feed_id: createTagFilter(),
    feed_link: createTagFilter(),
    sub_id: createTagFilter(),
    keyword: '',
  };
}

export function createEmptyUserFilters() {
  return {
    user_id: createTagFilter(),
    keyword: '',
  };
}

export function createEmptyFeedFilters() {
  return {
    feed_id: createTagFilter(),
    keyword: '',
  };
}

export function createEmptyPushHistoryFilters() {
  return {
    status: '',
    feed_link: createTagFilter(),
    keyword: '',
    page: 1,
    pageSize: 20,
  };
}

export function traceStatusText(step) {
  if (step?.allow === false) return '已过滤';
  return String(step?.status || step?.result || 'ok');
}

export function traceReasonText(step) {
  return String(step?.reason || step?.message || step?.error || '').trim();
}

export function pieSegments(items) {
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

export function normalizeHandlerField(field) {
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

export function normalizeHandlerRegistryItem(item) {
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
