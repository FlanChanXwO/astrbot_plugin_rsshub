export const dialogsTemplate = String.raw`
  <div class="toast" :class="[toast.type, { show: toast.show }]" v-if="toast.show">{{ toast.message }}</div>

  <div class="confirm-dialog" :class="{ visible: dialog.show }" v-if="dialog.show" style="display:flex;">
    <div class="confirm-dialog-overlay" @click="dialog.resolve(false)"></div>
    <div class="confirm-dialog-content">
      <h4>{{ dialog.title }}</h4>
      <p>{{ dialog.message }}</p>
      <label v-if="dialog.optionLabel" class="confirm-option">
        <input type="checkbox" v-model="dialog.optionValue" />
        <span>{{ dialog.optionLabel }}</span>
      </label>
      <div class="confirm-dialog-actions">
        <button type="button" class="btn btn-secondary" @click="dialog.resolve(false)">取消</button>
        <button type="button" class="btn" :class="dialog.okClass" @click="dialog.resolve(true)">{{ dialog.okText }}</button>
      </div>
    </div>
  </div>
`;
