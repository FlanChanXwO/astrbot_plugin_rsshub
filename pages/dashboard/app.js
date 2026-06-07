import { ready, checkUpdates } from './js/api.js';
import { initTheme } from './js/theme.js';
import { dashboardTemplate } from './components/dashboard-template.js';
import { createDashboardStore } from './store/index.js';

const store = createDashboardStore(PetiteVue);
window.store = store;

let pollTimer = null;

initTheme();
document.getElementById('dashboard-root').innerHTML = dashboardTemplate;
ready()
  .then(async () => {
    await store.loadData();
    pollTimer = setInterval(async () => {
      const { changed } = await checkUpdates();
      if (!changed) return;
      if (store.activeTab === 'overview') {
        store.loadOverview();
      } else {
        store.loadData(false);
      }
    }, 10000);
    window.addEventListener('beforeunload', () => {
      if (pollTimer) clearInterval(pollTimer);
      store.stopRouteKbPolling();
    });
  })
  .catch((err) => store.showToast(`初始化失败: ${err.message}`, 'error'));

PetiteVue.createApp(store).mount('.container');
