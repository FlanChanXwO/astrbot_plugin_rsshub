export const settingsPageTemplate = String.raw`
      <section v-if="activeTab === 'settings'" class="settings-shell narrow-page">
        <div v-if="pluginSettingsLoading" class="empty-state"><p>加载中...</p></div>
        <div v-else class="settings-scroll-area">
          <div class="settings-form">
            <div class="panel-section">
              <h4>插件默认订阅配置</h4>
              <div class="setting-row"><span class="setting-label">默认监控间隔（分钟）</span><div class="input-wrapper" style="max-width:120px;"><input type="number" v-model.number="subscriptionDefaults.interval" min="1" max="1440" /></div></div>
              <div class="setting-row"><span class="setting-label">默认通知</span><label class="toggle-switch"><input type="checkbox" v-model="subscriptionDefaults.notify" /><span class="toggle-slider"></span></label></div>
              <div class="setting-row"><span class="setting-label">默认发送模式</span><select class="select-input" v-model="subscriptionDefaults.send_mode"><option value="仅链接">仅链接</option><option value="自动">自动</option><option value="直接发送">直接发送</option></select></div>
              <div class="setting-row"><span class="setting-label">内容长度限制</span><div class="input-wrapper" style="max-width:120px;"><input type="number" v-model.number="subscriptionDefaults.length_limit" min="0" /></div></div>
              <div class="setting-row"><span class="setting-label">默认显示作者</span><select class="select-input" v-model="subscriptionDefaults.display_author"><option value="禁用">禁用</option><option value="自动">自动</option><option value="强制">强制</option></select></div>
              <div class="setting-row"><span class="setting-label">默认显示来源</span><select class="select-input" v-model="subscriptionDefaults.display_via"><option value="完全禁用">完全禁用</option><option value="仅链接">仅链接</option><option value="自动">自动</option><option value="强制">强制</option></select></div>
              <div class="setting-row"><span class="setting-label">默认显示标题</span><select class="select-input" v-model="subscriptionDefaults.display_title"><option value="禁用">禁用</option><option value="自动">自动</option><option value="强制">强制</option></select></div>
              <div class="setting-row"><span class="setting-label">默认显示标签</span><label class="toggle-switch"><input type="checkbox" v-model="subscriptionDefaults.display_entry_tags" /><span class="toggle-slider"></span></label></div>
              <div class="setting-row"><span class="setting-label">默认排版策略</span><select class="select-input" v-model="subscriptionDefaults.style"><option value="auto">自动</option><option value="rssrt">RSSRT</option><option value="original">原始顺序</option></select></div>
              <div class="setting-row"><span class="setting-label">默认显示媒体</span><label class="toggle-switch"><input type="checkbox" v-model="subscriptionDefaults.display_media" /><span class="toggle-slider"></span></label></div>
            </div>
            <div class="form-actions">
              <button class="btn btn-primary" :class="{ 'is-loading': isPending('plugin-settings:save') }" :disabled="isPending('plugin-settings:save')" @click="savePluginSettings()">保存插件设置</button>
            </div>
          </div>
        </div>
      </section>

`;
