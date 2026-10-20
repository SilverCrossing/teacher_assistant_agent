import React, { useCallback, useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import {
  BookOpenCheck, LayoutDashboard, ShieldCheck, History, Settings2, ChevronRight,
  ArrowRight, Play, Square, RotateCcw, Check, X, Search, FileText, FlaskConical,
  CircleHelp, AlertTriangle, Eye, LoaderCircle, CheckCheck, ListChecks, LockKeyhole,
} from 'lucide-react';
import { api, errorText, setToken } from './api';
import type { Session, GradingTask, Run, Item } from './types';
import './style.css';
import { ModelSettings } from './ModelSettings';
import { Materials, type Exam } from './Materials';
import { Simulation } from './Simulation';

const labels: Record<string, string> = {
  reading: '读取中', awaiting_login: '待登录', ready: '待生成', generating: '生成中',
  review: '待复核', reviewed: '已本地复核', paused: '已暂停', cancelled: '已取消',
  pending: '待生成', draft: '待复核', accepted: '已接受', edited: '已修改', rejected: '已拒绝',
  manual: '需人工处理', error: '生成失败',
};
const busyStates = ['reading', 'generating', 'awaiting_login'];
const time = (s: string) => new Date(s).toLocaleString('zh-CN', { hour12: false });
const score = (n: number) => Number(n.toFixed(2));

function Badge({ status }: { status: string }) {
  return <span className={`badge ${status}`}>{labels[status] || status}</span>;
}

function App() {
  const [session, setSession] = useState<Session | null>(null);
  const [tasks, setTasks] = useState<GradingTask[]>([]);
  const [taskId, setTaskId] = useState('');
  const [runs, setRuns] = useState<Run[]>([]);
  const [run, setRun] = useState<Run | null>(null);
  const [selected, setSelected] = useState('');
  const [tab, setTab] = useState('work');
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState('all');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [toast, setToast] = useState('');
  const [preview, setPreview] = useState(false);
  const [materials, setMaterials] = useState<Exam[]>([]);
  const [materialKey, setMaterialKey] = useState('');
  const [mappingChecked, setMappingChecked] = useState(false);
  const [audit, setAudit] = useState<{ created_at: string; event: string; version?: number; action?: string; code?: string }[]>([]);

  // 本地令牌仅放在内存中；页面刷新后重新握手，避免长期持久化鉴权信息。
  const load = useCallback(async () => {
    const s = await api<Session>('/session'); setToken(s.token); setSession(s);
    const [t, r] = await Promise.all([api<GradingTask[]>('/tasks'), api<Run[]>('/runs')]);
    setTasks(t); setTaskId(t[0]?.id || ''); setRuns(r);
    setMaterials(await api<Exam[]>('/materials'));
    if (r[0]) setRun(await api<Run>(`/runs/${r[0].id}`));
  }, []);
  useEffect(() => { load().catch(e => setError(`无法连接本地服务。${e.message}`)); }, [load]);
  // 只在任务运行期间轮询，进入待生成/待复核状态后停止，减少无效请求。
  useEffect(() => {
    if (!run || !busyStates.includes(run.status)) return;
    const timer = window.setInterval(() => {
      api<Run>(`/runs/${run.id}`).then(setRun).catch(e => setError(e.message));
    }, 900);
    return () => clearInterval(timer);
  }, [run?.id, run?.status]);
  useEffect(() => {
    if (run && !run.items.some(i => i.evidence.submission_id === selected)) {
      setSelected(run.items[0]?.evidence.submission_id || '');
    }
  }, [run, selected]);
  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(''), 3500);
    return () => clearTimeout(timer);
  }, [toast]);

  const act = async (operation: () => Promise<unknown>) => {
    setPending(true); setError('');
    try { await operation(); } catch (e) { setError((e as Error).message); } finally { setPending(false); }
  };
  const action = (name: string) => act(async () => {
    if (run) setRun(await api<Run>(`/runs/${run.id}/${name}`, {}));
  });
  const start = () => act(async () => {
    const [examId, index] = materialKey.split('/');
    const exam = materials.find(e => e.id === examId);
    const next = await api<Run>('/runs', { task_id: taskId, ...(exam ? {
      material_id: exam.id, material_version: exam.version, material_question: exam.questions[Number(index)].number,
    } : {}) });
    setRun(next); setSelected(''); setFilter('all'); setTab('work');
    setRuns(await api<Run[]>('/runs'));
  });
  const openTab = (next: string) => {
    setTab(next);
    if (next === 'work') {
      setMaterialKey(''); setMappingChecked(false);
      void api<Exam[]>('/materials').then(setMaterials).catch(e => setError(e.message));
    }
    if (next === 'history') void act(async () => setRuns(await api<Run[]>('/runs')));
    if (next === 'audit' && run) void act(async () => setAudit(await api(`/runs/${run.id}/audit`)));
  };
  const item = run?.items.find(i => i.evidence.submission_id === selected);
  const stats = {
    total: run?.items.length || 0,
    reviewed: run?.items.filter(i => ['accepted', 'edited', 'rejected'].includes(i.status)).length || 0,
    waiting: run?.items.filter(i => i.status === 'draft').length || 0,
    manual: run?.items.filter(i => ['manual', 'error'].includes(i.status)).length || 0,
  };
  const active = !!run && busyStates.includes(run.status);
  const filtered = run?.items.filter(i => i.evidence.submission_id.toLowerCase().includes(query.toLowerCase()) &&
    (filter === 'all' || (filter === 'draft' ? i.status === 'draft' : ['manual', 'error'].includes(i.status)))) || [];
  const currentTask = tasks.find(t => t.id === taskId);

  return <div className="app">
    <aside className="sidebar">
      <a className="brand" href="/" aria-label="阅卷助手首页"><span className="brand-icon"><BookOpenCheck size={23} /></span><span>阅卷助手<small>TEACHER ASSISTANT</small></span></a>
      <div className="workspace-label">教师工作空间</div>
      <nav>
        {[['work', '阅卷工作台', LayoutDashboard], ['history', '任务记录', History],
          ['simulation', '模拟批卷页', FlaskConical], ['materials', '试卷与答案库', FileText], ['audit', '审计记录', ShieldCheck], ['settings', '安全与配置', Settings2]].map(([key, title, Icon]) => {
          const I = Icon as typeof LayoutDashboard;
          return <button key={key as string} className={tab === key ? 'nav-item active' : 'nav-item'} onClick={() => openTab(key as string)}><I size={18} />{title as string}{tab === key && <span className="nav-dot" />}</button>;
        })}
      </nav>
      <div className="sidebar-note"><ShieldCheck size={22} /><strong>每一次评分，由你决定</strong><p>助手只生成本地草稿，<br />正式成绩由教师在原站提交。</p></div>
      <div className="local-status"><span className={session ? 'online-dot' : 'offline-dot'} />{session ? '本地服务已连接' : '正在连接本地服务'}<small>v0.1.0</small></div>
    </aside>
    <main>
      <header className="topbar"><div>教师工作空间 <ChevronRight size={14} /><span>{({ work: '阅卷工作台', simulation: '模拟批卷页', materials: '试卷与答案库', history: '任务记录', audit: '审计记录', settings: '安全与配置' } as Record<string, string>)[tab]}</span></div><span className="local-pill"><LockKeyhole size={13} /> 本地运行</span></header>
      <div className="page">
        <div className="page-heading"><div><div className="eyebrow">LESS BUSYWORK. MORE TEACHING.</div><h1>{tab === 'work' ? '让复核更专注' : tab === 'simulation' ? '从答题卡到分项给分' : tab === 'materials' ? '准备好每一道题的评分依据' : tab === 'history' ? '任务记录' : tab === 'audit' ? '可追溯的每一步' : '安全与配置'}</h1><p>{tab === 'work' ? '从答卷到证据清晰的评分建议，最终判断始终在你手中。' : '材料与操作记录保存在本机。'}</p></div><span className="outline-label"><ShieldCheck size={15} /> 正式成绩自动写入能力：未提供</span></div>
        {error && <div className="alert error" role="alert"><AlertTriangle size={18} /><span>{error}</span><button onClick={() => setError('')} aria-label="关闭错误"><X size={16} /></button></div>}
        {!session && <button className="button" onClick={() => void act(load)}>重新连接</button>}
        {session && <div hidden={tab !== 'materials'}><Materials /></div>}
        {session && <div hidden={tab !== 'simulation'}><Simulation /></div>}
        {tab === 'work' && <>
          <div className="demo-banner"><FlaskConical size={20} /><div><strong>{run?.mode === 'school' ? '已授权学校任务' : '当前为合成数据演示'}</strong><span>{run?.mode === 'school' ? '请确认当前账号和任务，仅在批准范围内使用。' : '无需登录或 API 密钥。可完整体验读取、生成与人工复核流程。'}</span></div><span className="tag">{run?.mode === 'school' ? '受限读取' : '数据不外发'}</span></div>
          <section className="task-card">
            <div className="section-kicker">01 <span>选择阅卷任务</span></div>
            <div className="task-row"><div className="task-icon"><FileText size={25} /></div><div className="task-select"><label htmlFor="task">课程与作业</label><select id="task" value={taskId} disabled={active || pending} onChange={e => { setTaskId(e.target.value); setMaterialKey(''); setMappingChecked(false); }}>{tasks.map(t => <option value={t.id} key={t.id}>{t.subject} / {t.title}</option>)}</select></div><div className="task-meta"><span>题目</span><strong>{currentTask?.question_id || '—'}</strong></div><div className="task-meta"><span>分值上限</span><strong>{currentTask?.max_score || '—'} 分</strong></div><button className="button primary" disabled={!session || pending || active || (!!materialKey && !mappingChecked)} onClick={start}><Play size={15} />开始读取</button></div>
            <div className="material-binding">
              <button className="button small" onClick={() => openTab('materials')}>导入 / 管理试卷与答案</button>
              {session?.school_enabled && currentTask?.source_site_id !== 'synthetic' && <>
                <label>评分依据<select value={materialKey} disabled={active || pending} onChange={e => { setMaterialKey(e.target.value); setMappingChecked(false); }}>
                  <option value="">使用任务原有评分依据</option>
                  {materials.filter(e => e.confirmed).flatMap(e => e.questions.map((q, i) => <option key={`${e.id}/${i}`} value={`${e.id}/${i}`}>{e.title} · {e.paper} · {q.number} · v{e.version}</option>))}
                </select></label>
                {materialKey && <label className="check-field"><input type="checkbox" checked={mappingChecked} onChange={e => setMappingChecked(e.target.checked)} />我已核对考试、卷别、小题及满分，与上方学校任务一致</label>}
              </>}
            </div>
          </section>
          <div className="stats">{[
            ['已读取答卷', stats.total, '份', FileText, 'blue'],
            ['等待复核', stats.waiting, '份', ListChecks, 'purple'],
            ['已本地复核', stats.reviewed, '份', CheckCheck, 'green'],
            ['需人工处理', stats.manual, '份', CircleHelp, 'amber'],
          ].map(([title, value, unit, Icon, color]) => { const I = Icon as typeof FileText; return <div className="stat" key={title as string}><div><span>{title as string}</span><strong>{value as number}<small>{unit as string}</small></strong></div><span className={`stat-icon ${color}`}><I size={21} /></span></div>; })}</div>
          {run && <div className="run-bar"><div>{active ? <LoaderCircle size={17} className="spin" /> : <span className="online-dot" />}<strong>{run.task.title}</strong><Badge status={run.status} /><small>{time(run.created_at)}</small></div><div>
            {run.status === 'awaiting_login' && <button className="button primary small" disabled={pending} onClick={() => action('confirm-login')}>已登录并核对账号 / 任务</button>}
            {run.status === 'ready' && <button className="button primary small" disabled={pending} onClick={() => setPreview(true)}><Eye size={15} />核对输入并生成</button>}
            {['paused', 'cancelled', 'review'].includes(run.status) && (!run.items.length || run.items.some(i => ['pending', 'error'].includes(i.status))) && <button className="button small" disabled={pending} onClick={() => run.items.length ? setPreview(true) : action('resume')}><RotateCcw size={14} />恢复未完成项</button>}
            {['reading', 'generating', 'awaiting_login', 'ready', 'paused'].includes(run.status) && <button className="button small" disabled={pending} onClick={() => action('cancel')}><Square size={12} />取消</button>}
          </div></div>}
          {run?.error_code && <div className="alert warning"><AlertTriangle size={17} />{errorText(run.error_code)}</div>}
          {run?.status === 'awaiting_login' && <div className="alert warning"><CircleHelp size={18} />请在已打开的专用浏览器中手动登录，进入授权任务页，核对账号后再确认读取。</div>}
          <section className="review-workspace">
            <div className="submissions"><div className="list-heading"><h2>答卷列表 <span>{stats.total}</span></h2><span className="section-kicker">02</span></div>
              <label className="search"><Search size={15} /><input aria-label="搜索答卷编号" placeholder="搜索答卷编号" value={query} onChange={e => setQuery(e.target.value)} /></label>
              <div className="filters">{[['all', '全部'], ['draft', '待复核'], ['manual', '需处理']].map(([key, title]) => <button className={filter === key ? 'selected' : ''} key={key} onClick={() => setFilter(key)}>{title}</button>)}</div>
              <div className="submission-list">{filtered.length ? filtered.map((i, index) => <button className={`submission ${selected === i.evidence.submission_id ? 'selected' : ''}`} key={i.evidence.submission_id} onClick={() => setSelected(i.evidence.submission_id)}><span className="paper-icon"><FileText size={19} /></span><span className="submission-text"><strong>答卷 {i.evidence.submission_id}</strong><span><Badge status={i.status} />{i.draft && <small>{score(i.draft.suggestion.score_suggestion)} / {run?.task.max_score} 分</small>}</span></span><ChevronRight size={15} /><span className="sr-only">第 {index + 1} 份</span></button>) : <div className="empty-list">{run?.items.length ? '没有匹配的答卷' : '读取完成后，答卷将在这里显示'}</div>}</div>
              <div className="list-footer"><LockKeyhole size={12} /> 证据与草稿仅存储在本机</div>
            </div>
            {run && item ? <ReviewPane key={`${run.id}/${item.evidence.submission_id}/${item.draft?.version}`} item={item} run={run} pending={pending || active}
              onReview={(action, scores, note) => void act(async () => {
                const next = await api<Run>(`/runs/${run.id}/submissions/${encodeURIComponent(item.evidence.submission_id)}/review`,
                  { expected_version: item.draft?.version, action, scores, note });
                setRun(next); setToast('复核结果已保存到本地，未提交至学校网站。');
              })} /> : <div className="empty-state"><div className="empty-illustration"><FileText size={46} /><span><Check size={18} /></span></div><h2>准备好开始一次轻松的复核</h2><p>选择上方任务并开始读取。<br />助手会把答卷、评分依据和建议放在一起。</p><div className="empty-steps"><span>读取答卷</span><ArrowRight size={14} /><span>生成草稿</span><ArrowRight size={14} /><span>教师复核</span></div></div>}
          </section>
          <div className="bottom-note"><ShieldCheck size={14} />本地草稿，尚未提交至学校网站。请在原网站核对并自行录入正式成绩。</div>
        </>}
        {tab === 'history' && <section className="panel"><h2>历史任务 <span className="muted">/ {runs.length}</span></h2>{runs.length ? runs.map(r => <button className="history-row" key={r.id} onClick={() => void act(async () => { setRun(await api(`/runs/${r.id}`)); setTab('work'); })}><FileText size={22} /><div><strong>{r.task.title}</strong><small>{time(r.created_at)} · {r.mode === 'demo' ? '合成演示' : '学校任务'}</small></div><Badge status={r.status} /><ChevronRight size={18} /></button>) : <p className="muted">还没有任务。先到阅卷工作台读取一组答卷。</p>}</section>}
        {tab === 'audit' && <section className="panel"><h2>当前任务的本地审计</h2><p className="muted">记录动作、时间与版本，不记录答卷正文、姓名、密钥或模型完整回复。</p>{!run ? <p>请先创建或打开任务。</p> : audit.map((event, index) => <div className="audit-row" key={index}><span className="audit-dot" /><time>{time(event.created_at)}</time><strong>{auditLabel(event.event)}</strong>{event.version && <span>v{event.version}</span>}{event.action && <Badge status={event.action} />}{event.code && <span>{errorText(event.code)}</span>}</div>)}</section>}
        {tab === 'settings' && <ModelSettings onSaved={async () => { const next = await api<Session>('/session'); setSession(next); }} />}
        {tab === 'settings' && <section className="panel settings-panel"><h2>默认关闭真实数据接入</h2><p>学校授权与站点适配由维护者管理；模型连接参数可在上方设置。</p><dl><dt>学校网站</dt><dd>{session?.school_enabled ? '已配置受限适配器' : '未启用 · 当前仅使用合成答卷'}</dd><dt>云端模型</dt><dd>{session?.cloud_enabled ? `${session.cloud_model} · ${session.cloud_region}` : '未启用 · 不向外部发送数据'}</dd><dt>草稿保留时间</dt><dd>{session?.retention_days ?? '—'} 天（启动及创建任务时清理到期记录）</dd><dt>存储方式</dt><dd>SQLite 加密载荷；真实模式密钥由系统凭据存储保护</dd><dt>浏览器能力</dt><dd>白名单读取、身份核验、证据提取；无成绩录入或提交接口</dd><dt>附件 / OCR</dt><dd>尚未开放，包含附件的答卷转人工处理</dd></dl><div className="alert warning"><CircleHelp size={18} />真实站点需完成页面适配和校方验收。详细配置步骤见项目 README 与站点适配文档。</div></section>}
      </div>
    </main>
    {toast && <div className="toast" role="status"><Check size={18} />{toast}</div>}
    {preview && run && <div className="modal-backdrop"><section className="modal" role="dialog" aria-modal="true" aria-labelledby="preview-title"><div className="modal-heading"><h2 id="preview-title">{run.mode === 'demo' ? '核对演示模型输入' : '确认本次外发内容'}</h2><button aria-label="关闭预览" onClick={() => setPreview(false)}><X size={20} /></button></div><p>{run.mode === 'demo' ? '以下数据只交给本地演示评分器，不会发送到云端。' : `仅发送题干、量规、脱敏答案行和临时匿名引用。目标：${session?.cloud_endpoint}；模型：${session?.cloud_model}；地域：${session?.cloud_region}。`}</p>
      {run.mode === 'school' && <div className="alert warning">保留条款：{session?.cloud_retention_terms}；训练条款：{session?.cloud_training_terms}。请逐份核对自由文本是否仍含个人信息；若有残留请取消并由维护者修正脱敏规则。</div>}
      <div className="preview-content">{run.items.filter(i => i.request && ['pending', 'error'].includes(i.status)).map(i => <details key={i.evidence.submission_id}><summary>答卷 {i.evidence.submission_id} · 查看实际输入</summary><pre>{JSON.stringify(i.request, null, 2)}</pre></details>)}</div>
      <div className="modal-actions"><button className="button" onClick={() => setPreview(false)}>返回核对</button><button className="button primary" disabled={pending || (run.mode === 'school' && !session?.cloud_enabled)} onClick={() => { setPreview(false); action('generate'); }}><Play size={15} />{run.mode === 'demo' ? '生成演示草稿' : '确认脱敏并允许本次生成'}</button></div></section></div>}
  </div>;
}

function ReviewPane({ item, run, pending, onReview }: { item: Item; run: Run; pending: boolean; onReview: (action: string, scores: Record<string, number>, note: string) => void }) {
  const draft = item.draft;
  const [scores, setScores] = useState<Record<string, number>>(Object.fromEntries(draft?.suggestion.criteria.map(c => [c.criterion_id, c.score]) || []));
  const [note, setNote] = useState(draft?.note || '');
  const [highlight, setHighlight] = useState<string[]>([]);
  const changed = draft?.suggestion.criteria.some(c => c.score !== scores[c.criterion_id]);
  const valid = run.task.criteria.every(c => Number.isFinite(scores[c.id]) && scores[c.id] >= 0 && scores[c.id] <= c.max_score);
  return <div className="review-pane"><div className="review-heading"><div><span className="section-kicker">03 <span>证据与评分建议</span></span><h2>答卷 {item.evidence.submission_id}<Badge status={item.status} /></h2></div><span className="draft-label">本地草稿 · 未提交</span></div>
    <div className="question"><span>题目 · {run.task.max_score} 分</span><p>{run.task.question}</p></div>
    <div className="evidence-score">
      <article className="answer-panel"><h3><FileText size={16} />作答原文<span>来源证据</span></h3>
        <div className="answer-lines">{item.evidence.answer ? item.evidence.answer.split('\n').map((line, i) => <div className={`answer-line ${highlight.includes(`L${i + 1}`) ? 'highlight' : ''}`} key={i}><span>L{i + 1}</span><p>{line || '（空行）'}</p></div>) : <div className="blank-answer">该答卷为空白，请教师自行判定。</div>}</div>
        <details className="source-details"><summary>查看来源与完整性记录</summary><dl><dt>捕获时间</dt><dd>{time(item.evidence.captured_at)}</dd><dt>来源定位</dt><dd>{item.evidence.source_locator}</dd><dt>内容哈希</dt><dd>{item.evidence.content_hash}</dd><dt>量规版本</dt><dd>{run.task.rubric_version}</dd><dt>解析质量</dt><dd>{item.evidence.quality}</dd></dl></details>
        <div className="rubric-box"><h4>评分依据</h4>{run.task.criteria.map(c => <p key={c.id}><strong>{c.title} · {c.max_score} 分</strong><span>{c.description}</span></p>)}</div>
      </article>
      <article className="score-panel"><h3><ListChecks size={16} />分项评分<span>需教师确认</span></h3>
        {draft ? <><div className="score-total"><div><span>建议总分</span><strong>{score(Object.values(scores).reduce((a, b) => a + b, 0))}<small> / {run.task.max_score}</small></strong></div><span className="badge draft">草稿 v{draft.version}</span></div>
          {draft.suggestion.criteria.map(c => { const rule = run.task.criteria.find(r => r.id === c.criterion_id)!; return <div className="criterion" key={c.criterion_id}><div><strong>{rule.title}</strong><label><input type="number" aria-label={`${rule.title}分数`} min="0" max={rule.max_score} step="0.1" disabled={pending} value={scores[c.criterion_id]} onChange={e => setScores({ ...scores, [c.criterion_id]: e.target.value === '' ? NaN : Number(e.target.value) })} /><span>/ {rule.max_score}</span></label></div><p>{c.reason}</p><div className="refs">{c.evidence_refs.map(ref => <button key={ref} onClick={() => setHighlight(c.evidence_refs)}><Eye size={11} />{ref}</button>)}</div></div>; })}
          <div className="uncertainties"><AlertTriangle size={15} /><div>{draft.suggestion.uncertainties.length ? draft.suggestion.uncertainties.map((u, i) => <p key={i}>{u}</p>) : <p>模型未标注疑点，仍需人工核对。</p>}</div></div>
        </> : <div className="ungraded"><CircleHelp size={28} /><h4>{item.status === 'manual' ? '这份答卷需要人工判定' : item.status === 'error' ? '未生成有效建议' : '尚未生成评分草稿'}</h4><p>{item.status === 'manual' ? '空白、缺页或附件内容不会交给模型强行评分。请到原网站核对。' : item.error_code ? errorText(item.error_code) : '请先核对模型输入，再开始生成。'}</p></div>}
      </article>
    </div>
    {draft && <div className="review-controls"><label htmlFor="review-note">复核备注 <span>仅保存在本地</span></label><textarea id="review-note" placeholder="记录调整理由、争议点或需要再次核对的内容…" value={note} maxLength={4000} onChange={e => setNote(e.target.value)} disabled={pending} /><div className="review-actions"><small>{draft.model} · {draft.prompt_version}</small><button className="button danger" disabled={pending} onClick={() => onReview('rejected', {}, note)}><X size={15} />拒绝建议</button><button className="button primary" disabled={pending || !valid} onClick={() => onReview(changed ? 'edited' : 'accepted', changed ? scores : {}, note)}><Check size={16} />{changed ? '保存修改并完成本地复核' : '接受建议并完成本地复核'}</button></div>{item.history.length > 0 && <details className="version-history"><summary>查看 {item.history.length} 个历史版本</summary>{item.history.map(d => <p key={d.version}>v{d.version} · {d.suggestion.score_suggestion} 分 · {labels[d.review_status] || '待复核'} · {d.note || '无备注'}</p>)}</details>}</div>}
  </div>;
}

function auditLabel(event: string) {
  return ({ run_created: '创建任务', capture_completed: '答卷读取完成', teacher_approved_generation: '教师确认生成',
    generation_started: '开始生成单份草稿', draft_created: '生成草稿', generation_completed: '本轮生成结束',
    local_review: '教师本地复核', teacher_cancelled: '教师取消任务', teacher_resumed: '教师恢复任务',
    run_paused: '任务暂停', recovered_after_restart: '重启后恢复检查', shutdown_paused: '退出时暂停',
    teacher_confirmed_identity: '教师确认账号与任务', generation_failed: '草稿生成失败' } as Record<string, string>)[event] || event;
}

createRoot(document.getElementById('root')!).render(<React.StrictMode><App /></React.StrictMode>);
