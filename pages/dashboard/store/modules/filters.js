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

export const filterModule = {
  filterTags(filter) {
    if (filter && typeof filter === 'object' && Array.isArray(filter.values)) {
      return normalizeTagValues([...filter.values, filter.input]);
    }
    return normalizeTagValues(filter);
  },

  hasFilterTags(filter) {
    return this.filterTags(filter).length > 0;
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
      parts.push(`用户: ${this.filterTags(this.userFilters.user_id).join(' / ')}`);
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
      parts.push(`Feed: ${this.filterTags(this.feedFilters.feed_id).join(' / ')}`);
    }
    if (this.hasTextFilter(this.feedFilters.keyword)) {
      parts.push(`关键词: ${this.textFilterValue(this.feedFilters.keyword)}`);
    }
    return parts.join(' / ');
  },

  async clearSubscriptionFilters() {
    this.subFilters = createEmptySubscriptionFilters();
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
      parts.push(`Feed 链接: ${this.filterTags(this.pushHistoryFilter.feed_link).join(' / ')}`);
    }
    if (this.hasTextFilter(this.pushHistoryFilter.keyword)) {
      parts.push(`关键词: ${this.textFilterValue(this.pushHistoryFilter.keyword)}`);
    }
    if (this.pushHistoryFilter.status) parts.push(`状态: ${this.pushHistoryFilter.status}`);
    return parts.join(' / ');
  },

  async clearPushHistoryFilters() {
    this.pushHistoryFilter = createEmptyPushHistoryFilters();
    this.scheduleFilterRefresh('pushHistoryFilter');
  },

  subscriptionFilterSummary() {
    const parts = [];
    if (this.hasFilterTags(this.subFilters.user_id)) {
      parts.push(`用户: ${this.filterTags(this.subFilters.user_id).join(' / ')}`);
    }
    if (this.hasFilterTags(this.subFilters.feed_id)) {
      parts.push(`Feed: ${this.filterTags(this.subFilters.feed_id).join(' / ')}`);
    }
    if (this.hasFilterTags(this.subFilters.feed_link)) {
      parts.push(`Feed 链接: ${this.filterTags(this.subFilters.feed_link).join(' / ')}`);
    }
    if (this.hasFilterTags(this.subFilters.sub_id)) {
      parts.push(`订阅: ${this.filterTags(this.subFilters.sub_id).join(' / ')}`);
    }
    if (this.hasTextFilter(this.subFilters.keyword)) {
      parts.push(`关键词: ${this.textFilterValue(this.subFilters.keyword)}`);
    }
    return parts.join(' / ');
  }
};
