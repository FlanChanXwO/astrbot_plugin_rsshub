

export const pendingModule = {
  isPending(key) {
    return Boolean(this.pendingActions[key]);
  },

  async runPending(key, action) {
    if (this.isPending(key)) return null;
    this.pendingActions[key] = true;
    try {
      return await action();
    } finally {
      delete this.pendingActions[key];
    }
  }
};
