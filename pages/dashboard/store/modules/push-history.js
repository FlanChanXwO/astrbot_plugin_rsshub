import {
  getPluginSettings,
  setPluginSettings,
  getPushHistory,
  deletePushHistory,
  deletePushHistoryBatch,
  retryPushHistory,
  cleanupPushHistory,
  clearPushHistory
} from '../../js/api.js';
import {
  normalizePushHistoryItem
} from '../helpers.js';

export const pushHistoryModule = {
  async loadPushHistory() {
    this.pushHistoryLoading = true;
    try {
      const pluginResult = await getPluginSettings();
      if (pluginResult.history_retention_days !== undefined) {
        this.historyRetentionDays = Number(pluginResult.history_retention_days) || 30;
      }
      const result = await getPushHistory({
        status: this.pushHistoryFilter.status,
        feedLink: this.committedFilterTags(this.pushHistoryFilter.feed_link),
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

  togglePushHistoryEditMode() {
    this.pushHistoryEditMode = !this.pushHistoryEditMode;
    if (!this.pushHistoryEditMode) this.selectedPushHistoryIds = [];
  },

  openPushHistoryDetail(item) {
    this.historyDetail = normalizePushHistoryItem(item);
    this.exportPreview = null;
    this.detailItems = [];
    this.panelMode = 'history-detail';
    this.panelExpanded = true;
    this.panelVisible = true;
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

  async retryPushHistoryItem(id) {
    await this.runPending(`push-history:retry:${id}`, async () => {
      const result = await retryPushHistory(id);
      const retryError = result.error || result.message || '发送失败';
      this.showToast(
        result.ok
          ? result.message || '重试完成'
          : `重试失败: ${retryError}`,
        result.ok ? 'success' : 'error'
      );
      this.pushHistoryFilter.page = 1;
      await this.loadPushHistory();
    }).catch((err) => {
      this.showToast(`重试失败: ${err.message}`, 'error');
      this.pushHistoryFilter.page = 1;
      return this.loadPushHistory();
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
      await this.loadData(false);
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
    const feedLink = String(item?.feed_link || '').trim();
    if (!feedLink) {
      this.showToast('这条历史记录没有 Feed 链接，无法安全定位相关订阅', 'error');
      return;
    }
    const filters = { feed_link: feedLink };
    const userId = String(item?.user_id || '').trim();
    if (userId) filters.user_id = userId;
    await this.openSubscriptionsWithFilter(filters);
  },

  openPushHistorySettingsPanel() {
    this.historyDetail = null;
    this.exportPreview = null;
    this.detailItems = [];
    this.panelMode = 'history-settings';
    this.panelExpanded = true;
    this.panelVisible = true;
  }
};
