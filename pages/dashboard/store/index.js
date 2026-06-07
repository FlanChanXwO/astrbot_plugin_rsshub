import { getSuggestions } from '../js/api.js';
import { createAutocompleteMethods } from '../js/autocomplete.js';
import { createDashboardInitialState } from './state.js';
import { formatBytes, formatDate, formatUserState, prettyJson } from './helpers.js';
import { pendingModule } from './modules/pending.js';
import { lifecycleModule } from './modules/lifecycle.js';
import { filterModule } from './modules/filters.js';
import { overviewModule } from './modules/overview.js';
import { subscriptionsModule } from './modules/subscriptions.js';
import { usersModule } from './modules/users.js';
import { feedsModule } from './modules/feeds.js';
import { pushHistoryModule } from './modules/push-history.js';
import { routeKbModule } from './modules/route-kb.js';
import { settingsModule } from './modules/settings.js';
import { dataManagementModule } from './modules/data-management.js';
import { handlersModule } from './modules/handlers.js';
import { panelsModule } from './modules/panels.js';
import { overlayModule } from './modules/overlays.js';

export function createDashboardStore(PetiteVue) {
  return PetiteVue.reactive({
    ...createDashboardInitialState(),
    ...createAutocompleteMethods(getSuggestions),
    ...pendingModule,
    ...lifecycleModule,
    ...filterModule,
    ...overviewModule,
    ...subscriptionsModule,
    ...usersModule,
    ...feedsModule,
    ...pushHistoryModule,
    ...routeKbModule,
    ...settingsModule,
    ...dataManagementModule,
    ...handlersModule,
    ...panelsModule,
    ...overlayModule,
    formatDate,
    formatUserState,
    formatBytes,
    prettyJson,
  });
}
