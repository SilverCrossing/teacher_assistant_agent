let token = '';
export function setToken(value: string) { token = value; }

const errors: Record<string, string> = {
  SIMULATION_NOT_FOUND: '未找到这份模拟记录，请刷新后重新选择。',
  SIMULATION_TRANSCRIPT_REQUIRED: '请先读取并确认有效作答，再生成评分草稿。',
  SCORE_OUT_OF_RANGE: '请完整填写各评分点，分数必须在零分与该项满分之间。',
  MATERIAL_NOT_CONFIRMED: '资料尚未确认或版本已变化，请重新选择已确认的版本。',
  MATERIAL_MAPPING_INVALID: '该资料无法关联此任务，请核对已授权的学校任务及小题。',
  MATERIAL_SCORE_MISMATCH: '资料中评分点的总分与学校任务满分不同，请先修正。',
  MATERIAL_FILE_INVALID: '请选择 PDF、DOCX、TXT、MD、PNG 或 JPG 文件，单个文件不超过 15 MB。',
  MATERIAL_PARSE_FAILED: '无法读取文件。请检查文件是否损坏、加密或超过 100 页；旧版 Word 请另存为 DOCX。',
  MATERIAL_FILE_LIMIT: '每份试卷最多上传 30 个文件，请拆分为多份资料。',
  MATERIAL_NOT_FOUND: '这份资料不存在，请刷新列表。',
  REQUEST_TOO_LARGE: '内容超过大小限制，请拆分后再上传。',
  INVALID_REQUEST: '请检查必填项、题号是否重复，以及评分点的分值。',
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
  CREDENTIAL_STORE_UNAVAILABLE: '无法访问系统凭据库。请关闭当前服务，在已登录的 Windows 桌面双击“启动阅卷助手.bat”后刷新页面；若仍失败，请联系维护者检查登录会话。',
  EXISTING_DATABASE_KEY_MISSING: '当前 Windows 账户缺少已有资料的解密密钥，请使用原账户启动；请勿删除数据库或重建密钥。',
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

// 原件使用受保护的请求获取，令牌不进入下载链接或浏览器历史。
export async function materialFile(path: string, file?: File, version?: number, role?: string): Promise<Response> {
  const response = await fetch(`/api${path}`, {
    method: file ? 'POST' : 'GET',
    headers: { 'X-Local-Token': token, ...(file ? {
      'X-File-Name': encodeURIComponent(file.name), 'X-Material-Version': String(version),
      'X-Material-Role': role || 'paper', 'Content-Type': 'application/octet-stream',
    } : {}) }, body: file,
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({ code: 'NETWORK_ERROR' }));
    throw new Error(errorText(data.code));
  }
  return response;
}
