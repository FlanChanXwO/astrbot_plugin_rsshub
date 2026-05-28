import { batchToolbarTemplate, filterSummaryTemplate, tagFilterTemplate, textFilterTemplate } from '../shared/filters.js';

export const subscriptionsActionsTemplate = [
  "    <div class=\"action-bar\" v-if=\"activeTab === 'subs'\">",
  tagFilterTemplate({ groupName: 'subFilters', fieldName: 'user_id', label: '用户 ID' }),
  tagFilterTemplate({ groupName: 'subFilters', fieldName: 'feed_id', label: 'Feed ID' }),
  tagFilterTemplate({ groupName: 'subFilters', fieldName: 'feed_link', label: 'Feed URL', wide: true }),
  tagFilterTemplate({ groupName: 'subFilters', fieldName: 'sub_id', label: '订阅 ID' }),
  textFilterTemplate({ groupName: 'subFilters', fieldName: 'keyword', label: '关键词' }),
  "      <button class=\"btn btn-secondary\" @click=\"clearSubscriptionFilters()\" :disabled=\"isPending('subs:refresh') || !hasSubscriptionFilters()\">清空筛选</button>\n      <button class=\"btn\" :class=\"editMode ? 'btn-primary' : 'btn-secondary'\" @click=\"toggleEditMode()\">\n        {{ editMode ? '完成编辑' : '批量操作' }}\n      </button>\n      <button class=\"btn btn-icon\" :class=\"{ 'is-loading': isPending('subs:refresh') }\" :disabled=\"isPending('subs:refresh')\" @click=\"runPending('subs:refresh', () => loadData())\" title=\"刷新\">⟳</button>\n    </div>",
  filterSummaryTemplate({ tab: 'subs', guard: 'hasSubscriptionFilters', summary: 'subscriptionFilterSummary', clearAction: 'clearSubscriptionFilters' }),
  batchToolbarTemplate({ visibleExpr: 'editMode && selectedIds.length > 0', countExpr: 'selectedIds.length', buttons: [
    `<button class="btn btn-primary btn-small" :class="{ 'is-loading': isPending('batch:activate') }" :disabled="isPending('batch:activate')" @click="batchActivate()">批量启用</button>`,
    `<button class="btn btn-secondary btn-small" :class="{ 'is-loading': isPending('batch:deactivate') }" :disabled="isPending('batch:deactivate')" @click="batchDeactivate()">批量禁用</button>`,
    `<button class="btn btn-danger btn-small" :class="{ 'is-loading': isPending('batch:unsubscribe') }" :disabled="isPending('batch:unsubscribe')" @click="batchUnsubscribe()">批量取消</button>`,
  ] }),
].join('\n');

export const subscriptionsPageTemplate = String.raw`
      <section class="table-section" v-if="activeTab === 'subs'">
        <div class="section-header">
          <h2>订阅列表</h2>
          <span style="font-size:13px;color:#94a3b8;">共 {{ filteredSubs.length }} 个</span>
        </div>
        <div v-if="!loading && showSubPagination()" class="pagination-bar pagination-top">
          <span class="pagination-summary">第 {{ subPagination.page }} / {{ subTotalPages() }} 页，每页 {{ subPagination.pageSize }} 个</span>
          <div class="pagination-actions">
            <button class="btn btn-secondary btn-small" :disabled="subPagination.page <= 1" @click="subPrevPage()">上一页</button>
            <span class="page-indicator">{{ subPagination.page }} / {{ subTotalPages() }}</span>
            <button class="btn btn-secondary btn-small" :disabled="subPagination.page >= subTotalPages()" @click="subNextPage()">下一页</button>
          </div>
        </div>
        <div class="table-scroll-area">
          <div v-if="loading" class="empty-state"><p>加载中...</p></div>
          <div v-else-if="filteredSubs.length === 0" class="empty-state">
            <svg class="empty-state-icon" width="64" height="64" viewBox="0 0 1024 1024" xmlns="http://www.w3.org/2000/svg">
              <path d="M337.487 213.925c-6.537-6.547-15.571-10.598-25.553-10.598s-19.018 4.050-25.553 10.597l-256.357 256.383c-6.547 6.546-10.597 15.589-10.597 25.579 0 9.989 4.050 19.034 10.597 25.579l256.343 256.343c7.065 7.065 16.313 10.596 25.547 10.596s18.483-3.532 25.547-10.596c14.129-14.129 14.129-37.029 0-51.158l-230.72-230.758 230.733-230.797c6.555-6.547 10.61-15.596 10.61-25.591 0-9.989-4.05-19.034-10.597-25.579zM997.484 470.308l-256.343-256.382c-6.467-6.134-15.228-9.906-24.869-9.906-19.975 0-36.17 16.193-36.17 36.17 0 9.654 3.782 18.425 9.946 24.911l230.718 230.781-230.733 230.784c-6.551 6.546-10.604 15.593-10.604 25.585 0 19.969 16.183 36.159 36.149 36.17 9.236 0 18.484-3.532 25.548-10.596l256.343-256.343c6.558-6.545 10.615-15.595 10.615-25.591 0-9.99-4.052-19.035-10.603-25.579zM609.667 82.453c-2.506-0.624-5.381-0.981-8.34-0.981-17.042 0-31.313 11.868-34.999 27.789l-175.627 756.609c-0.583 2.435-0.917 5.231-0.917 8.105 0 20.022 16.229 36.255 36.252 36.259 17.063-0.034 31.356-11.861 35.158-27.763l175.499-756.59c0.598-2.463 0.942-5.292 0.942-8.199 0-17.066-11.82-31.372-27.719-35.177z" fill="#cbd5e0"/>
            </svg>
            <p>{{ hasSubscriptionFilters() ? '没有匹配的订阅' : '暂无订阅' }}</p>
            <p style="font-size:13px;margin-top:8px;">{{ hasSubscriptionFilters() ? '试试调整筛选条件' : '可通过聊天命令创建订阅' }}</p>
          </div>
          <table class="sub-table subs-table" v-else :class="{ 'edit-mode': editMode }">
            <thead>
              <tr>
                <th v-if="editMode" class="col-chk"></th>
                <th class="col-status">状态</th>
                <th class="col-feed">Feed</th>
                <th class="col-user">用户</th>
                <th class="col-interval">间隔</th>
                <th class="col-session">目标会话</th>
                <th class="col-actions">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="sub in pagedSubs()" :key="sub.id" :class="{ selected: selectedIds.includes(sub.id) }" @click="editMode ? toggleSelect(sub.id) : openDetailPanel(sub)">
                <td v-if="editMode" class="col-chk"><input type="checkbox" :checked="selectedIds.includes(sub.id)" @click.stop="toggleSelect(sub.id)" /></td>
                <td class="col-status" data-label="状态"><span class="status-dot" :class="sub.state === 1 ? 'active' : 'inactive'"></span><span class="status-text">{{ sub.state === 1 ? '启用' : '停用' }}</span></td>
                <td class="col-feed" data-label="Feed"><div class="feed-title">{{ sub.feed_title || '#' + sub.id }}</div><div class="feed-url" :title="sub.feed_link">{{ sub.feed_link || '' }}</div></td>
                <td class="col-user cell-mono" data-label="用户" :title="sub.user_id">{{ sub.user_id }}</td>
                <td class="col-interval" data-label="间隔">{{ sub.interval > 0 ? sub.interval + ' 分钟' : '继承' }}</td>
                <td class="col-session cell-mono" data-label="目标" :title="sub.target_session">{{ sub.target_session || '-' }}</td>
                <td class="col-actions" data-label="操作"><div class="action-cell"><button class="btn btn-text btn-action" :class="{ 'is-loading': isPending('sub:panel-edit:' + sub.id) }" :disabled="isPending('sub:panel-edit:' + sub.id)" @click.stop="openEditPanel(sub)" title="编辑">编辑</button><button class="btn btn-text btn-action" :class="{ 'is-loading': isPending('feed:refresh:' + sub.feed_id) }" :disabled="isPending('feed:refresh:' + sub.feed_id)" @click.stop="handleRefreshDetail(sub.feed_id)" title="刷新">刷新</button></div></td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

`;
