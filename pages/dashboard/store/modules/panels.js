import {
  getFeedItems
} from '../../js/api.js';
import {
  createEditFormFromSub,
  traceStatusText,
  traceReasonText
} from '../helpers.js';

export const panelsModule = {
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

  closePanel() {
    this.panelVisible = false;
    this.panelExpanded = false;
    this.panelMode = 'detail';
    this.historyDetail = null;
    this.exportPreview = null;
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
  }
};
