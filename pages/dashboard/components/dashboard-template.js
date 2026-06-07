import { overviewPageTemplate } from './pages/overview.js';
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

const sidebarTemplate = String.raw`
    <aside class="dashboard-sidebar" aria-label="RSSHub 管理导航">
      <div class="dashboard-sidebar-title">RSSHub</div>
      <nav class="dashboard-nav">
        <button class="dashboard-nav-item" :class="{ active: activeTab === 'overview' }" @click="openTab('overview')" type="button">概览</button>
        <button class="dashboard-nav-item" :class="{ active: activeTab === 'subs' }" @click="openTab('subs')" type="button">订阅列表</button>
        <button class="dashboard-nav-item" :class="{ active: activeTab === 'users' }" @click="openTab('users')" type="button">用户</button>
        <button class="dashboard-nav-item" :class="{ active: activeTab === 'feeds' }" @click="openTab('feeds')" type="button">Feed 源</button>
        <button class="dashboard-nav-item" :class="{ active: activeTab === 'push-history' }" @click="openTab('push-history')" type="button">推送历史</button>
        <button class="dashboard-nav-item" :class="{ active: activeTab === 'handlers' }" @click="openTab('handlers')" type="button">处理器</button>
        <button class="dashboard-nav-item" :class="{ active: activeTab === 'route-kb' }" @click="openTab('route-kb')" type="button">知识库</button>
        <button class="dashboard-nav-item" :class="{ active: activeTab === 'settings' }" @click="openTab('settings')" type="button">默认订阅设置</button>
        <button class="dashboard-nav-item" :class="{ active: activeTab === 'data-management' }" @click="openTab('data-management')" type="button">数据管理</button>
      </nav>
    </aside>
`;

export const dashboardTemplate = [
  '<div class="container" v-scope>',
  '  <div class="dashboard-shell">',
  sidebarTemplate,
  '    <main class="dashboard-main">',
  '      <div class="dashboard-toolbar-stack">',
  subscriptionsActionsTemplate,
  usersActionsTemplate,
  feedsActionsTemplate,
  pushHistoryActionsTemplate,
  '      </div>',
  '      <div class="dashboard-content">',
  overviewPageTemplate,
  subscriptionsPageTemplate,
  usersPageTemplate,
  feedsPageTemplate,
  handlersPageTemplate,
  routeKbPageTemplate,
  pushHistoryPageTemplate,
  settingsPageTemplate,
  dataManagementPageTemplate,
  '      </div>',
  '    </main>',
  '  </div>',
  mainPanelTemplate,
  userPanelTemplate,
  feedPanelTemplate,
  dialogsTemplate,
  '</div>',
].join('\n');
