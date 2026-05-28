import { subscriptionsActionsTemplate, subscriptionsPageTemplate } from './pages/subscriptions.js';
import { usersActionsTemplate, usersPageTemplate } from './pages/users.js';
import { feedsActionsTemplate, feedsPageTemplate } from './pages/feeds.js';
import { pushHistoryActionsTemplate, pushHistoryPageTemplate } from './pages/push-history.js';
import { handlersPageTemplate } from './pages/handlers.js';
import { routeKbPageTemplate } from './pages/route-kb.js';
import { settingsPageTemplate } from './pages/settings.js';
import { dataManagementPageTemplate } from './pages/data-management.js';
import { mainPanelTemplate } from './overlays/main-panel.js';
import { userPanelTemplate } from './overlays/user-panel.js';
import { feedPanelTemplate } from './overlays/feed-panel.js';
import { dialogsTemplate } from './overlays/dialogs.js';

const statsAndTabsTemplate = "    <div class=\"stats-row\">\n      <div class=\"stat-card\"><div class=\"stat-card-value\">{{ stats.total_subscriptions }}</div><div class=\"stat-card-label\">总订阅</div></div>\n      <div class=\"stat-card\"><div class=\"stat-card-value\">{{ stats.active_subscriptions }}</div><div class=\"stat-card-label\">启用中</div></div>\n      <div class=\"stat-card\"><div class=\"stat-card-value\">{{ stats.total_feeds }}</div><div class=\"stat-card-label\">Feed 源</div></div>\n      <div class=\"stat-card\"><div class=\"stat-card-value\">{{ stats.unique_users }}</div><div class=\"stat-card-label\">用户数</div></div>\n    </div>\n\n    <div class=\"tab-nav\">\n      <button class=\"tab-btn\" :class=\"{ active: activeTab === 'subs' }\" @click=\"openTab('subs')\">订阅列表</button>\n      <button class=\"tab-btn\" :class=\"{ active: activeTab === 'users' }\" @click=\"openTab('users')\">用户</button>\n      <button class=\"tab-btn\" :class=\"{ active: activeTab === 'feeds' }\" @click=\"openTab('feeds')\">Feed 源</button>\n      <button class=\"tab-btn\" :class=\"{ active: activeTab === 'push-history' }\" @click=\"openTab('push-history')\">推送历史</button>\n      <button class=\"tab-btn\" :class=\"{ active: activeTab === 'handlers' }\" @click=\"openTab('handlers')\">处理器</button>\n      <button class=\"tab-btn\" :class=\"{ active: activeTab === 'route-kb' }\" @click=\"openTab('route-kb')\">知识库</button>\n      <button class=\"tab-btn\" :class=\"{ active: activeTab === 'settings' }\" @click=\"openTab('settings')\">默认订阅设置</button>\n      <button class=\"tab-btn\" :class=\"{ active: activeTab === 'data-management' }\" @click=\"openTab('data-management')\">数据管理</button>\n    </div>\n";

export const dashboardTemplate = [
  '<div class="container" v-scope>',
  '  <div class="dashboard-shell">',
  statsAndTabsTemplate,
  subscriptionsActionsTemplate,
  usersActionsTemplate,
  feedsActionsTemplate,
  pushHistoryActionsTemplate,
  '    <div class="dashboard-content">',
  subscriptionsPageTemplate,
  usersPageTemplate,
  feedsPageTemplate,
  handlersPageTemplate,
  routeKbPageTemplate,
  pushHistoryPageTemplate,
  settingsPageTemplate,
  dataManagementPageTemplate,
  '    </div>',
  '  </div>',
  mainPanelTemplate,
  userPanelTemplate,
  feedPanelTemplate,
  dialogsTemplate,
  '</div>',
].join('\n');
