import {
  normalizeTagValues,
  normalizeTextFilterValue,
  splitTagInputValue,
  createEmptySubscriptionFilters,
  createEmptyUserFilters,
  createEmptyFeedFilters,
  createEmptyPushHistoryFilters
} from '../helpers.js';

let filterDebounceTimer = null;

const COMPACT_FILTER_FIELDS = {
  subFilters: [
    { key: 'user_id', label: '用户 ID', type: 'tag', placeholder: '输入用户 ID' },
    { key: 'feed_id', label: 'Feed ID', type: 'tag', placeholder: '输入 Feed ID' },
    { key: 'feed_link', label: 'Feed URL', type: 'tag', placeholder: '输入 Feed URL' },
    { key: 'sub_id', label: '订阅 ID', type: 'tag', placeholder: '输入订阅 ID' },
  ],
  userFilters: [
    { key: 'user_id', label: '用户 ID', type: 'tag', placeholder: '输入用户 ID' },
  ],
  feedFilters: [
    { key: 'feed_id', label: 'Feed ID', type: 'tag', placeholder: '输入 Feed ID' },
  ],
  pushHistoryFilter: [
    { key: 'feed_link', label: 'Feed URL', type: 'tag', placeholder: '输入 Feed URL' },
    {
      key: 'status',
      label: '状态',
      type: 'select',
      options: [
        { value: 'pending', label: '待推送' },
        { value: 'success', label: '成功' },
        { value: 'failed', label: '失败' },
        { value: 'stopped', label: '已停止' },
      ],
    },
  ],
};

const COMPACT_FILTER_KEYWORD_PLACEHOLDERS = {
  subFilters: '搜索订阅、用户、Feed 或标签',
  userFilters: '搜索用户',
  feedFilters: '搜索 Feed',
  pushHistoryFilter: '搜索历史、条目或 ID',
};

function filterFieldLabel(groupName, fieldName) {
  const field = COMPACT_FILTER_FIELDS[groupName]?.find((item) => item.key === fieldName);
  return field?.label || fieldName;
}

function filterStatusLabel(value) {
  const status = COMPACT_FILTER_FIELDS.pushHistoryFilter
    .find((item) => item.key === 'status')
    ?.options.find((item) => item.value === value);
  return status?.label || value;
}

export const filterModule = {
  filterTags(filter) {
    if (filter && typeof filter === 'object' && Array.isArray(filter.values)) {
      return normalizeTagValues([...filter.values, filter.input]);
    }
    return normalizeTagValues(filter);
  },

  committedFilterTags(filter) {
    if (filter && typeof filter === 'object' && Array.isArray(filter.values)) {
      return normalizeTagValues(filter.values);
    }
    return normalizeTagValues(filter);
  },

  hasFilterTags(filter) {
    return this.committedFilterTags(filter).length > 0;
  },

  textFilterValue(value) {
    return normalizeTextFilterValue(value);
  },

  hasTextFilter(value) {
    return this.textFilterValue(value).length > 0;
  },

  addFilterTag(groupName, fieldName) {
    const filter = this[groupName]?.[fieldName];
    if (!filter) return;
    const values = splitTagInputValue(filter.input);
    if (values.length === 0) return;
    let changed = false;
    for (const value of values) {
      if (!filter.values.includes(value)) {
        filter.values.push(value);
        changed = true;
      }
    }
    filter.input = '';
    if (changed) {
      this.scheduleFilterRefresh(groupName);
    }
  },

  compactFilterFields(groupName) {
    return COMPACT_FILTER_FIELDS[groupName] || [];
  },

  compactFilterKeywordPlaceholder(groupName) {
    return COMPACT_FILTER_KEYWORD_PLACEHOLDERS[groupName] || '搜索';
  },

  compactFilterActiveField(groupName) {
    const fields = this.compactFilterFields(groupName);
    const selectedField = this.compactFilterUi?.[groupName]?.field;
    return fields.find((field) => field.key === selectedField) || fields[0] || {};
  },

  ensureCompactFilterField(groupName) {
    if (!this.compactFilterUi[groupName]) {
      this.compactFilterUi[groupName] = {
        field: this.compactFilterFields(groupName)[0]?.key || '',
        value: '',
      };
    }
    const active = this.compactFilterActiveField(groupName);
    if (!active.key) return '';
    this.compactFilterUi[groupName].field = active.key;
    return active.key;
  },

  addCompactFilterCondition(groupName) {
    const fieldName = this.ensureCompactFilterField(groupName);
    const field = this.compactFilterActiveField(groupName);
    if (!fieldName || field.type === 'select') {
      if (fieldName && field.type === 'select') {
        this[groupName][fieldName] = String(this.compactFilterUi[groupName]?.value || '').trim();
        if (groupName === 'pushHistoryFilter') this.pushHistoryFilter.page = 1;
      }
      this.scheduleFilterRefresh(groupName);
      return;
    }
    this.addFilterTag(groupName, fieldName);
  },

  handleCompactFilterInput(groupName) {
    const fieldName = this.ensureCompactFilterField(groupName);
    if (!fieldName) return;
    this.scheduleAutocomplete(groupName, fieldName);
  },

  handleCompactFilterKeydown(event, groupName) {
    const fieldName = this.ensureCompactFilterField(groupName);
    if (!fieldName) return;
    this.handleFilterKeydown(event, groupName, fieldName);
  },

  handleCompactKeywordKeydown(event, groupName, pendingKey, loadAction) {
    if (event.isComposing) return;
    if (this.handleAutocompleteKeydown(event, groupName, 'keyword')) return;
    if (event.key === 'Enter') {
      event.preventDefault();
      this.runPending(pendingKey, loadAction);
    }
  },

  compactFilterChips(groupName) {
    const filters = this[groupName] || {};
    const chips = [];
    for (const field of this.compactFilterFields(groupName)) {
      if (field.type === 'select') {
        const value = String(filters[field.key] || '').trim();
        if (value) {
          chips.push({
            key: `${field.key}:${value}`,
            field: field.key,
            label: field.label,
            type: field.type,
            value: filterStatusLabel(value),
            rawValue: value,
          });
        }
        continue;
      }
      for (const value of this.committedFilterTags(filters[field.key])) {
        chips.push({
          key: `${field.key}:${value}`,
          field: field.key,
          label: field.label,
          type: field.type,
          value,
          rawValue: value,
        });
      }
    }
    if (this.hasTextFilter(filters.keyword)) {
      chips.unshift({
        key: 'keyword',
        field: 'keyword',
        label: '关键词',
        type: 'text',
        value: this.textFilterValue(filters.keyword),
        rawValue: this.textFilterValue(filters.keyword),
      });
    }
    return chips;
  },

  removeCompactFilterChip(groupName, chip) {
    if (!chip?.field) return;
    if (chip.type === 'text') {
      this[groupName][chip.field] = '';
      this.scheduleFilterRefresh(groupName);
      return;
    }
    if (chip.type === 'select') {
      this[groupName][chip.field] = '';
      if (this.compactFilterUi[groupName]) this.compactFilterUi[groupName].value = '';
      if (groupName === 'pushHistoryFilter') this.pushHistoryFilter.page = 1;
      this.scheduleFilterRefresh(groupName);
      return;
    }
    this.removeFilterTag(groupName, chip.field, chip.rawValue);
  },

  handleFilterKeydown(event, groupName, fieldName) {
    if (event.isComposing) return;
    if (this.handleAutocompleteKeydown(event, groupName, fieldName)) return;
    if (event.key === 'Escape' && this.isTagFilterPanelOpen(groupName, fieldName)) {
      event.preventDefault();
      this.closeAutocomplete();
      return;
    }
    if (event.key === 'Enter') {
      event.preventDefault();
      this.addFilterTag(groupName, fieldName);
      return;
    }
    if (event.key === 'Tab') {
      const filter = this[groupName]?.[fieldName];
      if (filter && String(filter.input || '').trim()) {
        event.preventDefault();
        this.addFilterTag(groupName, fieldName);
      }
      return;
    }
  },

  handleFilterBlur(groupName, fieldName) {
    this.addFilterTag(groupName, fieldName);
    this.closeAutocomplete();
  },

  handleAutocompleteBlur(groupName, fieldName) {
    this.closeAutocomplete();
  },

  handleFilterPaste(event, groupName, fieldName) {
    const text = event.clipboardData?.getData('text') || '';
    if (!/[\n\r\t]/.test(text)) return;
    event.preventDefault();
    const filter = this[groupName]?.[fieldName];
    if (!filter) return;
    filter.input = [filter.input, text].filter(Boolean).join('\n');
    this.addFilterTag(groupName, fieldName);
  },

  handleTagFilterInput(groupName, fieldName) {
    this.scheduleAutocomplete(groupName, fieldName);
    this.scheduleFilterRefresh(groupName);
  },

  handleTextFilterInput(groupName, fieldName) {
    this.scheduleAutocomplete(groupName, fieldName);
    this.scheduleFilterRefresh(groupName);
  },

  removeFilterTag(groupName, fieldName, value) {
    const filter = this[groupName]?.[fieldName];
    if (!filter) return;
    const nextValues = filter.values.filter((item) => item !== value);
    if (nextValues.length === filter.values.length) return;
    filter.values = nextValues;
    this.scheduleFilterRefresh(groupName);
  },

  scheduleFilterRefresh(groupName) {
    if (filterDebounceTimer) clearTimeout(filterDebounceTimer);
    filterDebounceTimer = setTimeout(async () => {
      if (groupName === 'subFilters') {
        await this.runPending('subs:refresh', () => this.loadData());
      } else if (groupName === 'userFilters') {
        await this.runPending('users:refresh', () => this.loadUsers());
      } else if (groupName === 'feedFilters') {
        await this.runPending('feeds:refresh', () => this.loadFeeds());
      } else if (groupName === 'pushHistoryFilter') {
        this.pushHistoryFilter.page = 1;
        await this.runPending('push-history:refresh', () => this.loadPushHistory());
      }
    }, 220);
  },

  onPushHistoryStatusChanged() {
    this.pushHistoryFilter.page = 1;
    this.scheduleFilterRefresh('pushHistoryFilter');
  },

  async applySubscriptionFilters() {
    await this.runPending('subs:refresh', () => this.loadData());
  },

  async applyUserFilters() {
    await this.runPending('users:refresh', () => this.loadUsers());
  },

  async clearUserFilters() {
    this.userFilters = createEmptyUserFilters();
    if (this.compactFilterUi.userFilters) this.compactFilterUi.userFilters.value = '';
    this.scheduleFilterRefresh('userFilters');
  },

  hasUserFilters() {
    return (
      this.hasFilterTags(this.userFilters.user_id) ||
      this.hasTextFilter(this.userFilters.keyword)
    );
  },

  userFilterSummary() {
    const parts = [];
    if (this.hasFilterTags(this.userFilters.user_id)) {
      parts.push(`${filterFieldLabel('userFilters', 'user_id')}: ${this.committedFilterTags(this.userFilters.user_id).join(' / ')}`);
    }
    if (this.hasTextFilter(this.userFilters.keyword)) {
      parts.push(`关键词: ${this.textFilterValue(this.userFilters.keyword)}`);
    }
    return parts.join(' / ');
  },

  async applyFeedFilters() {
    await this.runPending('feeds:refresh', () => this.loadFeeds());
  },

  async clearFeedFilters() {
    this.feedFilters = createEmptyFeedFilters();
    if (this.compactFilterUi.feedFilters) this.compactFilterUi.feedFilters.value = '';
    this.scheduleFilterRefresh('feedFilters');
  },

  hasFeedFilters() {
    return (
      this.hasFilterTags(this.feedFilters.feed_id) ||
      this.hasTextFilter(this.feedFilters.keyword)
    );
  },

  feedFilterSummary() {
    const parts = [];
    if (this.hasFilterTags(this.feedFilters.feed_id)) {
      parts.push(`${filterFieldLabel('feedFilters', 'feed_id')}: ${this.committedFilterTags(this.feedFilters.feed_id).join(' / ')}`);
    }
    if (this.hasTextFilter(this.feedFilters.keyword)) {
      parts.push(`关键词: ${this.textFilterValue(this.feedFilters.keyword)}`);
    }
    return parts.join(' / ');
  },

  async clearSubscriptionFilters() {
    this.subFilters = createEmptySubscriptionFilters();
    if (this.compactFilterUi.subFilters) this.compactFilterUi.subFilters.value = '';
    this.scheduleFilterRefresh('subFilters');
  },

  hasSubscriptionFilters() {
    return (
      this.hasFilterTags(this.subFilters.user_id) ||
      this.hasFilterTags(this.subFilters.feed_id) ||
      this.hasFilterTags(this.subFilters.feed_link) ||
      this.hasFilterTags(this.subFilters.sub_id) ||
      this.hasTextFilter(this.subFilters.keyword)
    );
  },

  hasPushHistoryFilters() {
    return Boolean(
      this.hasTextFilter(this.pushHistoryFilter.keyword) ||
        this.hasFilterTags(this.pushHistoryFilter.feed_link) ||
        String(this.pushHistoryFilter.status || '').trim()
    );
  },

  pushHistoryFilterSummary() {
    const parts = [];
    if (this.hasFilterTags(this.pushHistoryFilter.feed_link)) {
      parts.push(`${filterFieldLabel('pushHistoryFilter', 'feed_link')}: ${this.committedFilterTags(this.pushHistoryFilter.feed_link).join(' / ')}`);
    }
    if (this.hasTextFilter(this.pushHistoryFilter.keyword)) {
      parts.push(`关键词: ${this.textFilterValue(this.pushHistoryFilter.keyword)}`);
    }
    if (this.pushHistoryFilter.status) parts.push(`状态: ${filterStatusLabel(this.pushHistoryFilter.status)}`);
    return parts.join(' / ');
  },

  async clearPushHistoryFilters() {
    this.pushHistoryFilter = createEmptyPushHistoryFilters();
    if (this.compactFilterUi.pushHistoryFilter) this.compactFilterUi.pushHistoryFilter.value = '';
    this.scheduleFilterRefresh('pushHistoryFilter');
  },

  subscriptionFilterSummary() {
    const parts = [];
    if (this.hasFilterTags(this.subFilters.user_id)) {
      parts.push(`${filterFieldLabel('subFilters', 'user_id')}: ${this.committedFilterTags(this.subFilters.user_id).join(' / ')}`);
    }
    if (this.hasFilterTags(this.subFilters.feed_id)) {
      parts.push(`${filterFieldLabel('subFilters', 'feed_id')}: ${this.committedFilterTags(this.subFilters.feed_id).join(' / ')}`);
    }
    if (this.hasFilterTags(this.subFilters.feed_link)) {
      parts.push(`${filterFieldLabel('subFilters', 'feed_link')}: ${this.committedFilterTags(this.subFilters.feed_link).join(' / ')}`);
    }
    if (this.hasFilterTags(this.subFilters.sub_id)) {
      parts.push(`${filterFieldLabel('subFilters', 'sub_id')}: ${this.committedFilterTags(this.subFilters.sub_id).join(' / ')}`);
    }
    if (this.hasTextFilter(this.subFilters.keyword)) {
      parts.push(`关键词: ${this.textFilterValue(this.subFilters.keyword)}`);
    }
    return parts.join(' / ');
  }
};
