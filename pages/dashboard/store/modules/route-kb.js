import {
  getRouteKbStatus,
  syncRouteKb,
  getRouteKbTask
} from '../../js/api.js';

let routeKbPollTimer = null;

export const routeKbModule = {
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
  }
};
