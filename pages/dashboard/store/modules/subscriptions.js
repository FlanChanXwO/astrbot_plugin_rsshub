import {
  getSubscriptions,
  unsubscribe,
  updateSubscription,
  testSubscription,
  batchActivate,
  batchDeactivate,
  batchUnsubscribe,
  getStats
} from '../../js/api.js';
import {
  buildHandlersFromEditorState,
  normalizeTagValues,
  normalizeTextFilterValue,
  inheritedNumberToPayload,
  createEmptySubscriptionFilters
} from '../helpers.js';

export const subscriptionsModule = {
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

  async openSubscriptionsWithFilter(filters = {}) {
    const nextFilters = createEmptySubscriptionFilters();
    for (const [key, value] of Object.entries(filters)) {
      if (!nextFilters[key]) continue;
      if (nextFilters[key] && typeof nextFilters[key] === 'object' && Array.isArray(nextFilters[key].values)) {
        nextFilters[key].values = normalizeTagValues(value);
        nextFilters[key].input = '';
      } else {
        nextFilters[key] = normalizeTextFilterValue(value);
      }
    }
    this.subFilters = nextFilters;
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
    const confirm = await this.showConfirm(
      `确定取消 ${this.selectedIds.length} 个订阅？此操作不可恢复。`,
      '批量取消订阅',
      '取消订阅',
      'btn-danger',
      { optionLabel: '同时清理对应推送历史' }
    );
    if (!confirm.ok) return;
    const count = this.selectedIds.length;
    await this.runPending('batch:unsubscribe', async () => {
      await this.runBatchByUser((ids, userId) =>
        batchUnsubscribe(ids, userId, confirm.optionChecked)
      );
      this.selectedIds = [];
      this.showToast(`已取消 ${count} 个订阅`);
      await this.loadData();
      if (confirm.optionChecked) await this.loadPushHistory();
    }).catch((err) => {
      this.showToast(`批量取消失败: ${err.message}`, 'error');
    });
  },

  currentSubUserId() {
    const subUserId =
      this.panelMode === 'edit' ? this.editForm.user_id : this.detailSub.user_id;
    const filterUserIds = this.committedFilterTags(this.subFilters.user_id);
    return subUserId || filterUserIds[0] || undefined;
  },

  selectedSubsByUser() {
    const selected = new Set(this.selectedIds);
    return this.filteredSubs
      .filter((sub) => selected.has(sub.id))
      .reduce((groups, sub) => {
        const filterUserIds = this.committedFilterTags(this.subFilters.user_id);
        const userId = sub.user_id || filterUserIds[0] || undefined;
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
      options.interval = inheritedNumberToPayload(this.editForm.interval_control);
      if (this.editForm.target_session !== undefined) {
        options.target_session = this.editForm.target_session;
      }
      options.length_limit = inheritedNumberToPayload(this.editForm.length_limit_control);
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
    const confirm = await this.showConfirm(
      '确定删除此订阅？此操作不可恢复。',
      '删除订阅',
      '删除',
      'btn-danger',
      { optionLabel: '同时清理对应推送历史' }
    );
    if (!confirm.ok) return;
    await this.runPending(`sub:delete:${id}`, async () => {
      await unsubscribe(id, this.currentSubUserId(), confirm.optionChecked);
      this.showToast('订阅已删除');
      this.closePanel();
      await this.loadData();
      if (confirm.optionChecked) await this.loadPushHistory();
    }).catch((err) => {
      this.showToast(`删除失败: ${err.message}`, 'error');
    });
  }
};
