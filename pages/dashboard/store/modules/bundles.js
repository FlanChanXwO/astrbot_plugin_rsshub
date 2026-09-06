import {
  deleteBundle,
  discardDeliveryBatch,
  getBundleDetail,
  getBundles,
  getFeeds,
  getTemplateOptions,
  previewTemplate,
  setBundleState,
  updateBundle,
  updateBundleMembers,
} from '../../js/api.js';

function stringifyDetails(details) {
  if (details === undefined || details === null) return '';
  if (typeof details === 'string') return details;
  try {
    return JSON.stringify(details, null, 2);
  } catch {
    return String(details);
  }
}

export function normalizeBundleDetail(result) {
  const data = result?.data || {};
  const bundle = data.bundle || data;
  return {
    ...bundle,
    members: Array.isArray(data.members) ? data.members.map((member) => ({ ...member })) : [],
    backlog: data.backlog || { unclaimed_count: 0, items: [] },
    pending_batch: data.pending_batch || null,
  };
}

export const bundlesModule = {
  async loadBundles(resetPage = false) {
    this.bundlesLoading = true;
    this.bundleLoadError = '';
    if (resetPage) this.bundlePagination.page = 1;
    try {
      const result = await getBundles({
        userId: this.bundleFilters.userId,
        keyword: this.bundleFilters.keyword,
        page: this.bundlePagination.page,
        pageSize: this.bundlePagination.pageSize,
      });
      this.bundles = result.items || [];
      this.bundlesTotal = result.total || 0;
      this.bundlePagination.page = result.page || this.bundlePagination.page;
      this.bundlePagination.pageSize = result.page_size || this.bundlePagination.pageSize;
      if (this.bundlePagination.page > this.bundleTotalPages()) {
        this.bundlePagination.page = this.bundleTotalPages();
        await this.loadBundles(false);
      }
    } catch (err) {
      this.bundleLoadError = err.message || 'Bundle 列表加载失败';
      this.showToast(`加载聚合订阅失败: ${this.bundleLoadError}`, 'error');
    } finally {
      this.bundlesLoading = false;
    }
  },

  bundleTotalPages() {
    return Math.max(1, Math.ceil(this.bundlesTotal / (this.bundlePagination.pageSize || 20)));
  },

  bundlePrevPage() {
    if (this.bundlePagination.page <= 1) return;
    this.bundlePagination.page -= 1;
    void this.loadBundles(false);
  },

  bundleNextPage() {
    if (this.bundlePagination.page >= this.bundleTotalPages()) return;
    this.bundlePagination.page += 1;
    void this.loadBundles(false);
  },

  async openBundleDetail(bundle) {
    const bundleId = Number(bundle?.id || 0);
    const userId = String(bundle?.user_id || '').trim();
    if (!bundleId || !userId) return;
    this.bundleDetailVisible = true;
    this.bundleDetailLoading = true;
    this.bundleDetailError = '';
    this.bundleCardError = '';
    this.bundlePreview = null;
    try {
      const [detailResult, feedsResult] = await Promise.all([
        getBundleDetail(bundleId, userId),
        getFeeds(),
      ]);
      this.bundleDetail = normalizeBundleDetail(detailResult);
      this.bundleAvailableFeeds = feedsResult.items || [];
      await this.loadBundleTemplateOptions();
    } catch (err) {
      this.bundleDetailError = err.message || 'Bundle 详情加载失败';
      this.showToast(`加载聚合订阅详情失败: ${this.bundleDetailError}`, 'error');
    } finally {
      this.bundleDetailLoading = false;
    }
  },

  async reloadBundleDetail() {
    if (!this.bundleDetail) return;
    await this.openBundleDetail(this.bundleDetail);
  },

  closeBundleDetail() {
    this.bundleDetailVisible = false;
    this.bundleDetailLoading = false;
    this.bundleDetailError = '';
    this.bundlePreview = null;
  },

  bundleMemberFeed(member) {
    const feedId = Number(member?.feed_id || 0);
    return this.bundleAvailableFeeds.find((feed) => Number(feed.id) === feedId) || null;
  },

  bundleMemberIds() {
    return (this.bundleDetail?.members || []).map((member) => Number(member.feed_id || 0));
  },

  availableBundleFeeds() {
    const selected = new Set(this.bundleMemberIds());
    return this.bundleAvailableFeeds.filter((feed) => !selected.has(Number(feed.id)));
  },

  addBundleMember() {
    const feedId = Number(this.bundleNewMemberFeedId || 0);
    if (!feedId || !this.bundleDetail || this.bundleMemberIds().includes(feedId)) return;
    this.bundleDetail.members.push({
      bundle_id: this.bundleDetail.id,
      feed_id: feedId,
      position: this.bundleDetail.members.length,
    });
    this.bundleNewMemberFeedId = '';
  },

  removeBundleMember(index) {
    if (!this.bundleDetail?.members?.[index]) return;
    this.bundleDetail.members.splice(index, 1);
    this.reindexBundleMembers();
  },

  moveBundleMember(index, delta) {
    const members = this.bundleDetail?.members;
    const target = index + delta;
    if (!Array.isArray(members) || !members[index] || target < 0 || target >= members.length) {
      return;
    }
    const [member] = members.splice(index, 1);
    members.splice(target, 0, member);
    this.reindexBundleMembers();
  },

  reindexBundleMembers() {
    for (const [position, member] of (this.bundleDetail?.members || []).entries()) {
      member.position = position;
    }
  },

  async saveBundleMembers() {
    if (!this.bundleDetail) return;
    const feedIds = this.bundleMemberIds();
    if (new Set(feedIds).size !== feedIds.length) {
      this.showToast('Bundle 成员不能重复', 'error');
      return;
    }
    const id = Number(this.bundleDetail.id || 0);
    await this.runPending(`bundle:members:${id}`, async () => {
      await updateBundleMembers(id, this.bundleDetail.user_id, feedIds);
      this.showToast('Bundle 成员顺序已保存');
      await this.reloadBundleDetail();
      await this.loadBundles(false);
    }).catch((err) => {
      this.showToast(`保存 Bundle 成员失败: ${err.message}`, 'error');
    });
  },

  async loadBundleTemplateOptions() {
    if (!this.bundleDetail) return;
    this.bundleTemplateOptionsLoading = true;
    this.bundleCardError = '';
    try {
      const result = await getTemplateOptions(
        'bundle',
        this.bundleDetail.id,
        this.bundleDetail.user_id,
      );
      this.bundleTemplateOptions = result.items || [];
      if (
        this.bundleDetail.send_card &&
        !this.bundleTemplateOptions.some((item) => item.id === this.bundleDetail.template_id)
      ) {
        this.bundleCardError = '当前 Bundle 没有匹配的模板候选，不能启用或保存卡片配置。';
      }
    } catch (err) {
      this.bundleTemplateOptions = [];
      this.bundleCardError = err.message || '模板候选加载失败';
    } finally {
      this.bundleTemplateOptionsLoading = false;
    }
  },

  bundleCardConfigurationValid() {
    if (!this.bundleDetail?.send_card) return true;
    return Boolean(
      this.bundleDetail.template_id &&
        this.bundleTemplateOptions.some((item) => item.id === this.bundleDetail.template_id),
    );
  },

  bundlePreviewConfigurationValid() {
    return Boolean(this.bundleDetail?.send_card) && this.bundleCardConfigurationValid();
  },

  async saveBundleCardConfiguration() {
    if (!this.bundleDetail) return;
    if (!this.bundleCardConfigurationValid()) {
      this.bundleCardError = '请先选择当前 Bundle 的严格匹配模板候选。';
      return;
    }
    const id = Number(this.bundleDetail.id || 0);
    await this.runPending(`bundle:card:${id}`, async () => {
      await updateBundle(id, this.bundleDetail.user_id, {
        send_card: Boolean(this.bundleDetail.send_card),
        template_id: this.bundleDetail.send_card ? this.bundleDetail.template_id : null,
        card_send_original_content: Boolean(this.bundleDetail.card_send_original_content),
      });
      this.showToast('Bundle 卡片配置已保存');
      await this.reloadBundleDetail();
      await this.loadBundles(false);
    }).catch((err) => {
      this.bundleCardError = err.message || 'Bundle 卡片配置保存失败';
      this.showToast(`保存卡片配置失败: ${this.bundleCardError}`, 'error');
    });
  },

  async previewBundleCard() {
    if (!this.bundleDetail || !this.bundlePreviewConfigurationValid()) {
      this.bundleCardError = '请先选择当前 Bundle 的严格匹配模板候选。';
      return;
    }
    const id = Number(this.bundleDetail.id || 0);
    await this.runPending(`bundle:preview:${id}`, async () => {
      const result = await previewTemplate({
        ownerType: 'bundle',
        ownerId: id,
        userId: this.bundleDetail.user_id,
        templateId: this.bundleDetail.template_id,
      });
      this.bundlePreview = {
        src: `data:image/png;base64,${result.png_base64}`,
        entryCount: result.entry_count || 0,
        template: result.template || {},
        sourceSummary: result.source_summary || {},
      };
    }).catch((err) => {
      this.bundleCardError = err.message || 'Bundle 预览失败';
      this.showToast(`Bundle 预览失败: ${this.bundleCardError}`, 'error');
    });
  },

  async setBundleEnabled(enabled) {
    if (!this.bundleDetail) return;
    if (enabled && this.bundleDetail.send_card && !this.bundleCardConfigurationValid()) {
      this.bundleCardError = '没有匹配模板时不能启用 Bundle。';
      return;
    }
    const id = Number(this.bundleDetail.id || 0);
    await this.runPending(`bundle:state:${id}`, async () => {
      await setBundleState(id, this.bundleDetail.user_id, enabled ? 1 : 0);
      this.showToast(enabled ? 'Bundle 已启用' : 'Bundle 已停用');
      await this.reloadBundleDetail();
      await this.loadBundles(false);
    }).catch((err) => {
      this.showToast(`更新 Bundle 状态失败: ${err.message}`, 'error');
    });
  },

  async deleteBundleFromPage() {
    if (!this.bundleDetail) return;
    const id = Number(this.bundleDetail.id || 0);
    const confirmed = await this.showConfirm(
      '删除只会在没有未解决批次或已认领输入时执行；已解决推送历史会保留。确定继续？',
      '删除聚合订阅',
      '删除',
      'btn-danger',
    );
    if (!confirmed) return;
    await this.runPending(`bundle:delete:${id}`, async () => {
      await deleteBundle(id, this.bundleDetail.user_id);
      this.showToast('聚合订阅已删除');
      this.closeBundleDetail();
      await this.loadBundles(false);
    }).catch((err) => {
      const details = stringifyDetails(err.details);
      const message = details ? `${err.message}\n${details}` : err.message;
      this.showToast(`删除聚合订阅失败: ${message}`, 'error', 6000);
    });
  },

  async discardBundlePendingBatch() {
    const batchId = Number(this.bundleDetail?.pending_batch?.id || 0);
    if (!batchId) return;
    const confirmed = await this.showConfirm(
      '丢弃会将当前未完成输出标记为 discarded，并消费本批已认领输入；未认领 backlog 不受影响。',
      '丢弃未完成批次',
      '确认丢弃',
      'btn-danger',
    );
    if (!confirmed) return;
    await this.runPending(`delivery-batch:discard:${batchId}`, async () => {
      await discardDeliveryBatch(batchId, 'Dashboard 用户显式丢弃');
      this.showToast(`批次 ${batchId} 已丢弃`);
      await this.reloadBundleDetail();
    }).catch((err) => {
      const details = stringifyDetails(err.details);
      this.showToast(`丢弃批次失败: ${details ? `${err.message}\n${details}` : err.message}`, 'error', 6000);
    });
  },
};
