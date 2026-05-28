import {
  refreshFeed,
  refreshFeeds,
  updateFeed,
  deleteFeed,
  deleteFeeds,
  getFeeds
} from '../../js/api.js';

export const feedsModule = {
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

  toggleFeedEditMode() {
    this.feedEditMode = !this.feedEditMode;
    if (!this.feedEditMode) this.selectedFeedIds = [];
  },

  toggleFeedSelection(feedId) {
    const index = this.selectedFeedIds.indexOf(feedId);
    if (index >= 0) {
      this.selectedFeedIds.splice(index, 1);
    } else {
      this.selectedFeedIds.push(feedId);
    }
  },

  areAllFeedsSelected() {
    return this.feeds.length > 0 && this.selectedFeedIds.length === this.feeds.length;
  },

  toggleAllFeedSelection() {
    if (this.areAllFeedsSelected()) {
      this.selectedFeedIds = [];
      return;
    }
    this.selectedFeedIds = this.feeds.map((item) => Number(item.id || 0)).filter((id) => id > 0);
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

  async deleteSelectedFeeds() {
    if (this.selectedFeedIds.length === 0) return;
    const count = this.selectedFeedIds.length;
    const confirm = await this.showConfirm(
      `确定删除选中的 ${count} 个 Feed？此操作将同时删除对应订阅，不可恢复。推送历史默认保留。`,
      '批量删除 Feed',
      '删除',
      'btn-danger',
      { optionLabel: '同时清理对应推送历史' }
    );
    if (!confirm.ok) return;
    await this.runPending('feeds:delete-batch', async () => {
      const result = await deleteFeeds(this.selectedFeedIds, confirm.optionChecked);
      this.selectedFeedIds = [];
      this.showToast(result.message || `已删除 ${count} 个 Feed`);
      await this.loadFeeds();
      await this.loadData();
      if (confirm.optionChecked) await this.loadPushHistory();
    }).catch((err) => {
      this.showToast(`批量删除 Feed 失败: ${err.message}`, 'error');
    });
  },

  openFeedEditPanel(feed) {
    this.feedEditForm = {
      id: Number(feed?.id || 0),
      title: String(feed?.title || ''),
      link: String(feed?.link || ''),
      state: Number(feed?.state ?? 1),
    };
    this.feedEditPanelVisible = true;
  },

  closeFeedEditPanel() {
    this.feedEditPanelVisible = false;
  },

  async handleSaveFeedEdit() {
    const feedId = Number(this.feedEditForm.id || 0);
    if (!feedId) return;
    await this.runPending(`feed:save:${feedId}`, async () => {
      const options = {
        title: String(this.feedEditForm.title || '').trim(),
        link: String(this.feedEditForm.link || '').trim(),
        state: Number(this.feedEditForm.state || 0),
      };
      const result = await updateFeed(feedId, options);
      this.showToast(result.message || 'Feed 已更新');
      this.closeFeedEditPanel();
      await this.loadFeeds();
      await this.loadData(false);
    }).catch((err) => {
      this.showToast(`更新 Feed 失败: ${err.message}`, 'error');
    });
  },

  async handleDeleteFeed(feedId) {
    const id = Number(feedId || 0);
    if (!id) return;
    const confirm = await this.showConfirm(
      `确定删除 Feed ${id}？此操作将同时删除对应订阅，不可恢复。推送历史默认保留。`,
      '删除 Feed',
      '删除',
      'btn-danger',
      { optionLabel: '同时清理对应推送历史' }
    );
    if (!confirm.ok) return;
    await this.runPending(`feed:delete:${id}`, async () => {
      const result = await deleteFeed(id, confirm.optionChecked);
      this.showToast(result.message || 'Feed 已删除');
      this.closeFeedEditPanel();
      await this.loadFeeds();
      await this.loadData();
      if (confirm.optionChecked) await this.loadPushHistory();
    }).catch((err) => {
      this.showToast(`删除 Feed 失败: ${err.message}`, 'error');
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
  }
};
