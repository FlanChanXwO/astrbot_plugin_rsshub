export const overviewPageTemplate = String.raw`
      <section class="overview-page" v-if="activeTab === 'overview'">
        <div class="section-header">
          <h2>概览</h2>
          <div class="section-header-actions">
            <div class="segmented-control" role="group" aria-label="图表时间范围">
              <button class="segmented-button" :class="{ active: overviewRange === '24h' }" type="button" @click="setOverviewRange('24h')">24小时</button>
              <button class="segmented-button" :class="{ active: overviewRange === '7d' }" type="button" @click="setOverviewRange('7d')">1周</button>
              <button class="segmented-button" :class="{ active: overviewRange === '30d' }" type="button" @click="setOverviewRange('30d')">1个月</button>
            </div>
            <button class="btn btn-icon" type="button" :class="{ 'is-loading': isPending('overview:refresh') || overviewChartsLoading }" :disabled="isPending('overview:refresh') || overviewChartsLoading" @click="runPending('overview:refresh', () => loadOverview())" title="刷新" aria-label="刷新">⟳</button>
          </div>
        </div>
        <div class="overview-stats-grid">
          <div class="stat-card"><div class="stat-card-value">{{ stats.total_subscriptions }}</div><div class="stat-card-label">总订阅</div></div>
          <div class="stat-card"><div class="stat-card-value">{{ stats.active_subscriptions }}</div><div class="stat-card-label">启用中</div></div>
          <div class="stat-card"><div class="stat-card-value">{{ stats.total_feeds }}</div><div class="stat-card-label">Feed 源</div></div>
          <div class="stat-card"><div class="stat-card-value">{{ stats.unique_users }}</div><div class="stat-card-label">用户数</div></div>
        </div>
        <div class="overview-chart-grid">
          <section class="overview-chart-panel overview-chart-panel-wide">
            <div class="overview-chart-head">
              <h3>推送成功率</h3>
              <span class="overview-chart-meta">success / (success + failed + stopped + skipped)</span>
            </div>
            <div class="overview-chart-canvas">
              <canvas id="overview-push-success-chart"></canvas>
            </div>
          </section>
          <section class="overview-chart-panel">
            <div class="overview-chart-head">
              <h3>Feed 新鲜度</h3>
              <span class="overview-chart-meta">按订阅间隔分档</span>
            </div>
            <div class="overview-chart-canvas overview-chart-canvas-small">
              <canvas id="overview-feed-health-chart"></canvas>
            </div>
            <div class="overview-health-summary">
              <div class="overview-health-item" v-for="bucket in feedHealthBuckets()" :key="bucket.status">
                <span class="legend-swatch" :style="{ background: bucket.color }"></span>
                <span>{{ bucket.label }}</span>
                <strong>{{ bucket.count }}</strong>
              </div>
            </div>
          </section>
          <section class="overview-chart-panel overview-share-panel">
            <div class="overview-chart-head">
              <h3>Feed 订阅占比</h3>
              <span class="overview-chart-meta">Top 8 + 其他</span>
            </div>
            <div class="overview-doughnut-layout">
              <div class="overview-share-legend">
                <div class="legend-list">
                  <div class="legend-item" v-for="(item, index) in feedShareLegendItems()" :key="item.feed_id || item.title">
                    <span class="legend-swatch" :style="{ background: feedShareColor(index) }"></span>
                    <span class="legend-label" :title="item.link || item.title">{{ item.title }}</span>
                    <span class="legend-value">{{ item.count }} / {{ feedSharePercent(item) }}</span>
                  </div>
                </div>
                <div class="legend-pager" v-if="feedShareLegendTotalPages() > 1">
                  <button class="legend-page-btn" type="button" :disabled="feedShareLegendPage <= 1" @click="setFeedShareLegendPage(feedShareLegendPage - 1)" title="上一页" aria-label="上一页">◀</button>
                  <span>{{ feedShareLegendPage }}/{{ feedShareLegendTotalPages() }}</span>
                  <button class="legend-page-btn" type="button" :disabled="feedShareLegendPage >= feedShareLegendTotalPages()" @click="setFeedShareLegendPage(feedShareLegendPage + 1)" title="下一页" aria-label="下一页">▶</button>
                </div>
              </div>
              <div class="overview-chart-canvas overview-doughnut-canvas">
                <canvas id="overview-feed-share-chart"></canvas>
              </div>
            </div>
          </section>
        </div>
      </section>

`;
