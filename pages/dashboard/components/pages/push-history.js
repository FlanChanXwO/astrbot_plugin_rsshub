import { filterSummaryTemplate, tagFilterTemplate, textFilterTemplate } from '../shared/filters.js';

export const pushHistoryActionsTemplate = [
  "    <div class=\"action-bar push-history-action-bar\" v-if=\"activeTab === 'push-history'\">",
  tagFilterTemplate({ groupName: 'pushHistoryFilter', fieldName: 'feed_link', label: 'Feed URL', wide: true }),
  textFilterTemplate({ groupName: 'pushHistoryFilter', fieldName: 'keyword', label: '关键词或 ID', placeholder: '输入关键词或 ID', wide: true }),
  "      <select class=\"select-input\" v-model=\"pushHistoryFilter.status\" @change=\"onPushHistoryStatusChanged()\">\n        <option value=\"\">全部状态</option>\n        <option value=\"pending\">待推送</option>\n        <option value=\"success\">成功</option>\n        <option value=\"failed\">失败</option>\n        <option value=\"stopped\">已停止</option>\n      </select>\n      <button class=\"btn btn-secondary\" :disabled=\"isPending('push-history:refresh') || !hasPushHistoryFilters()\" @click=\"clearPushHistoryFilters()\">清空筛选</button>\n      <button class=\"btn\" :class=\"pushHistoryEditMode ? 'btn-primary' : 'btn-secondary'\" @click=\"togglePushHistoryEditMode()\">\n        {{ pushHistoryEditMode ? '完成编辑' : '批量操作' }}\n      </button>\n      <button class=\"btn btn-secondary\" @click=\"openPushHistorySettingsPanel()\">清理设置</button>\n      <button class=\"btn btn-icon\" :class=\"{ 'is-loading': isPending('push-history:refresh') }\" :disabled=\"isPending('push-history:refresh')\" @click=\"runPending('push-history:refresh', () => loadPushHistory())\" title=\"刷新\">⟳</button>\n    </div>",
  filterSummaryTemplate({ tab: 'push-history', guard: 'hasPushHistoryFilters', summary: 'pushHistoryFilterSummary', clearAction: 'clearPushHistoryFilters' }),
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
            <tbody>
              <tr
                v-for="h in pushHistory"
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
                <td class="col-feed" data-label="条目"><div class="feed-title">{{ h.entry_title || '无标题' }}</div><div class="feed-url" :title="h.entry_link">{{ h.feed_title || '' }}</div></td>
                <td class="col-session cell-mono" data-label="目标" :title="h.target_session">{{ h.target_session || '-' }}</td>
                <td class="col-error cell-wrap" data-label="错误" :title="h.fail_reason || ''">{{ h.fail_reason || '-' }}</td>
                <td class="col-interval" data-label="重试">{{ h.retry_count }}/{{ h.max_retries }}</td>
                <td class="col-actions" data-label="操作">
                  <div class="action-cell">
                    <button class="btn btn-text btn-action" @click.stop="openPushHistoryDetail(h)">详情</button>
                    <button class="btn btn-text btn-action" :class="{ 'is-loading': isPending('push-history:retry:' + h.id) }" :disabled="isPending('push-history:retry:' + h.id)" @click.stop="retryPushHistoryItem(h.id)">重试</button>
                    <button class="btn btn-text btn-action danger" :class="{ 'is-loading': isPending('push-history:delete:' + h.id) }" :disabled="isPending('push-history:delete:' + h.id)" @click.stop="deletePushHistoryItem(h.id)">删除</button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

`;
