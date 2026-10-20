let token = '';
export function setToken(value: string) { token = value; }

const errors: Record<string, string> = {
  ANOTHER_RUN_ACTIVE: '已有任务正在执行，请先完成或取消当前任务。',
  REVISION_CONFLICT: '这份草稿已发生变化，请刷新后重新核对。',
  CLOUD_DISABLED: '云端模型尚未获得授权或完成配置。答卷仍保留在本地。',
  LOGIN_NOT_READY: '浏览器尚未准备就绪，请完成登录后重试。',
  IDENTITY_MISMATCH: '页面账号、课程或题目与授权任务不一致，读取已停止。',
  PAGE_STRUCTURE_CHANGED: '页面结构不符合已验证的适配规则，请联系维护者。',
  MODEL_KEY_MISSING: '系统凭据存储中尚未配置模型密钥。',
  MODEL_CONNECTION_INCOMPLETE: '请填写完整的 API 请求地址、模型名称和密钥。',
  MODEL_AUTH_FAILED: '服务商拒绝了密钥，请检查密钥是否正确、是否有该模型的访问权限。',
  MODEL_RATE_LIMITED: '服务商当前限流或余额不足，请检查账户额度后重试。',
  MODEL_CONNECTION_FAILED: '连接未成功，请核对完整 API 地址、模型名称和服务商状态。',
  MODEL_CONNECTION_TIMEOUT: '连接超时或网络不可用，请检查网络后重试。',
  MODEL_NEW_ENDPOINT_KEY_REQUIRED: '服务地址已改变，请为新服务重新输入密钥后测试。',
  MODEL_RESPONSE_INVALID: '服务已响应，但返回格式不符合当前对话接口要求。',
  PROTECTED_KEYRING_REQUIRED: '本机未找到受保护的系统凭据库，请联系维护者。',
  CREDENTIAL_STORE_UNAVAILABLE: '系统凭据库暂不可用，请检查 Windows 账户权限后重试。',
  SETTINGS_SAVE_FAILED: '设置保存失败，请检查磁盘空间和本地目录权限。',
  KEY_ACTION_CONFLICT: '替换密钥和移除密钥不能同时执行，请选择其中一种操作。',
  PROCESS_INTERRUPTED: '上次运行被中断，可恢复未完成的答卷。',
  NO_PENDING_ITEMS: '没有需要重新生成的答卷。',
  UNEXPECTED_NETWORK_REQUEST: '页面发起了白名单之外的请求，已阻止并暂停读取。',
  MODEL_BUDGET_EXCEEDED: '已达到本任务的模型请求上限。',
  STORAGE_FAILURE: '本地存储失败，任务已停止。请检查磁盘空间和存储权限，修复后再恢复。',
  LOCAL_TOKEN_REQUIRED: '本地会话已失效，请刷新页面。',
};
export function errorText(code: string) { return errors[code] || `操作未完成（${code}），请核对后重试。`; }

export async function api<T>(path: string, body?: unknown): Promise<T> {
  // 前端只访问本地后端；云服务请求与密钥存取集中在 Python 侧处理。
  const response = await fetch(`/api${path}`, {
    method: body === undefined ? 'GET' : 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Local-Token': token },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({ code: 'NETWORK_ERROR' }));
    throw new Error(errorText(data.code));
  }
  return response.json() as Promise<T>;
}
