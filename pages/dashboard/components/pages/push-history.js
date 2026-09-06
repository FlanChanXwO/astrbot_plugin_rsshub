import { compactFilterToolbarTemplate } from '../shared/filters.js';

export const pushHistoryActionsTemplate = [
  compactFilterToolbarTemplate({
    groupName: 'pushHistoryFilter',
    visibleExpr: "activeTab === 'push-history'",
    pendingKey: 'push-history:refresh',
    loadAction: 'loadPushHistory()',
    clearAction: 'clearPushHistoryFilters',
    hasFilters: 'hasPushHistoryFilters',
    extraButtons: [
      `<button class="btn" :class="pushHistoryEditMode ? 'btn-primary' : 'btn-secondary'" type="button" @click="togglePushHistoryEditMode()">{{ pushHistoryEditMode ? '完成编辑' : '批量操作' }}</button>`,
      `<button class="btn btn-secondary" type="button" @click="openPushHistorySettingsPanel()">清理设置</button>`,
    ],
  }),
].join('\n');

export const pushHistoryPageTemplate = String.raw`
      <section v-if="activeTab === 'push-history'" class="table-section">
        <div class="section-header">
          <h2>推送历史</h2>
          <span style="font-size:13px;color:#94a3b8;">共 {{ pushHistoryTotal }} 条</span>
        </div>
        <div class="batch-toolbar" :class="{ visible: pushHistoryEditMode && selectedPushHistoryIds.length > 0 }">
          <span class="count">已选 {{ selectedPushHistoryIds.length }} 项</span>
          <button class="btn btn-danger btn-small" :class="{ 'is-loading': isPending('push-history:delete-batch') }" :disabled="isPending('push-history:delete-batch')" @click="deleteSelectedPushHistory()">批量删除</button>
        </div>
        <div v-if="!pushHistoryLoading && showPushHistoryPagination()" class="pagination-bar pagination-top">
          <span class="pagination-summary">共 {{ pushHistoryTotal }} 条，第 {{ pushHistoryFilter.page }} / {{ pushHistoryTotalPages() }} 页</span>
          <div class="pagination-actions">
            <button class="btn btn-secondary btn-small" :disabled="pushHistoryFilter.page <= 1" @click="pushHistoryPrevPage()">上一页</button>
            <span class="page-indicator">{{ pushHistoryFilter.page }} / {{ pushHistoryTotalPages() }}</span>
            <button class="btn btn-secondary btn-small" :disabled="pushHistoryFilter.page >= pushHistoryTotalPages()" @click="pushHistoryNextPage()">下一页</button>
          </div>
        </div>
        <div class="table-scroll-area">
          <div v-if="pushHistoryLoading" class="empty-state"><p>加载中...</p></div>
          <div v-else-if="pushHistory.length === 0" class="empty-state"><p>暂无推送历史</p></div>
          <table class="sub-table history-table" v-else>
            <thead>
              <tr>
                <th v-if="pushHistoryEditMode" class="col-chk">
                  <input
                    type="checkbox"
                    :checked="areAllPushHistorySelected()"
                    @click.stop
                    @change="toggleAllPushHistorySelection()"
                  />
                </th>
                <th class="col-status">状态</th>
                <th class="col-user">用户</th>
                <th class="col-feed">条目</th>
                <th class="col-session">目标会话</th>
                <th class="col-error">错误</th>
                <th class="col-interval">重试</th>
                <th class="col-actions">操作</th>
              </tr>
            </thead>
            <tbody v-for="group in pushHistoryGroups()" :key="group.key">
              <tr class="history-batch-header">
                <td :colspan="pushHistoryEditMode ? 8 : 7">
                  <div class="history-batch-heading">
                    <div>
                      <strong>{{ group.batchId ? '可靠批次 #' + group.batchId : '单条输出' }}</strong>
                      <span v-if="group.batchId">{{ group.items.length }} 条输出 · {{ group.hasUnresolvedOutput ? '仍有未完成输出' : '输出已完成或已丢弃' }}</span>
                      <span v-if="group.template">模板：{{ group.template.metadata?.id || group.template.id || group.template.name || '已固化模板' }}</span>
                      <span v-if="group.bundleId">Bundle #{{ group.bundleId }}{{ group.memberCount ? ' · ' + group.memberCount + ' 个成员' : '' }}</span>
                    </div>
                    <button v-if="group.batchId && group.hasUnresolvedOutput" class="btn btn-danger btn-small" type="button" :class="{ 'is-loading': isPending('delivery-batch:discard:' + group.batchId) }" :disabled="isPending('delivery-batch:discard:' + group.batchId)" @click.stop="discardPushHistoryBatch(group.batchId)">丢弃批次</button>
                  </div>
                </td>
              </tr>
              <tr
                v-for="h in group.items"
                :key="h.id"
                :class="{ selected: isPushHistorySelected(h.id) }"
                @click="openPushHistorySubscriptions(h)"
              >
                <td v-if="pushHistoryEditMode" class="col-chk" data-label="选择">
                  <input
                    type="checkbox"
                    :checked="isPushHistorySelected(h.id)"
                    @click.stop
                    @change="togglePushHistorySelect(h.id)"
                  />
                </td>
                <td class="col-status" data-label="状态"><span class="status-badge" :class="h.status">{{ h.status }}</span></td>
                <td class="col-user cell-mono" data-label="用户" :title="h.user_id">{{ h.user_id }}</td>
                <td class="col-feed" data-label="条目"><div class="feed-title">{{ h.output_kind ? h.output_kind + ' · ' : '' }}{{ h.entry_title || (h.output_kind === 'card' ? '卡片输出' : '聚合/标准输出') }}</div><div class="feed-url" :title="h.entry_link">{{ h.feed_title || h.source_type || '' }}{{ h.output_order !== undefined ? ' · 顺序 ' + h.output_order : '' }}</div></td>
                <td class="col-session cell-mono" data-label="目标" :title="h.target_session">{{ h.target_session || '-' }}</td>
                <td class="col-error cell-wrap" data-label="错误" :title="h.fail_reason || ''">{{ h.fail_reason || '-' }}</td>
                <td class="col-interval" data-label="重试">{{ h.retry_count }}/{{ h.max_retries }}</td>
                <td class="col-actions" data-label="操作">
                  <div class="action-cell">
                    <button class="btn btn-text btn-action" type="button" @click.stop="openPushHistoryDetail(h)">详情</button>
                    <button class="btn btn-text btn-action" type="button" :class="{ 'is-loading': isPending('push-history:retry:' + h.id) }" :disabled="isPending('push-history:retry:' + h.id)" @click.stop="retryPushHistoryItem(h.id)">重试</button>
                    <button class="btn btn-text btn-action danger" type="button" :class="{ 'is-loading': isPending('push-history:delete:' + h.id) }" :disabled="Boolean(h.batch_id && group.hasUnresolvedOutput) || isPending('push-history:delete:' + h.id)" :title="h.batch_id && group.hasUnresolvedOutput ? '未完成批次不能单独删除，请重试或丢弃批次' : '删除'" @click.stop="deletePushHistoryItem(h.id)">删除</button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

`;
