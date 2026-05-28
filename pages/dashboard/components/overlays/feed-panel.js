export const feedPanelTemplate = String.raw`
  <div class="panel-overlay" :class="{ visible: feedEditPanelVisible }" @click="closeFeedEditPanel()"></div>
  <section class="edit-panel" :class="{ 'panel-visible': feedEditPanelVisible }">
    <div class="panel-header">
      <h3>编辑 Feed</h3>
      <div class="panel-actions"><button class="btn btn-icon" @click="closeFeedEditPanel()">×</button></div>
    </div>
    <form class="form" @submit.prevent="handleSaveFeedEdit()">
      <div class="panel-section">
        <h4>基本信息</h4>
        <div class="detail-row"><span class="detail-label">Feed ID</span><span class="detail-value">{{ feedEditForm.id }}</span></div>
        <div class="form-group">
          <label>标题</label>
          <div class="input-wrapper"><input type="text" v-model="feedEditForm.title" placeholder="Feed 标题" /></div>
        </div>
        <div class="form-group">
          <label>链接</label>
          <div class="input-wrapper"><input type="text" v-model="feedEditForm.link" placeholder="https://..." /></div>
        </div>
        <div class="setting-row"><span class="setting-label">状态</span><select class="select-input" v-model.number="feedEditForm.state"><option :value="1">启用</option><option :value="0">停用</option></select></div>
      </div>
      <div class="form-actions">
        <button type="button" class="btn btn-danger" :class="{ 'is-loading': isPending('feed:delete:' + feedEditForm.id) }" :disabled="isPending('feed:delete:' + feedEditForm.id)" @click="handleDeleteFeed(feedEditForm.id)">删除 Feed</button>
        <div class="center-actions">
          <button type="button" class="btn btn-text" @click="closeFeedEditPanel()">取消</button>
          <button type="submit" class="btn btn-primary" :class="{ 'is-loading': isPending('feed:save:' + feedEditForm.id) }" :disabled="isPending('feed:save:' + feedEditForm.id)">{{ isPending('feed:save:' + feedEditForm.id) ? '保存中...' : '保存修改' }}</button>
        </div>
      </div>
    </form>
  </section>

`;
