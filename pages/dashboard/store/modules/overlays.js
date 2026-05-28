

let toastTimer = null;

export const overlayModule = {
  showToast(message, type = 'success', duration = 3000) {
    if (toastTimer) clearTimeout(toastTimer);
    this.toast.show = true;
    this.toast.message = message;
    this.toast.type = type;
    toastTimer = setTimeout(() => {
      this.toast.show = false;
    }, duration);
  },

  showConfirm(message, title = '确认', okText = '确定', okClass = 'btn-danger', options = {}) {
    const hasOption = Boolean(options.optionLabel);
    this.dialog.title = title;
    this.dialog.message = message;
    this.dialog.okText = okText;
    this.dialog.okClass = okClass;
    this.dialog.optionLabel = String(options.optionLabel || '');
    this.dialog.optionValue = Boolean(options.optionDefault);
    this.dialog.show = true;
    return new Promise((resolve) => {
      this.dialog.resolve = (result) => {
        this.dialog.show = false;
        if (!hasOption) {
          resolve(Boolean(result));
          return;
        }
        resolve({
          ok: Boolean(result),
          optionChecked: Boolean(result && this.dialog.optionValue),
        });
      };
    });
  }
};
