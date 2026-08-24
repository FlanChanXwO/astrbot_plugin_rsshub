export const templatesActionsTemplate = String.raw`
      <div v-if="activeTab === 'templates'" class="resource-toolbar">
        <label class="sr-only" for="template-search">搜索卡片模板</label>
        <input id="template-search" class="search-input" type="search" v-model="templateFilter" placeholder="搜索名称、作者或模板 ID" @keyup.enter="loadTemplates()" />
        <button class="btn btn-secondary" type="button" :class="{ 'is-loading': isPending('templates:refresh') }" :disabled="isPending('templates:refresh')" @click="runPending('templates:refresh', () => loadTemplates())">刷新</button>
      </div>
`;

export const templatesPageTemplate = String.raw`
      <section v-if="activeTab === 'templates'" class="resource-page">
        <div class="section-header resource-page-header">
          <div>
            <h2>卡片模板</h2>
            <p class="section-subtitle">安装并审阅模板包。模板脚本和网络访问采用高信任模型，请只安装可信来源。</p>
          </div>
          <span class="resource-count">共 {{ templatesTotal }} 个</span>
        </div>
        <section class="template-install-card" aria-labelledby="template-install-title">
          <div>
            <h3 id="template-install-title">从 HTTP(S) URL 安装</h3>
            <p class="field-help">HTTPS 直接安装；HTTP 会在提交前弹出明确的明文传输警告并要求确认。ZIP 包仍由后端校验 metadata.yaml、入口和路径安全。</p>
          </div>
          <div class="resource-toolbar template-install-toolbar">
            <label class="sr-only" for="template-install-url">模板包 URL</label>
            <input id="template-install-url" class="search-input" type="url" v-model="templateInstallUrl" placeholder="https://example.com/card-template.zip" @keyup.enter="installTemplateFromPage()" />
            <button class="btn btn-primary" type="button" :class="{ 'is-loading': isPending('templates:install') }" :disabled="isPending('templates:install')" @click="installTemplateFromPage()">安装模板</button>
          </div>
          <p v-if="templateInstallError" class="field-error" role="alert">{{ templateInstallError }}</p>
        </section>
        <div v-if="templatesLoading" class="resource-state" aria-live="polite"><span class="loading-spinner"></span><p>正在加载模板列表...</p></div>
        <div v-else-if="templatesLoadError" class="resource-state resource-state-error" role="alert"><p>{{ templatesLoadError }}</p><button class="btn btn-secondary btn-small" type="button" @click="loadTemplates()">重试</button></div>
        <div v-else-if="filteredTemplates().length === 0" class="resource-state"><p>{{ templateFilter ? '没有匹配的模板' : '暂无卡片模板' }}</p><p class="resource-state-help">安装内置或可信来源的模板包后，Subscription 与 Bundle 的严格候选会自动更新。</p></div>
        <div v-else class="resource-grid template-grid">
          <article v-for="template in filteredTemplates()" :key="template.id" class="resource-card template-card">
            <div class="resource-card-header"><div class="resource-card-title-wrap"><h3>{{ template.name }}</h3><span class="template-version">v{{ template.version }}</span></div><button class="btn btn-text btn-action danger" type="button" @click="deleteTemplateFromPage(template)" :disabled="isPending('templates:delete:' + template.id)">删除</button></div>
            <p class="template-description">{{ template.description || '暂无描述' }}</p>
            <dl class="resource-card-meta">
              <div><dt>ID</dt><dd class="cell-mono cell-wrap">{{ template.id }}</dd></div>
              <div><dt>作者</dt><dd>{{ template.author }}</dd></div>
              <div><dt>目标</dt><dd>{{ (template.targets || []).join('、') }}</dd></div>
              <div><dt>来源匹配</dt><dd>{{ (template.feed_patterns || []).length ? template.feed_patterns.join('、') : '任意来源' }}</dd></div>
            </dl>
            <a v-if="templateRepositoryUrl(template)" class="template-repository" :href="templateRepositoryUrl(template)" target="_blank" rel="noopener noreferrer">查看仓库</a>
            <span v-else-if="template.repository" class="field-help">仓库链接不是受支持的 HTTP(S) 地址</span>
          </article>
        </div>
      </section>
`;
