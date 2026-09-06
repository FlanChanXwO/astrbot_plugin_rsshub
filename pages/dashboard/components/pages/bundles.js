export const bundlesActionsTemplate = String.raw`
      <div v-if="activeTab === 'bundles'" class="resource-toolbar">
        <label class="sr-only" for="bundle-search">搜索聚合订阅</label>
        <input id="bundle-search" class="search-input" type="search" v-model="bundleFilters.keyword" placeholder="搜索 Bundle 名称" @keyup.enter="runPending('bundles:refresh', () => loadBundles(true))" />
        <label class="sr-only" for="bundle-user-filter">按用户筛选</label>
        <input id="bundle-user-filter" class="search-input resource-user-filter" type="text" v-model="bundleFilters.userId" placeholder="用户 ID（可选）" @keyup.enter="runPending('bundles:refresh', () => loadBundles(true))" />
        <button class="btn btn-secondary" type="button" :class="{ 'is-loading': isPending('bundles:refresh') }" :disabled="isPending('bundles:refresh')" @click="runPending('bundles:refresh', () => loadBundles(true))">刷新</button>
      </div>
`;

export const bundlesPageTemplate = String.raw`
      <section v-if="activeTab === 'bundles'" class="resource-page">
        <div class="section-header resource-page-header">
          <div>
            <h2>聚合订阅</h2>
            <p class="section-subtitle">管理已有 Feed 的顺序、状态、卡片输出和可靠投递积压。创建 Bundle 或发现新 Feed 请使用命令或 AI tools。</p>
          </div>
          <span class="resource-count">共 {{ bundlesTotal }} 个</span>
        </div>
        <div v-if="!bundlesLoading && bundlesTotal > (bundlePagination.pageSize || 20)" class="pagination-bar resource-pagination">
          <span class="pagination-summary">第 {{ bundlePagination.page }} / {{ bundleTotalPages() }} 页</span>
          <div class="pagination-actions"><button class="btn btn-secondary btn-small" type="button" :disabled="bundlePagination.page <= 1" @click="bundlePrevPage()">上一页</button><span class="page-indicator">{{ bundlePagination.page }} / {{ bundleTotalPages() }}</span><button class="btn btn-secondary btn-small" type="button" :disabled="bundlePagination.page >= bundleTotalPages()" @click="bundleNextPage()">下一页</button></div>
        </div>
        <div v-if="bundlesLoading" class="resource-state" aria-live="polite"><span class="loading-spinner"></span><p>正在加载聚合订阅...</p></div>
        <div v-else-if="bundleLoadError" class="resource-state resource-state-error" role="alert">
          <p>{{ bundleLoadError }}</p>
          <button class="btn btn-secondary btn-small" type="button" @click="runPending('bundles:refresh', () => loadBundles(true))">重试</button>
        </div>
        <div v-else-if="bundles.length === 0" class="resource-state">
          <p>暂无聚合订阅</p>
          <p class="resource-state-help">通过聊天命令或 AI tools 创建 Bundle 后，它会出现在这里。</p>
        </div>
        <div v-else class="resource-grid bundle-grid">
          <article v-for="bundle in bundles" :key="bundle.id" class="resource-card bundle-card" @click="openBundleDetail(bundle)">
            <div class="resource-card-header">
              <div class="resource-card-title-wrap">
                <h3>{{ bundle.name || '未命名 Bundle' }}</h3>
                <span class="status-badge" :class="bundle.state === 1 ? 'active' : 'inactive'">{{ bundle.state === 1 ? '启用' : '停用' }}</span>
              </div>
              <span class="resource-card-id">#{{ bundle.id }}</span>
            </div>
            <dl class="resource-card-meta">
              <div><dt>用户</dt><dd class="cell-mono">{{ bundle.user_id }}</dd></div>
              <div><dt>目标会话</dt><dd class="cell-wrap">{{ (bundle.target_sessions || []).join('、') || '默认' }}</dd></div>
              <div><dt>刷新间隔</dt><dd>{{ bundle.interval || '默认' }} 分钟</dd></div>
              <div><dt>卡片</dt><dd>{{ bundle.send_card ? (bundle.template_id || '未选择模板') : '未启用' }}</dd></div>
            </dl>
            <div class="resource-card-footer">
              <span>{{ bundle.send_card ? '可靠批次输出' : '标准输出' }}</span>
              <button class="btn btn-text btn-action" type="button" @click.stop="openBundleDetail(bundle)" aria-label="打开 Bundle 详情">管理详情</button>
            </div>
          </article>
        </div>
      </section>

      <div class="bundle-detail-overlay" :class="{ visible: bundleDetailVisible }" @click="closeBundleDetail()"></div>
      <aside class="bundle-detail-drawer" :class="{ visible: bundleDetailVisible }" aria-label="聚合订阅详情" aria-live="polite">
        <div class="bundle-detail-header">
          <div>
            <p class="eyebrow">BUNDLE DETAIL</p>
            <h2>{{ bundleDetail?.name || '聚合订阅详情' }}</h2>
          </div>
          <button class="btn btn-icon" type="button" @click="closeBundleDetail()" aria-label="关闭聚合订阅详情">×</button>
        </div>
        <div v-if="bundleDetailLoading" class="resource-state drawer-state"><span class="loading-spinner"></span><p>正在加载详情...</p></div>
        <div v-else-if="bundleDetailError" class="resource-state resource-state-error drawer-state" role="alert"><p>{{ bundleDetailError }}</p><button class="btn btn-secondary btn-small" type="button" @click="reloadBundleDetail()">重试</button></div>
        <div v-else-if="bundleDetail" class="bundle-detail-content">
          <section class="detail-section">
            <div class="detail-section-heading"><h3>运行状态</h3><span class="resource-card-id">#{{ bundleDetail.id }}</span></div>
            <div class="detail-summary-grid">
              <div><span>用户</span><strong class="cell-wrap">{{ bundleDetail.user_id }}</strong></div>
              <div><span>目标</span><strong class="cell-wrap">{{ (bundleDetail.target_sessions || []).join('、') || '默认' }}</strong></div>
              <div><span>下次检查</span><strong>{{ formatDate(bundleDetail.next_check_time) }}</strong></div>
              <div><span>成员数</span><strong>{{ (bundleDetail.members || []).length }}</strong></div>
            </div>
            <div class="setting-row bundle-state-row">
              <span class="setting-label">Bundle 状态</span>
              <label class="toggle-switch"><input type="checkbox" :checked="bundleDetail.state === 1" @change="setBundleEnabled($event.target.checked)" /><span class="toggle-slider"></span><span class="toggle-label">{{ bundleDetail.state === 1 ? '启用' : '停用' }}</span></label>
            </div>
          </section>

          <section class="detail-section card-management-section">
            <div class="detail-section-heading"><div><h3>卡片输出</h3><p class="section-subtitle">模板采用高信任浏览器模型；模板作者提供的脚本和网络访问可能带来风险。</p></div></div>
            <div class="risk-note" role="note"><strong>风险提示</strong><span>只选择你信任的模板包。模板候选由全部成员 Feed 严格匹配，页面不会接受自由填写的模板 ID。</span></div>
            <div class="setting-row">
              <span class="setting-label">发送卡片</span>
              <label class="toggle-switch"><input type="checkbox" v-model="bundleDetail.send_card" /><span class="toggle-slider"></span><span class="toggle-label">{{ bundleDetail.send_card ? '开启' : '关闭' }}</span></label>
            </div>
            <div class="form-group">
              <label for="bundle-template-select">匹配模板</label>
              <select id="bundle-template-select" class="select-input resource-select" v-model="bundleDetail.template_id" :disabled="!bundleDetail.send_card || bundleTemplateOptionsLoading">
                <option value="">{{ bundleTemplateOptionsLoading ? '加载候选中...' : '请选择严格匹配模板' }}</option>
                <option v-for="template in bundleTemplateOptions" :key="template.id" :value="template.id">{{ template.name }} · v{{ template.version }} · {{ template.author }}</option>
              </select>
              <p v-if="!bundleTemplateOptionsLoading && bundleTemplateOptions.length === 0" class="field-help field-warning">当前成员组合没有可用模板，开启卡片前请先安装匹配的模板包。</p>
            </div>
            <div class="setting-row" v-if="bundleDetail.send_card">
              <span class="setting-label">卡片后继续原文</span>
              <label class="toggle-switch"><input type="checkbox" v-model="bundleDetail.card_send_original_content" /><span class="toggle-slider"></span><span class="toggle-label">{{ bundleDetail.card_send_original_content ? '开启' : '关闭' }}</span></label>
            </div>
            <p v-if="bundleCardError" class="field-error" role="alert">{{ bundleCardError }}</p>
            <div class="inline-actions">
              <button class="btn btn-secondary btn-small" type="button" :class="{ 'is-loading': isPending('bundle:preview:' + bundleDetail.id) }" :disabled="!bundlePreviewConfigurationValid() || isPending('bundle:preview:' + bundleDetail.id)" @click="previewBundleCard()">预览卡片</button>
              <button class="btn btn-primary btn-small" type="button" :class="{ 'is-loading': isPending('bundle:card:' + bundleDetail.id) }" :disabled="!bundleCardConfigurationValid() || isPending('bundle:card:' + bundleDetail.id)" @click="saveBundleCardConfiguration()">保存卡片配置</button>
            </div>
            <div v-if="bundlePreview" class="preview-result">
              <img :src="bundlePreview?.src || 'data:image/gif;base64,R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs='" alt="Bundle 卡片预览" />
              <p>预览包含 {{ bundlePreview?.entryCount ?? 0 }} 条处理后条目；不会写入水位、inbox、批次或历史。</p>
            </div>
          </section>

          <section class="detail-section">
            <div class="detail-section-heading"><div><h3>成员与顺序</h3><p class="section-subtitle">只管理已有 Feed；成员重排只影响尚未建立的批次。</p></div></div>
            <div v-if="bundleDetail.members.length === 0" class="mini-empty">暂无成员</div>
            <ol v-else class="bundle-member-list">
              <li v-for="(member, index) in bundleDetail.members" :key="member.feed_id + '-' + index" class="bundle-member-row">
                <span class="bundle-member-position">{{ index + 1 }}</span>
                <div class="bundle-member-main"><strong>{{ bundleMemberFeed(member)?.title || ('Feed #' + member.feed_id) }}</strong><span>{{ bundleMemberFeed(member)?.link || 'Feed ID ' + member.feed_id }}</span></div>
                <div class="bundle-member-actions">
                  <button class="btn btn-text btn-action" type="button" :disabled="index === 0" @click="moveBundleMember(index, -1)" aria-label="上移成员">上移</button>
                  <button class="btn btn-text btn-action" type="button" :disabled="index === bundleDetail.members.length - 1" @click="moveBundleMember(index, 1)" aria-label="下移成员">下移</button>
                  <button class="btn btn-text btn-action danger" type="button" @click="removeBundleMember(index)">移除</button>
                </div>
              </li>
            </ol>
            <div class="bundle-member-add">
              <label class="sr-only" for="bundle-new-member">添加已有 Feed</label>
              <select id="bundle-new-member" class="select-input" v-model="bundleNewMemberFeedId">
                <option value="">添加已有 Feed...</option>
                <option v-for="feed in availableBundleFeeds()" :key="feed.id" :value="String(feed.id)">{{ feed.title || ('Feed #' + feed.id) }}</option>
              </select>
              <button class="btn btn-secondary btn-small" type="button" :disabled="!bundleNewMemberFeedId" @click="addBundleMember()">添加</button>
            </div>
            <div class="inline-actions"><button class="btn btn-primary btn-small" type="button" :class="{ 'is-loading': isPending('bundle:members:' + bundleDetail.id) }" :disabled="isPending('bundle:members:' + bundleDetail.id)" @click="saveBundleMembers()">保存成员顺序</button></div>
          </section>

          <section class="detail-section">
            <div class="detail-section-heading"><div><h3>积压与未完成批次</h3><p class="section-subtitle">失败期间新内容继续入箱；未认领 backlog 不会因丢弃当前批次而消失。</p></div></div>
            <div class="backlog-summary"><strong>{{ bundleDetail.backlog?.unclaimed_count || 0 }}</strong><span>条未认领输入</span></div>
            <div v-if="bundleDetail.backlog?.items?.length" class="backlog-list">
              <div v-for="item in bundleDetail.backlog.items" :key="item.id || item.item_key" class="backlog-item"><strong>{{ item.entry_payload?.title || item.item_key || '未命名条目' }}</strong><span>Feed #{{ item.feed_id }} · {{ item.item_key }}</span></div>
            </div>
            <div v-else class="mini-empty">当前没有未认领 backlog</div>
            <div v-if="bundleDetail.pending_batch" class="pending-batch-card">
              <div class="pending-batch-heading"><strong>批次 #{{ bundleDetail.pending_batch.id }}</strong><span class="status-badge pending">{{ bundleDetail.pending_batch.status }}</span></div>
              <p>输出 {{ bundleDetail.pending_batch.output_count }} 条：{{ bundleDetail.pending_batch.output_statuses.join('、') || '暂无状态' }}</p>
              <button class="btn btn-danger btn-small" type="button" :class="{ 'is-loading': isPending('delivery-batch:discard:' + bundleDetail.pending_batch.id) }" :disabled="isPending('delivery-batch:discard:' + bundleDetail.pending_batch.id)" @click="discardBundlePendingBatch()">显式丢弃批次</button>
              <p class="field-help">重试请在“推送历史”中按批次查看每条输出；成功输出不会重复发送。</p>
            </div>
            <div v-else class="mini-empty">当前没有未完成批次</div>
          </section>

          <section class="detail-section danger-section">
            <button class="btn btn-danger" type="button" :class="{ 'is-loading': isPending('bundle:delete:' + bundleDetail.id) }" :disabled="isPending('bundle:delete:' + bundleDetail.id)" @click="deleteBundleFromPage()">删除聚合订阅</button>
            <p class="field-help">存在未解决批次或已认领输入时，后端会拒绝删除并返回阻塞详情。</p>
          </section>
        </div>
      </aside>
`;
