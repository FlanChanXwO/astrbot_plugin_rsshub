import {
  deleteTemplate,
  getTemplates,
  installTemplateFromUrl,
} from '../../js/api.js';

function stringifyDetails(details) {
  if (details === undefined || details === null) return '';
  if (typeof details === 'string') return details;
  try {
    return JSON.stringify(details, null, 2);
  } catch {
    return String(details);
  }
}

export function validateTemplateInstallUrl(value) {
  const url = String(value || '').trim();
  if (!url) return { url: '', protocol: '', error: '模板 URL 不能为空' };
  try {
    const parsed = new URL(url);
    const protocol = parsed.protocol.toLowerCase();
    if (protocol !== 'http:' && protocol !== 'https:') {
      return { url, protocol, error: '模板 URL 只支持 HTTP(S)' };
    }
    return { url, protocol, error: '' };
  } catch {
    return { url, protocol: '', error: '模板 URL 格式无效' };
  }
}

export function safeTemplateRepositoryUrl(value) {
  const rawUrl = String(value || '').trim();
  if (!rawUrl) return '';
  try {
    const parsed = new URL(rawUrl);
    // metadata 来自可安装模板包；这里只允许可导航的 HTTP(S) 链接，避免危险协议进入 href。
    if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') return '';
    return parsed.href;
  } catch {
    return '';
  }
}

export const templatesModule = {
  async loadTemplates() {
    this.templatesLoading = true;
    this.templatesLoadError = '';
    try {
      const result = await getTemplates();
      this.templates = result.items || [];
      this.templatesTotal = result.total || 0;
    } catch (err) {
      this.templatesLoadError = err.message || '模板列表加载失败';
      this.showToast(`加载卡片模板失败: ${this.templatesLoadError}`, 'error');
    } finally {
      this.templatesLoading = false;
    }
  },

  filteredTemplates() {
    const keyword = String(this.templateFilter || '').trim().toLowerCase();
    if (!keyword) return this.templates;
    return this.templates.filter((template) =>
      [template.id, template.name, template.author, template.description, template.repository]
        .some((value) => String(value || '').toLowerCase().includes(keyword)),
    );
  },

  templateRepositoryUrl(template) {
    return safeTemplateRepositoryUrl(template?.repository);
  },

  async installTemplateFromPage() {
    const parsed = validateTemplateInstallUrl(this.templateInstallUrl);
    this.templateInstallError = parsed.error;
    if (parsed.error) return;
    let allowInsecureHttp = false;
    if (parsed.protocol === 'http:') {
      const confirmed = await this.showConfirm(
        'HTTP 模板下载未加密，内容可能被篡改。只有在确认信任来源时继续；模板运行在高信任浏览器模型中，作者脚本和网络访问可能带来风险。',
        '确认 HTTP 模板下载',
        '继续安装',
        'btn-danger',
      );
      if (!confirmed) return;
      allowInsecureHttp = true;
    }
    await this.runPending('templates:install', async () => {
      const result = await installTemplateFromUrl(parsed.url, allowInsecureHttp);
      this.templateInstallUrl = '';
      this.templateInstallError = '';
      this.showToast(result.message || '模板安装完成');
      await this.loadTemplates();
    }).catch((err) => {
      this.templateInstallError = err.message || '模板安装失败';
      this.showToast(`安装模板失败: ${this.templateInstallError}`, 'error');
    });
  },

  async deleteTemplateFromPage(template) {
    const templateId = String(template?.id || '').trim();
    if (!templateId) return;
    const confirmed = await this.showConfirm(
      `确定删除模板“${template.name || templateId}”？正在被 Subscription 或 Bundle 引用的模板会被后端拒绝删除。`,
      '删除卡片模板',
      '删除',
      'btn-danger',
    );
    if (!confirmed) return;
    await this.runPending(`templates:delete:${templateId}`, async () => {
      await deleteTemplate(templateId);
      this.showToast('卡片模板已删除');
      await this.loadTemplates();
    }).catch((err) => {
      const details = stringifyDetails(err.details);
      const message = details ? `${err.message}\n${details}` : err.message;
      this.showToast(`删除模板失败: ${message}`, 'error', 6000);
    });
  },
};
