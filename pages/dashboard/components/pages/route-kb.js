export const routeKbPageTemplate = String.raw`
      <section v-if="activeTab === 'route-kb'" class="settings-shell narrow-page">
        <div class="settings-scroll-area">
          <div class="settings-form">
            <div class="panel-section">
              <div class="section-header" style="padding:0 0 12px 0;border-bottom:1px solid #f1f5f9;margin-bottom:8px;">
                <div class="route-kb-title"><h2>RSSHub Routes 知识库</h2></div>
                <div class="section-header-actions">
                  <button class="btn btn-secondary btn-small" :class="{ 'is-loading': routeKbLoading }" :disabled="routeKbLoading" @click="loadRouteKbStatus()">刷新</button>
                  <button class="btn btn-primary btn-small" :class="{ 'is-loading': isPending('route-kb:sync') }" :disabled="routeKbLoading || isRouteKbTaskRunning() || isPending('route-kb:sync')" @click="handleRouteKbSync()">
                    {{ isPending('route-kb:sync') ? '启动中...' : '同步' }}
                  </button>
                </div>
              </div>
              <div v-if="routeKbLoading" class="empty-state"><p>加载中...</p></div>
              <div v-else-if="!routeKbStatus" class="empty-state"><p>暂无知识库状态</p></div>
              <div v-else>
                <div class="setting-row"><span class="setting-label">知识库名称</span><span class="setting-value">{{ routeKbStatus.kb_name }}</span></div>
                <div class="setting-row"><span class="setting-label">KB ID</span><span class="setting-value">{{ routeKbStatus.kb_id || '未就绪' }}</span></div>
                <div class="setting-row"><span class="setting-label">已管理文件</span><span class="setting-value">{{ routeKbStatus.managed_files }}</span></div>
                <div class="setting-row"><span class="setting-label">KB 文档数</span><span class="setting-value">{{ routeKbStatus.kb_docs }}</span></div>
                <div class="setting-row"><span class="setting-label">来源版本</span><span class="setting-value">{{ routeKbStatus.source_version || '未知' }}</span></div>
                <div class="setting-row"><span class="setting-label">最后同步</span><span class="setting-value">{{ formatDate(routeKbStatus.last_sync_at) }}</span></div>
                <div class="setting-row" v-if="routeKbStatus.last_error"><span class="setting-label">最近错误</span><span class="setting-value error-block">{{ routeKbStatus.last_error }}</span></div>
              </div>
            </div>
            <div class="panel-section" v-if="routeKbTask && routeKbTask.status !== 'idle'">
              <div class="section-header" style="padding:0 0 12px 0;border-bottom:1px solid #f1f5f9;margin-bottom:8px;">
                <h2>同步任务</h2>
              </div>
              <div class="setting-row"><span class="setting-label">任务 ID</span><span class="setting-value">{{ routeKbTask.task_id }}</span></div>
              <div class="setting-row"><span class="setting-label">状态</span><span class="status-badge" :class="routeKbTask.status === 'completed' ? 'success' : (routeKbTask.status === 'failed' ? 'failed' : 'pending')">{{ routeKbTask.status }}</span></div>
              <div class="setting-row"><span class="setting-label">进度</span><span class="setting-value">{{ routeKbTask.processed }}/{{ routeKbTask.total }}</span></div>
              <div class="setting-row"><span class="setting-label">计划</span><span class="setting-value">新增 {{ routeKbTask.added }}，更新 {{ routeKbTask.updated }}，删除 {{ routeKbTask.deleted }}，跳过 {{ routeKbTask.skipped || 0 }}，未变更 {{ routeKbTask.unchanged }}</span></div>
              <div class="setting-row" v-if="routeKbTask.current_path"><span class="setting-label">当前文件</span><span class="setting-value">{{ routeKbTask.current_path }}</span></div>
              <div class="setting-row" v-if="routeKbTask.message"><span class="setting-label">消息</span><span class="setting-value">{{ routeKbTask.message }}</span></div>
              <div class="setting-row" v-if="routeKbTask.error"><span class="setting-label">错误</span><span class="setting-value error-block">{{ routeKbTask.error }}</span></div>
            </div>
          </div>
        </div>
      </section>

`;
