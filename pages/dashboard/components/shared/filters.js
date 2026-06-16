// 这些 template factory 只生成筛选控件 HTML，不持有 API 或页面状态。

function autocompleteMenu(groupName, fieldName) {
  return String.raw`<div v-if="isAutocompleteOpen('${groupName}', '${fieldName}')" class="autocomplete-menu"><button v-for="(item, index) in autocompleteItems('${groupName}', '${fieldName}')" :key="item.value" type="button" class="autocomplete-option" :class="{ active: index === autocomplete.activeIndex }" @mousedown.prevent="acceptAutocomplete('${groupName}', '${fieldName}', item)"><span class="autocomplete-option-main">{{ item.label || item.value }}</span><span class="autocomplete-option-kind">{{ item.kind }}</span><span v-if="formatAutocompleteMeta(item)" class="autocomplete-option-meta">{{ formatAutocompleteMeta(item) }}</span></button><div v-if="autocomplete.loading" class="autocomplete-empty">搜索中...</div><div v-else-if="autocompleteItems('${groupName}', '${fieldName}').length === 0" class="autocomplete-empty">没有建议</div></div>`;
}

function autocompleteMenuForFieldExpr(groupName, fieldExpr) {
  return String.raw`<div v-if="isAutocompleteOpen('${groupName}', ${fieldExpr})" class="autocomplete-menu"><button v-for="(item, index) in autocompleteItems('${groupName}', ${fieldExpr})" :key="item.value" type="button" class="autocomplete-option" :class="{ active: index === autocomplete.activeIndex }" @mousedown.prevent="acceptAutocomplete('${groupName}', ${fieldExpr}, item)"><span class="autocomplete-option-main">{{ item.label || item.value }}</span><span class="autocomplete-option-kind">{{ item.kind }}</span><span v-if="formatAutocompleteMeta(item)" class="autocomplete-option-meta">{{ formatAutocompleteMeta(item) }}</span></button><div v-if="autocomplete.loading" class="autocomplete-empty">搜索中...</div><div v-else-if="autocompleteItems('${groupName}', ${fieldExpr}).length === 0" class="autocomplete-empty">没有建议</div></div>`;
}

function tagFilterPanel(groupName, fieldName) {
  return String.raw`<div v-if="isTagFilterPanelOpen('${groupName}', '${fieldName}')" class="tag-filter-panel"><div v-if="${groupName}.${fieldName}.values.length > 0" class="tag-filter-panel-section"><div class="tag-filter-panel-title">已选项</div><button v-for="tag in ${groupName}.${fieldName}.values" :key="tag" type="button" class="tag-filter-selected-item" :title="tag" :aria-label="'移除筛选项 ' + tag" @mousedown.prevent="removeFilterTag('${groupName}', '${fieldName}', tag)"><span class="tag-filter-selected-text">{{ tag }}</span><span class="tag-filter-remove" aria-hidden="true">×</span></button></div><div v-if="autocomplete.loading || autocompleteQuery('${groupName}', '${fieldName}') || autocompleteItems('${groupName}', '${fieldName}').length > 0" class="tag-filter-panel-section"><div class="tag-filter-panel-title">建议</div><button v-for="(item, index) in autocompleteItems('${groupName}', '${fieldName}')" :key="item.value" type="button" class="autocomplete-option" :class="{ active: index === autocomplete.activeIndex }" @mousedown.prevent="acceptAutocomplete('${groupName}', '${fieldName}', item)"><span class="autocomplete-option-main">{{ item.label || item.value }}</span><span class="autocomplete-option-kind">{{ item.kind }}</span><span v-if="formatAutocompleteMeta(item)" class="autocomplete-option-meta">{{ formatAutocompleteMeta(item) }}</span></button><div v-if="autocomplete.loading" class="autocomplete-empty">搜索中...</div><div v-else-if="autocompleteQuery('${groupName}', '${fieldName}') && autocompleteItems('${groupName}', '${fieldName}').length === 0" class="autocomplete-empty">没有建议</div></div></div>`;
}

export function tagFilterTemplate({ groupName, fieldName, label, wide = false }) {
  const classes = wide
    ? 'tag-filter tag-filter-wide autocomplete-field'
    : 'tag-filter autocomplete-field';
  return String.raw`
      <div class="${classes}"><div class="tag-filter-label">${label}</div><div class="tag-filter-control"><span v-if="${groupName}.${fieldName}.values.length > 0" class="filter-selection-summary">已选 {{ ${groupName}.${fieldName}.values.length }}</span><input class="tag-filter-input" type="text" v-model="${groupName}.${fieldName}.input" :placeholder="${groupName}.${fieldName}.values.length > 0 ? '继续输入' : '输入或选择'" @input="handleTagFilterInput('${groupName}', '${fieldName}')" @focus="scheduleAutocomplete('${groupName}', '${fieldName}')" @keydown="handleFilterKeydown($event, '${groupName}', '${fieldName}')" @blur="handleFilterBlur('${groupName}', '${fieldName}')" @paste="handleFilterPaste($event, '${groupName}', '${fieldName}')" /></div>${tagFilterPanel(groupName, fieldName)}</div>`;
}

export function textFilterTemplate({ groupName, fieldName, label, placeholder = '输入关键词', wide = false }) {
  const classes = wide ? 'text-filter text-filter-wide autocomplete-field' : 'text-filter autocomplete-field';
  return String.raw`
      <div class="${classes}"><div class="filter-field-label">${label}</div><input class="filter-text-input" type="text" v-model="${groupName}.${fieldName}" placeholder="${placeholder}" @input="handleTextFilterInput('${groupName}', '${fieldName}')" @focus="scheduleAutocomplete('${groupName}', '${fieldName}')" @keydown="handleAutocompleteKeydown($event, '${groupName}', '${fieldName}')" @blur="handleAutocompleteBlur('${groupName}', '${fieldName}')" />${autocompleteMenu(groupName, fieldName)}</div>`;
}

function compactFilterInput(groupName, activeFieldExpr) {
  return String.raw`
      <div class="compact-filter-value autocomplete-field" v-if="compactFilterActiveField('${groupName}').type !== 'select'">
        <input class="filter-text-input" type="text" v-model="${groupName}[${activeFieldExpr}].input" :placeholder="compactFilterActiveField('${groupName}').placeholder || '筛选值'" @input="handleCompactFilterInput('${groupName}')" @focus="scheduleAutocomplete('${groupName}', ${activeFieldExpr})" @keydown="handleCompactFilterKeydown($event, '${groupName}')" @blur="handleAutocompleteBlur('${groupName}', ${activeFieldExpr})" @paste="handleFilterPaste($event, '${groupName}', ${activeFieldExpr})" />
        ${autocompleteMenuForFieldExpr(groupName, activeFieldExpr)}
      </div>
      <select class="select-input compact-filter-value" v-else v-model="compactFilterUi.${groupName}.value">
        <option value="">全部状态</option>
        <option v-for="option in compactFilterActiveField('${groupName}').options" :key="option.value" :value="option.value">{{ option.label }}</option>
      </select>`;
}

function compactFilterChips(groupName) {
  return String.raw`
      <div class="compact-filter-chips" v-if="compactFilterChips('${groupName}').length > 0">
        <button v-for="chip in compactFilterChips('${groupName}')" :key="chip.key" type="button" class="filter-chip" :title="chip.value" :aria-label="'移除筛选 ' + chip.label + ' ' + chip.value" @click="removeCompactFilterChip('${groupName}', chip)">
          <span class="filter-chip-label">{{ chip.label }}</span>
          <span class="filter-chip-value">{{ chip.value }}</span>
          <span class="filter-chip-remove" aria-hidden="true">×</span>
        </button>
      </div>`;
}

export function compactFilterToolbarTemplate({
  groupName,
  visibleExpr,
  pendingKey,
  loadAction,
  clearAction,
  hasFilters,
  extraButtons = [],
}) {
  const activeFieldExpr = `compactFilterUi.${groupName}.field`;
  return String.raw`
    <div class="action-bar compact-filter-toolbar" v-if="${visibleExpr}">
      <div class="compact-filter-row">
        <div class="compact-search-field autocomplete-field">
          <span class="compact-filter-icon" aria-hidden="true">⌕</span>
          <input class="filter-text-input" type="text" v-model="${groupName}.keyword" :placeholder="compactFilterKeywordPlaceholder('${groupName}')" @input="scheduleAutocomplete('${groupName}', 'keyword')" @focus="scheduleAutocomplete('${groupName}', 'keyword')" @keydown="handleCompactKeywordKeydown($event, '${groupName}', '${pendingKey}', () => ${loadAction})" @blur="handleAutocompleteBlur('${groupName}', 'keyword')" />
          ${autocompleteMenu(groupName, 'keyword')}
        </div>
        <span class="compact-filter-icon compact-filter-funnel" aria-hidden="true">⌯</span>
        <select class="select-input compact-filter-field" v-model="${activeFieldExpr}">
          <option v-for="field in compactFilterFields('${groupName}')" :key="field.key" :value="field.key">{{ field.label }}</option>
        </select>
        ${compactFilterInput(groupName, activeFieldExpr)}
        <button class="btn btn-add-circle" type="button" title="添加筛选条件" aria-label="添加筛选条件" @click="addCompactFilterCondition('${groupName}')">+</button>
        <button class="btn btn-secondary compact-clear-button" v-if="${hasFilters}()" type="button" :disabled="isPending('${pendingKey}')" @click="${clearAction}()">清空</button>
        <div class="compact-toolbar-spacer"></div>
        ${extraButtons.join('\n        ')}
        <button class="btn btn-icon" type="button" :class="{ 'is-loading': isPending('${pendingKey}') }" :disabled="isPending('${pendingKey}')" @click="runPending('${pendingKey}', () => ${loadAction})" title="刷新" aria-label="刷新">⟳</button>
      </div>
      ${compactFilterChips(groupName)}
    </div>`;
}

export function filterSummaryTemplate() {
  return '';
}

export function batchToolbarTemplate({ visibleExpr, countExpr, buttons }) {
  return String.raw`
    <div class="batch-toolbar" :class="{ visible: ${visibleExpr} }">
      <span class="count">已选 {{ ${countExpr} }} 项</span>
      ${buttons.join('\n      ')}
    </div>`;
}
