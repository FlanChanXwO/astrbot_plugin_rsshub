import { batchToolbarTemplate, compactFilterToolbarTemplate } from '../shared/filters.js';

export const feedsActionsTemplate = [
  compactFilterToolbarTemplate({
    groupName: 'feedFilters',
    visibleExpr: "activeTab === 'feeds'",
    pendingKey: 'feeds:refresh',
    loadAction: 'loadFeeds()',
    clearAction: 'clearFeedFilters',
    hasFilters: 'hasFeedFilters',
    extraButtons: [
      `<button class="btn" :class="feedEditMode ? 'btn-primary' : 'btn-secondary'" type="button" @click="toggleFeedEditMode()">{{ feedEditMode ? '完成编辑' : '批量操作' }}</button>`,
    ],
  }),
  batchToolbarTemplate({ visibleExpr: 'feedEditMode && selectedFeedIds.length > 0', countExpr: 'selectedFeedIds.length', buttons: [
    `<button class="btn btn-primary btn-small" :class="{ 'is-loading': isPending('feeds:refresh-batch') }" :disabled="isPending('feeds:refresh-batch')" @click="refreshSelectedFeeds()">批量刷新</button>`,
    `<button class="btn btn-danger btn-small" :class="{ 'is-loading': isPending('feeds:delete-batch') }" :disabled="isPending('feeds:delete-batch')" @click="deleteSelectedFeeds()">批量删除</button>`,
  ] }),
].join('\n');

export const feedsPageTemplate = String.raw`
      <section class="table-section" v-if="activeTab === 'feeds'">
        <div class="section-header">
          <h2>Feed 源</h2>
          <span style="font-size:13px;color:#94a3b8;">共 {{ feeds.length }} 个</span>
        </div>
        <div class="table-scroll-area">
          <div v-if="feedsLoading" class="empty-state"><p>加载中...</p></div>
          <div v-else-if="feeds.length === 0" class="empty-state"><p>暂无 Feed 源</p></div>
          <table class="sub-table feeds-table" v-else>
            <thead><tr><th v-if="feedEditMode" class="col-chk"><input type="checkbox" :checked="areAllFeedsSelected()" @click.stop @change="toggleAllFeedSelection()" /></th><th class="col-feed">Feed</th><th class="col-interval">订阅数</th><th class="col-status">状态</th><th class="col-actions">操作</th></tr></thead>
            <tbody>
              <tr v-for="f in feeds" :key="f.id" :class="{ selected: selectedFeedIds.includes(f.id) }" @click="feedEditMode ? toggleFeedSelection(f.id) : selectFeed(f.id)">
                <td v-if="feedEditMode" class="col-chk"><input type="checkbox" :checked="selectedFeedIds.includes(f.id)" @click.stop="toggleFeedSelection(f.id)" /></td>
                <td class="col-feed" data-label="Feed"><div class="feed-title">{{ f.title || '未知' }}</div><div class="feed-url" :title="f.link">{{ f.link || '' }}</div></td>
                <td class="col-interval" data-label="订阅数">{{ f.subscription_count }}</td>
                <td class="col-status" data-label="状态"><span class="status-dot" :class="f.state === 1 ? 'active' : 'inactive'"></span> {{ f.state === 1 ? '启用' : '停用' }}</td>
                <td class="col-actions" data-label="操作"><div class="action-cell"><button class="btn btn-text btn-action" :class="{ 'is-loading': isPending('feed:save:' + f.id) }" :disabled="isPending('feed:save:' + f.id)" @click.stop="openFeedEditPanel(f)">编辑</button><button class="btn btn-text btn-action" :class="{ 'is-loading': isPending('feed:refresh:' + f.id) }" :disabled="isPending('feed:refresh:' + f.id)" @click.stop="handleRefreshDetail(f.id)">刷新</button><button class="btn btn-text btn-action danger" :class="{ 'is-loading': isPending('feed:delete:' + f.id) }" :disabled="isPending('feed:delete:' + f.id)" @click.stop="handleDeleteFeed(f.id)">删除</button></div></td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

`;
