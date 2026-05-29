import {
  getDataManagementOverview,
  getDataManagementExports,
  clearDataManagementCache,
  clearDataManagementExports,
  deleteDataManagementExport,
  getDataManagementExportContent
} from '../../js/api.js';
import {
  normalizeDataOverview,
  normalizeExportFile,
  pieSegments
} from '../helpers.js';

export const dataManagementModule = {
  async loadDataManagement() {
    this.dataManagementLoading = true;
    try {
      const [overviewResult, exportsResult] = await Promise.all([
        getDataManagementOverview(),
        getDataManagementExports(),
      ]);
      this.dataManagementOverview = normalizeDataOverview(overviewResult);
      this.exportFiles = (exportsResult.items || []).map(normalizeExportFile);
    } catch (err) {
      this.showToast(`加载数据管理信息失败: ${err.message}`, 'error');
    } finally {
      this.dataManagementLoading = false;
    }
  },

  async openExportPreview(name) {
    if (!name) return;
    await this.runPending(`data-management:export-preview:${name}`, async () => {
      const result = await getDataManagementExportContent(name);
      this.exportPreview = {
        name: result.name || name,
        content: String(result.content || ''),
        size: Number(result.size || 0) || 0,
      };
      this.historyDetail = null;
      this.detailItems = [];
      this.panelMode = 'export-preview';
      this.panelExpanded = true;
      this.panelVisible = true;
    }).catch((err) => {
      this.showToast(`预览导出文件失败: ${err.message}`, 'error');
    });
  },

  async refreshDataManagement() {
    await this.runPending('data-management:refresh', () => this.loadDataManagement()).catch(
      () => {}
    );
  },

  async handleClearCache() {
    const ok = await this.showConfirm(
      '确定清理插件缓存目录？这会删除媒体缓存与临时转换产物。',
      '清理缓存',
      '清理'
    );
    if (!ok) return;
    await this.runPending('data-management:cache-clear', async () => {
      const result = await clearDataManagementCache();
      this.showToast(result.message || '缓存已清理');
      await this.loadDataManagement();
    }).catch((err) => {
      this.showToast(`清理缓存失败: ${err.message}`, 'error');
    });
  },

  async handleClearExports() {
    const ok = await this.showConfirm(
      '确定删除全部导出 TOML 文件？此操作不可恢复。',
      '清空导出',
      '清空'
    );
    if (!ok) return;
    await this.runPending('data-management:exports-clear', async () => {
      const result = await clearDataManagementExports();
      this.showToast(result.message || '导出文件已清空');
      await this.loadDataManagement();
    }).catch((err) => {
      this.showToast(`清空导出失败: ${err.message}`, 'error');
    });
  },

  async handleDeleteExportFile(name) {
    const ok = await this.showConfirm(
      `确定删除导出文件 ${name}？`,
      '删除导出文件',
      '删除'
    );
    if (!ok) return;
    await this.runPending(`data-management:export-delete:${name}`, async () => {
      const result = await deleteDataManagementExport(name);
      this.showToast(result.message || '导出文件已删除');
      await this.loadDataManagement();
    }).catch((err) => {
      this.showToast(`删除导出文件失败: ${err.message}`, 'error');
    });
  },

  cacheSegments() {
    return pieSegments(this.dataManagementOverview.cache.breakdown);
  },

  exportSegments() {
    return pieSegments(this.dataManagementOverview.exports.breakdown);
  },

  pieSegments(items) {
    return pieSegments(items);
  }
};
