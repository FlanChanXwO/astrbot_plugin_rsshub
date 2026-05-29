const AUTOCOMPLETE_DEBOUNCE_MS = 180;
const AUTOCOMPLETE_LIMIT = 10;

export function createAutocompleteState() {
  return {
    openKey: '',
    items: [],
    activeIndex: -1,
    loading: false,
    requestId: 0,
    timer: null,
  };
}

export function createAutocompleteMethods(getSuggestions) {
  return {
    isTagFilterField(groupName, fieldName) {
      const field = this[groupName]?.[fieldName];
      return Boolean(field && typeof field === 'object' && Array.isArray(field.values));
    },

    autocompleteKey(groupName, fieldName) {
      return `${groupName}:${fieldName}`;
    },

    isAutocompleteKeyActive(groupName, fieldName) {
      return this.autocomplete.openKey === this.autocompleteKey(groupName, fieldName);
    },

    autocompleteScope(groupName) {
      if (groupName === 'subFilters') return 'subscriptions';
      if (groupName === 'userFilters') return 'users';
      if (groupName === 'feedFilters') return 'feeds';
      if (groupName === 'pushHistoryFilter') return 'push-history';
      return '';
    },

    autocompleteQuery(groupName, fieldName) {
      const field = this[groupName]?.[fieldName];
      if (this.isTagFilterField(groupName, fieldName)) {
        return String(field.input || '').trim();
      }
      return String(field || '').trim();
    },

    isAutocompleteOpen(groupName, fieldName) {
      return (
        this.isAutocompleteKeyActive(groupName, fieldName) &&
        (this.autocomplete.loading || this.autocomplete.items.length > 0)
      );
    },

    isTagFilterPanelOpen(groupName, fieldName) {
      const field = this[groupName]?.[fieldName];
      if (!this.isTagFilterField(groupName, fieldName)) return false;
      if (!this.isAutocompleteKeyActive(groupName, fieldName)) return false;
      return (
        field.values.length > 0 ||
        this.autocomplete.loading ||
        this.autocomplete.items.length > 0 ||
        Boolean(String(field.input || '').trim())
      );
    },

    autocompleteItems(groupName, fieldName) {
      return this.isAutocompleteOpen(groupName, fieldName)
        ? this.autocomplete.items
        : [];
    },

    scheduleAutocomplete(groupName, fieldName) {
      const scope = this.autocompleteScope(groupName);
      if (!scope) return;
      const key = this.autocompleteKey(groupName, fieldName);
      const query = this.autocompleteQuery(groupName, fieldName);
      if (this.autocomplete.timer) {
        clearTimeout(this.autocomplete.timer);
        this.autocomplete.timer = null;
      }
      const requestId = this.autocomplete.requestId + 1;
      this.autocomplete.requestId = requestId;
      this.autocomplete.openKey = key;
      this.autocomplete.activeIndex = -1;
      if (!query) {
        this.autocomplete.items = [];
        this.autocomplete.loading = false;
        return;
      }
      this.autocomplete.loading = true;
      this.autocomplete.timer = setTimeout(async () => {
        try {
          const result = await getSuggestions(scope, fieldName, query, AUTOCOMPLETE_LIMIT);
          if (this.autocomplete.requestId !== requestId) return;
          this.autocomplete.items = result.items || [];
          this.autocomplete.activeIndex = this.autocomplete.items.length > 0 ? 0 : -1;
        } catch (err) {
          if (this.autocomplete.requestId === requestId) {
            this.autocomplete.items = [];
          }
        } finally {
          if (this.autocomplete.requestId === requestId) {
            this.autocomplete.loading = false;
            this.autocomplete.timer = null;
          }
        }
      }, AUTOCOMPLETE_DEBOUNCE_MS);
    },

    closeAutocomplete() {
      if (this.autocomplete.timer) {
        clearTimeout(this.autocomplete.timer);
        this.autocomplete.timer = null;
      }
      this.autocomplete.openKey = '';
      this.autocomplete.items = [];
      this.autocomplete.activeIndex = -1;
      this.autocomplete.loading = false;
      this.autocomplete.requestId += 1;
    },

    moveAutocomplete(delta) {
      const total = this.autocomplete.items.length;
      if (total <= 0) return;
      const current = this.autocomplete.activeIndex;
      this.autocomplete.activeIndex = (current + delta + total) % total;
    },

    acceptAutocomplete(groupName, fieldName, item) {
      const value = String(item?.value || '').trim();
      if (!value) return false;
      const field = this[groupName]?.[fieldName];
      if (this.isTagFilterField(groupName, fieldName)) {
        if (!field.values.includes(value)) {
          field.values.push(value);
        }
        field.input = '';
      } else if (this[groupName]) {
        this[groupName][fieldName] = value;
      }
      this.closeAutocomplete();
      this.scheduleFilterRefresh(groupName);
      return true;
    },

    acceptActiveAutocomplete(groupName, fieldName) {
      const index = this.autocomplete.activeIndex;
      if (index < 0) return false;
      return this.acceptAutocomplete(
        groupName,
        fieldName,
        this.autocomplete.items[index]
      );
    },

    handleAutocompleteKeydown(event, groupName, fieldName) {
      if (event.isComposing || !this.isAutocompleteOpen(groupName, fieldName)) {
        return false;
      }
      if (event.key === 'ArrowDown') {
        event.preventDefault();
        this.moveAutocomplete(1);
        return true;
      }
      if (event.key === 'ArrowUp') {
        event.preventDefault();
        this.moveAutocomplete(-1);
        return true;
      }
      if (event.key === 'Enter' && this.autocomplete.activeIndex >= 0) {
        event.preventDefault();
        return this.acceptActiveAutocomplete(groupName, fieldName);
      }
      if (event.key === 'Escape') {
        event.preventDefault();
        this.closeAutocomplete();
        return true;
      }
      return false;
    },

    formatAutocompleteMeta(item) {
      const meta = item?.meta || {};
      return Object.values(meta)
        .map((value) => String(value || '').trim())
        .filter(Boolean)
        .join(' · ');
    },
  };
}
