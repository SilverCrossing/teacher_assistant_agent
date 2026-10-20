import { useEffect, useState } from 'react';
import { Check, LoaderCircle, LockKeyhole, PlugZap, Save, ShieldCheck } from 'lucide-react';
import { api } from './api';

interface Connection {
  endpoint: string; model: string; enabled: boolean; effective_enabled: boolean;
  approved: boolean; has_key: boolean; credentials_available: boolean; school_enabled: boolean;
}

/** 密钥仅保留在此组件的短暂输入状态中，不写 localStorage，也不从服务端回显。 */
export function ModelSettings({ onSaved }: { onSaved: () => Promise<void> }) {
  const [connection, setConnection] = useState<Connection | null>(null);
  const [endpoint, setEndpoint] = useState('');
  const [model, setModel] = useState('');
  const [secret, setSecret] = useState('');
  const [enabled, setEnabled] = useState(false);
  const [clearKey, setClearKey] = useState(false);
  const [busy, setBusy] = useState('');
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  useEffect(() => {
    api<Connection>('/settings/model').then(value => {
      setConnection(value); setEndpoint(value.endpoint); setModel(value.model); setEnabled(value.enabled);
    }).catch(e => setError(e.message));
  }, []);

  const execute = async (kind: 'save' | 'test') => {
    setBusy(kind); setError(''); setMessage('');
    const value = { endpoint, model, enabled, api_key: secret, clear_key: clearKey };
    try {
      if (kind === 'save') {
        const saved = await api<Connection>('/settings/model', value);
        setConnection(saved); setSecret(''); setClearKey(false);
        setMessage(saved.effective_enabled ? '已保存并生效。下次生成使用新配置。' : '配置已保存，可测试连接。真实答卷外发需完成学校授权。');
        await onSaved();
      } else {
        const result = await api<{ message: string }>('/settings/model/test', value);
        setMessage(result.message);
      }
    } catch (e) { setError((e as Error).message); } finally { setBusy(''); }
  };

  return <section className="panel model-settings">
    <div className="model-heading"><span className="model-icon"><PlugZap size={23} /></span><div><h2>模型 API 设置</h2><p>填写服务商提供的连接信息，先测试，再保存。无需编辑配置文件。</p></div></div>
    <ol className="setup-steps"><li>获取 API 密钥</li><li>填写地址与模型</li><li>测试并保存</li></ol>
    {error && <div className="alert error" role="alert">{error}</div>}
    {message && <div className="alert success" role="status"><Check size={17} />{message}</div>}
    {!connection && !error && <p className="muted">正在读取设置…</p>}
    <form onSubmit={e => { e.preventDefault(); void execute('save'); }}>
      <label htmlFor="model-endpoint">API 请求地址 <span>必填</span></label>
      <input id="model-endpoint" type="url" required placeholder="https://服务商域名/v1/chat/completions" value={endpoint} disabled={!!busy || !connection} onChange={e => setEndpoint(e.target.value)} />
      <p className="field-help">填写完整 HTTPS 请求地址，以服务商文档为准。当前支持兼容 messages / choices 的对话接口。</p>
      <label htmlFor="model-name">模型名称 <span>必填</span></label>
      <input id="model-name" required placeholder="填写服务商提供的模型 ID" value={model} disabled={!!busy || !connection} maxLength={200} onChange={e => setModel(e.target.value)} />
      <p className="field-help">须与账号可用的模型名称一致。连接测试会产生一次很小的 API 调用费用。</p>
      <label htmlFor="model-key">API 密钥 <span>{connection?.has_key ? '已安全保存 · 留空表示保留' : '尚未保存'}</span></label>
      <input id="model-key" type="password" autoComplete="new-password" spellCheck={false} placeholder={connection?.has_key ? '输入新密钥可替换，原密钥不会显示' : '粘贴 API 密钥'} value={secret} disabled={!!busy || !connection || clearKey} maxLength={4000} onChange={e => setSecret(e.target.value)} />
      <p className="field-help"><LockKeyhole size={12} />密钥保存在 Windows 系统凭据库，不写入配置文件。修改服务地址时需要重新输入密钥。</p>
      {connection?.has_key && <label className="check-field"><input type="checkbox" checked={clearKey} disabled={!!busy || !!secret} onChange={e => setClearKey(e.target.checked)} />移除当前连接保存的密钥</label>}
      <label className="check-field"><input type="checkbox" checked={enabled} disabled={!!busy || !connection} onChange={e => setEnabled(e.target.checked)} />完成学校授权后，允许此连接用于真实答卷</label>
      <div className="connection-state"><ShieldCheck size={17} /><span>{connection?.effective_enabled ? '真实外发已启用；每次生成仍需预览确认。' : '当前真实答卷外发未启用。可先保存参数、测试连接。'}</span></div>
      {!connection?.approved && <p className="field-help">学校站点、服务商地址、模型与数据政策需由校方维护者核验并批准。修改服务商或模型后，旧批准不会自动沿用；合成演示始终在本地运行。</p>}
      {connection && !connection.credentials_available && <div className="alert warning">系统凭据库暂不可用，请联系本机维护者；程序不会改用明文文件保存密钥。</div>}
      <div className="settings-actions"><button type="button" className="button" disabled={!!busy || !endpoint || !model || clearKey} onClick={() => void execute('test')}>{busy === 'test' ? <LoaderCircle className="spin" size={15} /> : <PlugZap size={15} />}测试连接</button><button type="submit" className="button primary" disabled={!!busy || !connection}>{busy === 'save' ? <LoaderCircle className="spin" size={15} /> : <Save size={15} />}保存 API 设置</button></div>
    </form>
  </section>;
}
