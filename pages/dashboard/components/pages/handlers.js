export const handlersPageTemplate = String.raw`
      <section class="table-section" v-if="activeTab === 'handlers'">
        <div class="section-header">
          <h2>处理器</h2>
          <div class="section-header-actions">
            <button class="btn btn-secondary btn-small" :class="{ 'is-loading': handlersLoading }" :disabled="handlersLoading" @click="refreshHandlers()">刷新</button>
            <button class="btn btn-primary btn-small" disabled title="外部处理器安装暂未开放">安装</button>
          </div>
        </div>
        <div class="table-scroll-area">
          <div v-if="handlersLoading" class="empty-state"><p>加载中...</p></div>
          <div v-else-if="handlersRegistry.length === 0" class="empty-state"><p>暂无处理器数据</p></div>
          <div v-else class="handler-grid">
            <article
              v-for="handler in handlersRegistry"
              :key="handler.name"
              class="handler-card"
              :class="{ expanded: isHandlerExpanded(handler.name) }"
              role="button"
              tabindex="0"
              :aria-expanded="isHandlerExpanded(handler.name) ? 'true' : 'false'"
              @click="toggleHandlerCard(handler.name)"
              @keydown.enter.prevent="toggleHandlerCard(handler.name)"
              @keydown.space.prevent="toggleHandlerCard(handler.name)"
            >
              <div class="handler-card-head">
                <div class="handler-card-main">
                  <div class="handler-title-row">
                    <div class="handler-title">{{ handler.title }}</div>
                    <span class="handler-expand-indicator">{{ isHandlerExpanded(handler.name) ? '收起' : '展开' }}</span>
                  </div>
                  <div class="handler-meta">{{ handler.name }} · {{ handlerTypeLabel(handler.type) }}</div>
                  <div class="handler-card-tags">
                    <span class="handler-tag">{{ handlerStatusLabel(handler) }}</span>
                    <span class="handler-tag">{{ handlerFieldCountText(handler) }}</span>
                  </div>
                </div>
              </div>
              <div class="handler-desc">{{ handler.description || '暂无说明' }}</div>
              <div class="handler-fields" v-if="isHandlerExpanded(handler.name) && handler.fields.length > 0">
                <div v-for="field in handler.fields" :key="field.key" class="handler-field">
                  <div class="handler-field-label">
                    <span>{{ field.label || field.key }}</span>
                    <span class="handler-field-type">{{ field.type }}</span>
                  </div>
                  <div class="handler-field-desc">{{ field.description || '无说明' }}</div>
                  <div class="handler-field-value">
                    <span class="handler-field-default">默认: {{ handlerDefaultValueText(field.default) }}</span>
                    <span v-if="field.options && field.options.length" class="handler-field-options">可选: {{ field.options.map((item) => item.value || item.label).join(' / ') }}</span>
                  </div>
                </div>
              </div>
              <div class="handler-fields empty" v-else-if="isHandlerExpanded(handler.name)">该处理器无额外配置项</div>
            </article>
          </div>
        </div>
      </section>

`;
