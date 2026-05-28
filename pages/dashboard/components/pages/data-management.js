export const dataManagementPageTemplate = String.raw`
      <section v-if="activeTab === 'data-management'" class="settings-shell narrow-page">
        <div v-if="dataManagementLoading" class="empty-state"><p>加载中...</p></div>
        <div v-else class="settings-scroll-area">
          <div class="settings-form">
            <div class="panel-section">
              <div class="section-header" style="padding:0 0 12px 0;border-bottom:1px solid #f1f5f9;margin-bottom:8px;">
                <h2>数据管理</h2>
                <div class="section-header-actions">
                  <button class="btn btn-secondary btn-small" :class="{ 'is-loading': isPending('data-management:refresh') }" :disabled="isPending('data-management:refresh')" @click="refreshDataManagement()">刷新</button>
                  <button class="btn btn-secondary btn-small" :class="{ 'is-loading': isPending('data-management:cache-clear') }" :disabled="isPending('data-management:cache-clear')" @click="handleClearCache()">清理缓存</button>
                  <button class="btn btn-danger btn-small" :class="{ 'is-loading': isPending('data-management:exports-clear') }" :disabled="isPending('data-management:exports-clear')" @click="handleClearExports()">清空导出</button>
                </div>
              </div>
              <div class="data-overview-grid">
                <div class="data-summary-card">
                  <div class="data-summary-title">缓存</div>
                  <div class="data-summary-value">{{ formatBytes(dataManagementOverview.cache.total_bytes) }}</div>
                  <div class="data-summary-meta">{{ dataManagementOverview.cache.file_count }} 个文件</div>
                </div>
                <div class="data-summary-card">
                  <div class="data-summary-title">导出</div>
                  <div class="data-summary-value">{{ formatBytes(dataManagementOverview.exports.total_bytes) }}</div>
                  <div class="data-summary-meta">{{ dataManagementOverview.exports.file_count }} 个文件</div>
                </div>
                <div class="data-summary-card">
                  <div class="data-summary-title">合计</div>
                  <div class="data-summary-value">{{ formatBytes(dataManagementOverview.totals.combined_bytes) }}</div>
                  <div class="data-summary-meta">缓存 + 导出</div>
                </div>
              </div>
              <div class="data-charts">
                <div class="data-chart-panel">
                  <h4>缓存占比</h4>
                  <div class="pie-chart-wrap">
                    <svg viewBox="0 0 36 36" class="pie-chart">
                      <circle class="pie-track" cx="18" cy="18" r="15.9155"></circle>
                      <circle
                        v-for="segment in cacheSegments()"
                        :key="segment.key"
                        class="pie-segment"
                        cx="18"
                        cy="18"
                        r="15.9155"
                        :stroke="segment.color"
                        :stroke-dasharray="segment.dashArray"
                        :stroke-dashoffset="segment.dashOffset"
                      ></circle>
                    </svg>
                  </div>
                  <div class="legend-list">
                    <div class="legend-item" v-for="segment in cacheSegments()" :key="segment.key">
                      <span class="legend-swatch" :style="{ background: segment.color }"></span>
                      <span class="legend-label">{{ segment.label }}</span>
                      <span class="legend-value">{{ formatBytes(segment.bytes) }}</span>
                    </div>
                  </div>
                </div>
                <div class="data-chart-panel">
                  <h4>导出占比</h4>
                  <div class="pie-chart-wrap">
                    <svg viewBox="0 0 36 36" class="pie-chart">
                      <circle class="pie-track" cx="18" cy="18" r="15.9155"></circle>
                      <circle
                        v-for="segment in exportSegments()"
                        :key="segment.key"
                        class="pie-segment"
                        cx="18"
                        cy="18"
                        r="15.9155"
                        :stroke="segment.color"
                        :stroke-dasharray="segment.dashArray"
                        :stroke-dashoffset="segment.dashOffset"
                      ></circle>
                    </svg>
                  </div>
                  <div class="legend-list">
                    <div class="legend-item" v-for="segment in exportSegments()" :key="segment.key">
                      <span class="legend-swatch" :style="{ background: segment.color }"></span>
                      <span class="legend-label">{{ segment.label }}</span>
                      <span class="legend-value">{{ formatBytes(segment.bytes) }}</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
            <div class="panel-section">
              <div class="section-header" style="padding:0 0 12px 0;border-bottom:1px solid #f1f5f9;margin-bottom:8px;">
                <h2>导出文件</h2>
                <span style="font-size:13px;color:#94a3b8;">{{ exportFiles.length }} 个</span>
              </div>
              <div v-if="exportFiles.length === 0" class="empty-state"><p>暂无导出文件</p></div>
              <table class="sub-table exports-table" v-else>
                <thead><tr><th class="col-feed">文件名</th><th class="col-interval">大小</th><th class="col-session">更新时间</th><th class="col-actions">操作</th></tr></thead>
                <tbody>
                  <tr v-for="file in exportFiles" :key="file.name">
                    <td class="col-feed cell-mono" data-label="文件名" :title="file.name">{{ file.name }}</td>
                    <td class="col-interval" data-label="大小">{{ formatBytes(file.size_bytes) }}</td>
                    <td class="col-session cell-mono" data-label="更新时间">{{ formatDate(file.modified_at) }}</td>
                    <td class="col-actions" data-label="操作">
                      <div class="action-cell">
                        <button class="btn btn-text btn-action" :class="{ 'is-loading': isPending('data-management:export-preview:' + file.name) }" :disabled="isPending('data-management:export-preview:' + file.name)" @click="openExportPreview(file.name)">预览</button>
                        <button class="btn btn-text btn-action danger" :class="{ 'is-loading': isPending('data-management:export-delete:' + file.name) }" :disabled="isPending('data-management:export-delete:' + file.name)" @click="handleDeleteExportFile(file.name)">删除</button>
                      </div>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </section>
`;
