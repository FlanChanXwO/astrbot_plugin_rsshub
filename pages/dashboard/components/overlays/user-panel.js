export const userPanelTemplate = String.raw`
  <div class="panel-overlay" :class="{ visible: userEditPanelVisible }" @click="closeUserEditPanel()"></div>
  <section class="edit-panel" :class="{ 'panel-visible': userEditPanelVisible }">
    <div class="panel-header">
      <h3>编辑用户配置</h3>
      <div class="panel-actions"><button class="btn btn-icon" @click="closeUserEditPanel()">×</button></div>
    </div>
    <form class="form" @submit.prevent="handleSaveUserEdit()">
      <div class="panel-section">
        <h4>基本信息</h4>
        <div class="detail-row"><span class="detail-label">用户 ID</span><span class="detail-value">{{ userEditForm.user_id }}</span></div>
        <div class="setting-row"><span class="setting-label">用户状态</span><select class="select-input" v-model.number="userEditForm.state"><option :value="-1">已封禁</option><option :value="1">用户</option></select></div>
        <div class="form-group">
          <label>内容处理链</label>
          <div class="handler-editor">
            <div class="handler-json">
              <textarea v-model="userEditForm.handlers_json" rows="10"></textarea>
              <button type="button" class="btn btn-secondary btn-small" @click="applyHandlersJson(userEditForm)">应用 JSON</button>
            </div>
          </div>
        </div>
      </div>
      <div class="panel-section">
        <h4>推送设置</h4>
        <div class="setting-row"><span class="setting-label">推送间隔（分钟）</span><div class="inherit-control"><select class="select-input" v-model="userEditForm.interval_control.mode"><option value="inherit">继承</option><option value="custom">自定义</option></select><div v-if="userEditForm.interval_control.mode === 'custom'" class="input-wrapper"><input type="number" v-model.number="userEditForm.interval_control.value" min="1" max="1440" /></div></div></div>
        <div class="setting-row"><span class="setting-label">通知</span><select class="select-input" v-model.number="userEditForm.notify"><option :value="-100">继承</option><option :value="0">禁用</option><option :value="1">启用</option></select></div>
        <div class="setting-row"><span class="setting-label">发送模式</span><select class="select-input" v-model.number="userEditForm.send_mode"><option :value="-100">继承</option><option :value="-1">仅链接</option><option :value="0">自动</option><option :value="1">直接发送</option></select></div>
        <div class="setting-row"><span class="setting-label">内容长度限制</span><div class="inherit-control"><select class="select-input" v-model="userEditForm.length_limit_control.mode"><option value="inherit">继承</option><option value="custom">自定义</option></select><div v-if="userEditForm.length_limit_control.mode === 'custom'" class="input-wrapper"><input type="number" v-model.number="userEditForm.length_limit_control.value" min="0" max="10000" /></div></div></div>
      </div>
      <div class="panel-section">
        <h4>显示选项</h4>
        <div class="setting-row"><span class="setting-label">显示作者</span><select class="select-input" v-model.number="userEditForm.display_author"><option :value="-100">继承</option><option :value="-1">禁用</option><option :value="0">自动</option><option :value="1">强制</option></select></div>
        <div class="setting-row"><span class="setting-label">显示来源</span><select class="select-input" v-model.number="userEditForm.display_via"><option :value="-100">继承</option><option :value="-2">完全禁用</option><option :value="-1">仅链接</option><option :value="0">自动</option><option :value="1">强制</option></select></div>
        <div class="setting-row"><span class="setting-label">显示标题</span><select class="select-input" v-model.number="userEditForm.display_title"><option :value="-100">继承</option><option :value="-1">禁用</option><option :value="0">自动</option><option :value="1">强制</option></select></div>
        <div class="setting-row"><span class="setting-label">显示标签</span><select class="select-input" v-model.number="userEditForm.display_entry_tags"><option :value="-100">继承</option><option :value="-1">禁用</option><option :value="0">启用</option></select></div>
        <div class="setting-row"><span class="setting-label">排版策略</span><select class="select-input" v-model.number="userEditForm.style"><option :value="-100">继承</option><option :value="0">自动</option><option :value="1">RSSRT</option><option :value="2">原始顺序</option></select></div>
        <div class="setting-row"><span class="setting-label">显示媒体</span><select class="select-input" v-model.number="userEditForm.display_media"><option :value="-100">继承</option><option :value="-1">禁用</option><option :value="0">启用</option></select></div>
      </div>
      <div class="form-actions">
        <div></div>
        <div class="center-actions">
          <button type="button" class="btn btn-text" @click="closeUserEditPanel()">取消</button>
          <button type="submit" class="btn btn-primary" :class="{ 'is-loading': isPending('user:save:' + userEditForm.user_id) }" :disabled="isPending('user:save:' + userEditForm.user_id)">{{ isPending('user:save:' + userEditForm.user_id) ? '保存中...' : '保存修改' }}</button>
        </div>
      </div>
    </form>
  </section>

`;
