import {
  getUserDetails,
  updateUser,
  deleteUser,
  deleteUsers
} from '../../js/api.js';
import {
  normalizeUserState,
  handlersToEditorState,
  buildHandlersFromEditorState,
  createInheritedNumberValue,
  inheritedNumberToPayload
} from '../helpers.js';

export const usersModule = {
  async loadUsers() {
    this.usersLoading = true;
    try {
      const result = await getUserDetails(this.userFilters);
      this.users = result.items || [];
      this.selectedUserIds = this.selectedUserIds.filter((id) =>
        this.users.some((item) => item.user_id === id)
      );
    } catch (err) {
      this.showToast(`加载用户失败: ${err.message}`, 'error');
    } finally {
      this.usersLoading = false;
    }
  },

  toggleUserEditMode() {
    this.userEditMode = !this.userEditMode;
    if (!this.userEditMode) this.selectedUserIds = [];
  },

  toggleUserSelection(userId) {
    const index = this.selectedUserIds.indexOf(userId);
    if (index >= 0) {
      this.selectedUserIds.splice(index, 1);
    } else {
      this.selectedUserIds.push(userId);
    }
  },

  areAllUsersSelected() {
    return this.users.length > 0 && this.selectedUserIds.length === this.users.length;
  },

  toggleAllUserSelection() {
    if (this.areAllUsersSelected()) {
      this.selectedUserIds = [];
      return;
    }
    this.selectedUserIds = this.users.map((item) => item.user_id).filter(Boolean);
  },

  async deleteSelectedUsers() {
    if (this.selectedUserIds.length === 0) return;
    const count = this.selectedUserIds.length;
    const confirm = await this.showConfirm(
      `确定删除选中的 ${count} 个用户？此操作会同时删除这些用户的所有订阅，不可恢复。推送历史默认保留。`,
      '批量删除用户',
      '删除',
      'btn-danger',
      { optionLabel: '同时清理对应推送历史' }
    );
    if (!confirm.ok) return;
    await this.runPending('users:delete-batch', async () => {
      const result = await deleteUsers(this.selectedUserIds, confirm.optionChecked);
      this.selectedUserIds = [];
      this.showToast(result.message || `已删除 ${count} 个用户`);
      await this.loadUsers();
      await this.loadData();
      await this.loadFeeds();
      if (confirm.optionChecked) await this.loadPushHistory();
    }).catch((err) => {
      this.showToast(`批量删除用户失败: ${err.message}`, 'error');
    });
  },

  openUserEditPanel(user) {
    this.userEditForm = {
      user_id: user.user_id,
      state: normalizeUserState(user.state ?? 1),
      interval: user.interval ?? -100,
      interval_control: createInheritedNumberValue(user.interval ?? -100, 10),
      notify: user.notify ?? -100,
      send_mode: user.send_mode ?? -100,
      length_limit: user.length_limit ?? -100,
      length_limit_control: createInheritedNumberValue(user.length_limit ?? -100, 0),
      display_author: user.display_author ?? -100,
      display_via: user.display_via ?? -100,
      display_title: user.display_title ?? -100,
      display_entry_tags: user.display_entry_tags ?? -100,
      style: user.style ?? -100,
      display_media: user.display_media ?? -100,
      ...handlersToEditorState(user.handlers),
    };
    this.userEditPanelVisible = true;
  },

  closeUserEditPanel() {
    this.userEditPanelVisible = false;
  },

  async handleSaveUserEdit() {
    await this.runPending(`user:save:${this.userEditForm.user_id}`, async () => {
      const settings = {
        state: normalizeUserState(this.userEditForm.state),
        interval: inheritedNumberToPayload(this.userEditForm.interval_control),
        notify: this.userEditForm.notify,
        send_mode: this.userEditForm.send_mode,
        length_limit: inheritedNumberToPayload(this.userEditForm.length_limit_control),
        display_author: this.userEditForm.display_author,
        display_via: this.userEditForm.display_via,
        display_title: this.userEditForm.display_title,
        display_entry_tags: this.userEditForm.display_entry_tags,
        style: this.userEditForm.style,
        display_media: this.userEditForm.display_media,
        handlers: buildHandlersFromEditorState(this.userEditForm),
      };
      await updateUser(this.userEditForm.user_id, settings);
      this.showToast('用户配置已更新');
      this.closeUserEditPanel();
      await this.loadUsers();
    }).catch((err) => {
      this.showToast(`更新失败: ${err.message}`, 'error');
    });
  },

  async handleDeleteUser(userId) {
    const confirm = await this.showConfirm(
      `确定删除用户 ${userId}？此操作将同时删除该用户的所有订阅，不可恢复。推送历史默认保留。`,
      '删除用户',
      '删除',
      'btn-danger',
      { optionLabel: '同时清理对应推送历史' }
    );
    if (!confirm.ok) return;
    await this.runPending(`user:delete:${userId}`, async () => {
      const result = await deleteUser(userId, confirm.optionChecked);
      this.showToast(result.message || '用户已删除');
      await this.loadUsers();
      await this.loadData();
      await this.loadFeeds();
      if (confirm.optionChecked) await this.loadPushHistory();
    }).catch((err) => {
      this.showToast(`删除失败: ${err.message}`, 'error');
    });
  },

  userSubscriptionCountText(user) {
    const total = Number(user?.subscription_count ?? 0) || 0;
    const active = Number(user?.active_subscription_count ?? total) || 0;
    return active !== total ? `${active} / ${total}` : String(total);
  }
};
