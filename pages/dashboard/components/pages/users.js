import { batchToolbarTemplate, compactFilterToolbarTemplate } from '../shared/filters.js';

export const usersActionsTemplate = [
  compactFilterToolbarTemplate({
    groupName: 'userFilters',
    visibleExpr: "activeTab === 'users'",
    pendingKey: 'users:refresh',
    loadAction: 'loadUsers()',
    clearAction: 'clearUserFilters',
    hasFilters: 'hasUserFilters',
    extraButtons: [
      `<button class="btn" :class="userEditMode ? 'btn-primary' : 'btn-secondary'" type="button" @click="toggleUserEditMode()">{{ userEditMode ? '完成编辑' : '批量操作' }}</button>`,
    ],
  }),
  batchToolbarTemplate({ visibleExpr: 'userEditMode && selectedUserIds.length > 0', countExpr: 'selectedUserIds.length', buttons: [
    `<button class="btn btn-danger btn-small" :class="{ 'is-loading': isPending('users:delete-batch') }" :disabled="isPending('users:delete-batch')" @click="deleteSelectedUsers()">批量删除</button>`,
  ] }),
].join('\n');

export const usersPageTemplate = String.raw`
      <section class="table-section" v-if="activeTab === 'users'">
        <div class="section-header">
          <h2>用户列表</h2>
          <span style="font-size:13px;color:#94a3b8;">共 {{ users.length }} 个</span>
        </div>
        <div class="table-scroll-area">
          <div v-if="usersLoading" class="empty-state"><p>加载中...</p></div>
          <div v-else-if="users.length === 0" class="empty-state"><p>暂无用户数据</p></div>
          <table class="sub-table users-table" v-else>
            <thead><tr><th v-if="userEditMode" class="col-chk"><input type="checkbox" :checked="areAllUsersSelected()" @click.stop @change="toggleAllUserSelection()" /></th><th class="col-user">用户 ID</th><th class="col-status">状态</th><th class="col-interval">订阅数</th><th class="col-actions">操作</th></tr></thead>
            <tbody>
              <tr v-for="u in users" :key="u.user_id" :class="{ selected: selectedUserIds.includes(u.user_id) }" @click="userEditMode ? toggleUserSelection(u.user_id) : selectUser(u.user_id)">
                <td v-if="userEditMode" class="col-chk"><input type="checkbox" :checked="selectedUserIds.includes(u.user_id)" @click.stop="toggleUserSelection(u.user_id)" /></td>
                <td class="col-user cell-mono" data-label="用户" :title="u.user_id">{{ u.user_id }}</td>
                <td class="col-status" data-label="状态"><span class="status-badge" :class="u.state >= 0 ? 'active' : 'inactive'">{{ formatUserState(u.state) }}</span></td>
                <td class="col-interval" data-label="订阅数">{{ userSubscriptionCountText(u) }}</td>
                <td class="col-actions" data-label="操作">
                  <div class="action-cell">
                    <button class="btn btn-text btn-action" :class="{ 'is-loading': isPending('user:panel-edit:' + u.user_id) }" :disabled="isPending('user:panel-edit:' + u.user_id)" @click.stop="openUserEditPanel(u)">编辑</button>
                    <button class="btn btn-text btn-action danger" :class="{ 'is-loading': isPending('user:delete:' + u.user_id) }" :disabled="isPending('user:delete:' + u.user_id)" @click.stop="handleDeleteUser(u.user_id)">删除</button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

`;
