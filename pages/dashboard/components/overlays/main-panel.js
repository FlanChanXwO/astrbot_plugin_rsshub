export const mainPanelTemplate = String.raw`
  <div class="panel-overlay" :class="{ visible: panelVisible }" @click="closePanel()"></div>

  <section class="edit-panel" :class="{ 'panel-visible': panelVisible, expanded: panelExpanded }">
    <div class="panel-header">
      <h3>{{ panelTitle() }}</h3>
      <div class="panel-actions">
        <button type="button" class="btn btn-icon" title="展开" @click="panelExpanded = !panelExpanded">{{ panelExpanded ? '⇋' : '⛶' }}</button>
        <button class="btn btn-icon" :class="{ 'is-loading': closePanelDisabled() }" :disabled="closePanelDisabled()" @click="closePanel()">×</button>
      </div>
    </div>

    <form v-if="panelMode === 'edit'" class="form" @submit.prevent="handleEditSub()">
      <div class="panel-section">
        <h4>基本信息</h4>
        <div class="detail-row"><span class="detail-label">Feed</span><span class="detail-value">{{ editForm.feed_title || editForm.feed_link }}</span></div>
        <div class="detail-row"><span class="detail-label">用户</span><span class="detail-value">{{ editForm.user_id }}</span></div>
        <div class="form-group">
          <label>标题</label>
          <div class="input-wrapper"><input type="text" v-model="editForm.title" placeholder="订阅显示名称" /></div>
        </div>
        <div class="form-group">
          <label>标签</label>
          <div class="input-wrapper"><input type="text" v-model="editForm.tags" placeholder="news,tech" /></div>
        </div>
      </div>
      <div class="panel-section">
        <h4>推送设置</h4>
        <div class="form-group">
          <label>目标会话</label>
          <div class="input-wrapper"><input type="text" v-model="editForm.target_session" /></div>
        </div>
        <div class="form-group">
          <label>内容处理链</label>
          <div class="handler-editor">
            <div class="setting-row">
              <span class="setting-label">处理链模式</span>
              <select class="select-input" v-model="editForm.handlers_mode">
                <option value="inherit">继承用户设置</option>
                <option value="override">使用订阅设置</option>
                <option value="disabled">禁用全部处理链</option>
              </select>
            </div>
            <div v-if="editForm.handlers_mode === 'override'" class="handler-json">
              <textarea v-model="editForm.handlers_json" rows="10"></textarea>
              <button type="button" class="btn btn-secondary btn-small" @click="applyHandlersJson(editForm)">应用 JSON</button>
            </div>
            <div v-else class="handler-empty">{{ editForm.handlers_mode === 'inherit' ? '当前订阅继承用户处理链' : '当前订阅禁用全部处理链' }}</div>
          </div>
        </div>
        <div class="form-group">
          <label>刷新间隔（分钟）</label>
          <div class="inherit-control">
            <select class="select-input" v-model="editForm.interval_control.mode">
              <option value="inherit">继承</option>
              <option value="custom">自定义</option>
            </select>
            <div v-if="editForm.interval_control.mode === 'custom'" class="input-wrapper"><input type="number" v-model.number="editForm.interval_control.value" min="1" max="1440" /></div>
          </div>
        </div>
        <div class="setting-row">
          <span class="setting-label">状态</span>
          <label class="toggle-switch"><input type="checkbox" v-model="editForm.state_" /><span class="toggle-slider"></span><span class="toggle-label">{{ editForm.state_ ? '启用' : '停用' }}</span></label>
        </div>
      </div>
      <div class="panel-section">
        <h4>显示选项</h4>
        <div class="setting-row"><span class="setting-label">发送模式</span><select class="select-input" v-model.number="editForm.send_mode"><option :value="-100">继承</option><option :value="-1">仅链接</option><option :value="0">自动</option><option :value="1">直接发送</option></select></div>
        <div class="setting-row"><span class="setting-label">通知</span><select class="select-input" v-model.number="editForm.notify"><option :value="-100">继承</option><option :value="0">禁用</option><option :value="1">启用</option></select></div>
        <div class="setting-row"><span class="setting-label">内容长度限制</span><div class="inherit-control"><select class="select-input" v-model="editForm.length_limit_control.mode"><option value="inherit">继承</option><option value="custom">自定义</option></select><div v-if="editForm.length_limit_control.mode === 'custom'" class="input-wrapper"><input type="number" v-model.number="editForm.length_limit_control.value" min="0" max="10000" /></div></div></div>
        <div class="setting-row"><span class="setting-label">显示作者</span><select class="select-input" v-model.number="editForm.display_author"><option :value="-100">继承</option><option :value="-1">禁用</option><option :value="0">自动</option><option :value="1">强制</option></select></div>
        <div class="setting-row"><span class="setting-label">显示来源</span><select class="select-input" v-model.number="editForm.display_via"><option :value="-100">继承</option><option :value="-2">完全禁用</option><option :value="-1">仅链接</option><option :value="0">自动</option><option :value="1">强制</option></select></div>
        <div class="setting-row"><span class="setting-label">显示标题</span><select class="select-input" v-model.number="editForm.display_title"><option :value="-100">继承</option><option :value="-1">禁用</option><option :value="0">自动</option><option :value="1">强制</option></select></div>
        <div class="setting-row"><span class="setting-label">显示标签</span><select class="select-input" v-model.number="editForm.display_entry_tags"><option :value="-100">继承</option><option :value="-1">禁用</option><option :value="0">启用</option></select></div>
        <div class="setting-row"><span class="setting-label">排版策略</span><select class="select-input" v-model.number="editForm.style"><option :value="-100">继承</option><option :value="0">自动</option><option :value="1">RSSRT</option><option :value="2">原始顺序</option></select></div>
        <div class="setting-row"><span class="setting-label">显示媒体</span><select class="select-input" v-model.number="editForm.display_media"><option :value="-100">继承</option><option :value="-1">禁用</option><option :value="0">启用</option></select></div>
      </div>
      <div class="form-actions">
        <button type="button" class="btn btn-danger" :class="{ 'is-loading': isPending('sub:delete:' + editForm.id) }" :disabled="isPending('sub:delete:' + editForm.id)" @click="handleDeleteSub()">删除订阅</button>
        <div class="center-actions">
          <button type="button" class="btn btn-text" @click="closePanel()">取消</button>
          <button type="submit" class="btn btn-primary" :class="{ 'is-loading': isPending('sub:save:' + editForm.id) }" :disabled="isPending('sub:save:' + editForm.id)">{{ isPending('sub:save:' + editForm.id) ? '保存中...' : '保存修改' }}</button>
        </div>
      </div>
    </form>

    <div v-else-if="panelMode === 'detail'" class="form">
      <div class="panel-section">
        <h4>订阅信息</h4>
        <div class="detail-row"><span class="detail-label">ID</span><span class="detail-value">{{ detailSub.id }}</span></div>
        <div class="detail-row"><span class="detail-label">状态</span><span class="detail-value"><span class="status-badge" :class="detailSub.state === 1 ? 'active' : 'inactive'">{{ detailSub.state === 1 ? '启用' : '停用' }}</span></span></div>
        <div class="detail-row"><span class="detail-label">Feed</span><span class="detail-value">{{ detailSub.feed_title || '未知' }}</span></div>
        <div class="detail-row"><span class="detail-label">链接</span><span class="detail-value cell-wrap">{{ detailSub.feed_link }}</span></div>
        <div class="detail-row"><span class="detail-label">用户</span><span class="detail-value">{{ detailSub.user_id }}</span></div>
        <div class="detail-row"><span class="detail-label">目标</span><span class="detail-value">{{ detailSub.target_session || '默认' }}</span></div>
        <div class="detail-row"><span class="detail-label">间隔</span><span class="detail-value">{{ detailSub.interval || '默认' }} 分钟</span></div>
        <div class="detail-row"><span class="detail-label">标签</span><span class="detail-value">{{ detailSub.tags || '-' }}</span></div>
        <div class="detail-row"><span class="detail-label">创建时间</span><span class="detail-value">{{ formatDate(detailSub.created_at) }}</span></div>
        <div class="detail-row"><span class="detail-label">更新时间</span><span class="detail-value">{{ formatDate(detailSub.updated_at) }}</span></div>
      </div>
      <div class="panel-section">
        <h4>操作</h4>
        <div style="display:flex;gap:8px;flex-wrap:wrap;">
          <button class="btn btn-primary btn-small" @click="switchToEdit(detailSub)">编辑</button>
          <button class="btn btn-secondary btn-small" :class="{ 'is-loading': isPending('feed:refresh:' + detailSub.feed_id) }" :disabled="isPending('feed:refresh:' + detailSub.feed_id)" @click="handleRefreshDetail(detailSub.feed_id)">刷新 Feed</button>
          <button class="btn btn-secondary btn-small" :class="{ 'is-loading': isPending('sub:test:' + detailSub.id) }" :disabled="isPending('sub:test:' + detailSub.id)" @click="handleTestDetail(detailSub.id)">测试推送</button>
          <button class="btn btn-secondary btn-small" :class="{ 'is-loading': isPending('detail:items:' + detailSub.feed_id) }" :disabled="isPending('detail:items:' + detailSub.feed_id)" @click="loadDetailItems(detailSub.feed_id)">查看条目</button>
          <button class="btn btn-danger btn-small" :class="{ 'is-loading': isPending('sub:delete:' + detailSub.id) }" :disabled="isPending('sub:delete:' + detailSub.id)" @click="handleDeleteSub()">删除</button>
        </div>
      </div>
      <div class="panel-section" v-if="detailItems.length > 0">
        <h4>最新条目</h4>
        <div v-for="item in detailItems" :key="item.link" class="entry-item">
          <div class="entry-title">{{ item.title }}</div>
          <div class="entry-meta">{{ item.author ? item.author + ' · ' : '' }}{{ formatDate(item.published_at) }}</div>
          <div class="entry-summary" v-if="item.summary">{{ item.summary }}</div>
        </div>
      </div>
    </div>

    <div v-else-if="panelMode === 'history-detail' && historyDetail" class="form">
      <div class="panel-section">
        <h4>基础信息</h4>
        <div class="detail-row"><span class="detail-label">状态</span><span class="detail-value"><span class="status-badge" :class="historyDetail.status">{{ historyDetail.status }}</span></span></div>
        <div class="detail-row"><span class="detail-label">来源</span><span class="detail-value">{{ historyDetail.source_type || 'feed' }} / {{ historyDetail.source_key || '-' }}</span></div>
        <div class="detail-row"><span class="detail-label">用户</span><span class="detail-value">{{ historyDetail.user_id }}</span></div>
        <div class="detail-row"><span class="detail-label">Feed</span><span class="detail-value">{{ historyDetail.feed_title || '-' }}</span></div>
        <div class="detail-row"><span class="detail-label">条目</span><span class="detail-value">{{ historyDetail.entry_title || '-' }}</span></div>
        <div class="detail-row"><span class="detail-label">链接</span><span class="detail-value cell-wrap">{{ historyDetail.entry_link || '-' }}</span></div>
        <div class="detail-row"><span class="detail-label">GUID</span><span class="detail-value cell-wrap">{{ historyDetail.entry_guid || '-' }}</span></div>
        <div class="detail-row"><span class="detail-label">目标</span><span class="detail-value">{{ historyDetail.target_session || '-' }}</span></div>
        <div class="detail-row"><span class="detail-label">平台</span><span class="detail-value">{{ historyDetail.platform_name || '-' }}</span></div>
        <div class="detail-row"><span class="detail-label">重试</span><span class="detail-value">{{ historyDetail.retry_count }}/{{ historyDetail.max_retries }}</span></div>
        <div class="detail-row"><span class="detail-label">创建时间</span><span class="detail-value">{{ formatDate(historyDetail.created_at) }}</span></div>
        <div class="detail-row"><span class="detail-label">完成时间</span><span class="detail-value">{{ formatDate(historyDetail.completed_at) }}</span></div>
      </div>
      <div class="panel-section">
        <h4>正文与来源</h4>
        <div class="detail-row"><span class="detail-label">正文</span><span class="detail-value cell-wrap">{{ historyDetail.content || '-' }}</span></div>
        <div class="detail-row"><span class="detail-label">原始 XML</span><span class="detail-value cell-wrap">{{ historyDetail.raw_xml || '-' }}</span></div>
        <div class="detail-row"><span class="detail-label">媒体</span><span class="detail-value cell-wrap">{{ prettyJson(historyDetail.media_urls) }}</span></div>
        <div class="detail-row"><span class="detail-label">错误</span><span class="detail-value error-block">{{ historyDetail.fail_reason || '-' }}</span></div>
      </div>
      <div class="panel-section">
        <h4>调用链</h4>
        <div v-if="historyTraceSteps().length === 0" class="empty-state"><p>暂无 handler 记录</p></div>
        <div v-else>
          <div v-for="(step, index) in historyTraceSteps()" :key="step.id || step.name || index" class="entry-item">
            <div class="entry-title">{{ step.name || step.id || '未知 Handler' }}</div>
            <div class="entry-meta">状态: {{ historyTraceStatus(step) }} · {{ step.type || 'builtin' }}</div>
            <div class="entry-summary" v-if="historyTraceReason(step)">{{ historyTraceReason(step) }}</div>
            <div class="entry-summary" v-if="step.config">{{ prettyJson(step.config) }}</div>
          </div>
          <div class="trace-raw-block">
            <div class="trace-raw-title">原始 Trace JSON</div>
            <pre class="trace-raw-json">{{ prettyJson(historyDetail.handler_trace) }}</pre>
          </div>
        </div>
      </div>
    </div>

    <div v-else-if="panelMode === 'history-settings'" class="form">
      <div class="panel-section">
        <h4>自动清理</h4>
        <div class="setting-row">
          <span class="setting-label">保留周期</span>
          <select class="select-input" v-model.number="historyRetentionDays">
            <option :value="1">1 天</option>
            <option :value="7">1 周</option>
            <option :value="30">30 天</option>
          </select>
        </div>
      </div>
      <div class="panel-section">
        <h4>历史操作</h4>
        <div style="display:flex;gap:8px;flex-wrap:wrap;">
          <button class="btn btn-primary btn-small" :class="{ 'is-loading': isPending('push-history:settings-save') }" :disabled="isPending('push-history:settings-save')" @click="savePushHistorySettings()">保存设置</button>
          <button class="btn btn-secondary btn-small" :class="{ 'is-loading': isPending('push-history:cleanup') }" :disabled="isPending('push-history:cleanup')" @click="cleanupPushHistory()">立即清理旧记录</button>
          <button class="btn btn-danger btn-small" :class="{ 'is-loading': isPending('push-history:clear') }" :disabled="isPending('push-history:clear')" @click="clearPushHistory()">清空历史</button>
        </div>
      </div>
    </div>

    <div v-else-if="panelMode === 'export-preview' && exportPreview" class="form">
      <div class="panel-section">
        <h4>文件信息</h4>
        <div class="detail-row"><span class="detail-label">文件名</span><span class="detail-value cell-wrap">{{ exportPreview.name }}</span></div>
        <div class="detail-row"><span class="detail-label">大小</span><span class="detail-value">{{ formatBytes(exportPreview.size) }}</span></div>
      </div>
      <div class="panel-section">
        <div class="section-header" style="padding:0 0 12px 0;border-bottom:1px solid #f1f5f9;margin-bottom:8px;">
          <h4 style="margin:0;">TOML 内容</h4>
        </div>
        <div class="trace-raw-block">
          <pre class="trace-raw-json">{{ exportPreview.content || '' }}</pre>
        </div>
      </div>
    </div>
  </section>

`;
