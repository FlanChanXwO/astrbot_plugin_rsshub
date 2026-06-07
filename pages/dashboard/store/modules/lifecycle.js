

export const lifecycleModule = {
  async openTab(tab) {
    this.syncBatchModesForTab(tab);
    this.activeTab = tab;
    const loaders = {
      subs: () => this.loadData(false),
      overview: () => this.loadOverview(),
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
    if (tab !== 'overview') {
      this.destroyOverviewCharts();
    }
  }
};
