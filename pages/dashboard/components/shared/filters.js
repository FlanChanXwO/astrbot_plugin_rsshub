// 这些 template factory 只生成筛选控件 HTML，不持有 API 或页面状态。

function autocompleteMenu(groupName, fieldName) {
  return String.raw`<div v-if="isAutocompleteOpen('${groupName}', '${fieldName}')" class="autocomplete-menu"><button v-for="(item, index) in autocompleteItems('${groupName}', '${fieldName}')" :key="item.value" type="button" class="autocomplete-option" :class="{ active: index === autocomplete.activeIndex }" @mousedown.prevent="acceptAutocomplete('${groupName}', '${fieldName}', item)"><span class="autocomplete-option-main">{{ item.label || item.value }}</span><span class="autocomplete-option-kind">{{ item.kind }}</span><span v-if="formatAutocompleteMeta(item)" class="autocomplete-option-meta">{{ formatAutocompleteMeta(item) }}</span></button><div v-if="autocomplete.loading" class="autocomplete-empty">搜索中...</div><div v-else-if="autocompleteItems('${groupName}', '${fieldName}').length === 0" class="autocomplete-empty">没有建议</div></div>`;
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
