import { useEffect, useState } from 'react';
import { api } from './api';
import type { Exam } from './Materials';
import type { Criterion } from './types';

type Source = { id: string; title: string; paper: string; version: number };
type Card = {
  id: string; image_text: string; label: string; question_number: string; status: string;
  draft: { transcript: string; scores: Record<string, number> | null; reason: string } | null;
  review: { scores: Record<string, number>; total: number; note: string } | null;
  history: { total: number; note: string; created_at: string }[];
};
type Session = {
  id: string; version: number; source: Source; builtin: boolean; cards: Card[];
  question: { number: string; prompt: string; answer: string; criteria: Criterion[] };
};
type RecordItem = { id: string; source: Source; reviewed: number; created_at: string };
const status: Record<string, string> = { unread: '未读取', draft: '待复核', manual: '需人工给分', reviewed: '已本地确认' };

export function Simulation() {
  const [session, setSession] = useState<Session | null>(null);
  const [exams, setExams] = useState<Exam[]>([]);
  const [records, setRecords] = useState<RecordItem[]>([]);
  const [binding, setBinding] = useState('');
  const [mapping, setMapping] = useState(false);
  const [selected, setSelected] = useState('SIM-001');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [editing, setEditing] = useState(false);
  const mayLeave = () => !editing || window.confirm('当前答卷有未保存的修改，是否放弃并切换？');
  const act = async (fn: () => Promise<void>) => {
    setBusy(true); setError(''); setMessage('');
    try { await fn(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  const refresh = async () => {
    const [e, r] = await Promise.all([api<Exam[]>('/materials'), api<RecordItem[]>('/simulations')]);
    setExams(e.filter(x => x.confirmed)); setRecords(r);
  };
  useEffect(() => { void act(refresh); }, []);
  useEffect(() => {
    const warn = (e: BeforeUnloadEvent) => { if (editing) { e.preventDefault(); e.returnValue = ''; } };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [editing]);
  const card = session?.cards.find(c => c.id === selected);
  const total = session?.question.criteria.reduce((sum, c) => sum + c.max_score, 0) || 0;
  const reviewed = session?.cards.filter(c => c.status === 'reviewed').length || 0;
  return <div className="simulation">
    <div className="alert warning">模拟学校批卷页 · 合成答题卡 · 不连接学校、不调用云端模型、不提交正式成绩。这里只验证答案关联和给分流程。</div>
    {error && <div className="alert error" role="alert">{error}</div>}
    {message && <div className="alert success" role="status">{message}</div>}
    <section className="panel sim-setup">
      <h2>准备一轮模拟阅卷</h2>
      <div className="sim-setup-row">
        <label>关联的答案与评分规则<select value={binding} disabled={busy} onChange={e => { setBinding(e.target.value); setMapping(false); }}>
          <option value="">内置化学示例 · 15(2) · 4 分</option>
          {exams.flatMap(e => e.questions.map((q, i) => <option key={`${e.id}/${i}`} value={`${e.id}/${i}`}>{e.title} · {e.paper} · {q.number} · v{e.version}</option>))}
        </select></label>
        <button className="button" disabled={busy} onClick={() => void act(refresh)}>刷新答案库</button>
        <button className="button primary" disabled={busy || (!!binding && !mapping)} onClick={() => void act(async () => {
          if (!mayLeave()) return;
          const [id, index] = binding.split('/');
          const exam = exams.find(e => e.id === id);
          const result = await api<Session>('/simulations', exam ? {
            material_id: id, material_version: exam.version,
            question_number: exam.questions[Number(index)].number, mapping_confirmed: mapping,
          } : {});
          setSession(result); setEditing(false); setSelected(result.cards[0].id); await refresh();
        })}>开始新一轮模拟</button>
      </div>
      {binding && <label className="check-field"><input type="checkbox" checked={mapping} onChange={e => setMapping(e.target.checked)} />我已核对小题映射。本轮仍展示合成化学答题卡，自定义答案仅测试关联与人工给分。</label>}
      <label>继续之前的模拟<select value={session?.id || ''} disabled={busy} onChange={e => void act(async () => {
        if (!mayLeave()) return;
        const result = await api<Session>(`/simulations/${e.target.value}`);
        setSession(result); setEditing(false); setSelected(result.cards[0].id);
      })}><option value="" disabled>选择历史模拟记录</option>{records.map(r => <option key={r.id} value={r.id}>{r.source.title} · {new Date(r.created_at).toLocaleString('zh-CN')} · 已确认 {r.reviewed} 份</option>)}</select></label>
    </section>
    {session && card ? <>
      <div className="sim-school-header"><div><strong>{session.source.title}</strong><span>{session.source.paper} · 第 {session.question.number} 题 · 满分 {total} 分</span></div><strong>已确认 {reviewed} / {session.cards.length}</strong></div>
      <div className="sim-layout">
        <nav className="sim-cards" aria-label="模拟答卷列表">{session.cards.map((c, i) => <button key={c.id} disabled={busy}
          className={selected === c.id ? 'selected' : ''} onClick={() => { if (selected !== c.id && mayLeave()) { setSelected(c.id); setEditing(false); } }}>
          <strong>{i + 1}</strong><span>{c.id}</span><small>{status[c.status]}</small>{c.review && <b>{c.review.total} 分</b>}
        </button>)}</nav>
        <SimulationCard key={`${session.id}/${card.id}/${session.version}`} session={session} card={card} busy={busy} onEdit={() => setEditing(true)}
          onAction={(kind, body) => void act(async () => {
            const result = await api<Session>(`/simulations/${session.id}/cards/${card.id}/${kind}`, { expected_version: session.version, ...body });
            setSession(result); setEditing(false);
            setMessage(kind === 'review' ? '本份给分已保存到本地。可在左侧切换下一份；不会自动提交学校网站。' : '已关联冻结的答案版本，请核对各评分点。');
            await refresh();
          })} />
      </div>
    </> : <section className="panel"><p>点击“开始新一轮模拟”，体验答题卡读取、答案关联和分项给分。无需学校网址或 API 密钥。</p></section>}
  </div>;
}

function SimulationCard({ session, card, busy, onAction, onEdit }: {
  session: Session; card: Card; busy: boolean;
  onAction: (kind: string, body: Record<string, unknown>) => void;
  onEdit: () => void;
}) {
  const [transcript, setTranscript] = useState(card.draft?.transcript ?? '');
  const [read, setRead] = useState(!!card.draft);
  const [checked, setChecked] = useState(false);
  const [scores, setScores] = useState<Record<string, string>>(Object.fromEntries(session.question.criteria.map(c =>
    [c.id, String(card.review?.scores[c.id] ?? card.draft?.scores?.[c.id] ?? '')])));
  const [note, setNote] = useState(card.review?.note || '');
  const rules = session.question.criteria;
  const valid = rules.every(c => scores[c.id] !== '' && Number.isFinite(Number(scores[c.id])) && Number(scores[c.id]) >= 0 && Number(scores[c.id]) <= c.max_score);
  const total = rules.reduce((s, c) => s + (Number(scores[c.id]) || 0), 0);
  const changed = transcript !== (card.draft?.transcript ?? '');
  return <>
    <section className="sim-paper-panel">
      <div className="sim-paper-title"><strong>答题卡 {card.id}</strong><span>{card.label}</span></div>
      <div className="sim-paper">
        <svg viewBox="0 0 800 310" role="img" aria-label={`合成答题卡 ${card.id}`}>
          <rect x="1" y="1" width="798" height="308" fill="#fffef8" stroke="#b3b3af" />
          <text x="40" y="48" fontSize="19" fill="#555">第 II 卷　非选择题　（合成样例）</text>
          <text x="40" y="100" fontSize="23" fill="#333">{card.question_number}</text>
          <line x1="40" y1="210" x2="755" y2="210" stroke="#777" />
          <text x="55" y="193" fontSize="23" fill="#303943" fontFamily="KaiTi, serif">{card.image_text}</text>
          <text x="40" y="280" fontSize="14" fill="#999">答卷编号：{card.id}　｜　模拟图像，不代表真实手写识别效果</text>
        </svg>
      </div>
      <div className="sim-transcript">
        <h3>1. 获取并核对作答</h3>
        <p className="muted">此处用预置文字模拟“获取答题卡后的转写结果”，没有进行 OCR。请核对有效作答，涂改和空白由教师判定。</p>
        <button className="button" disabled={busy} onClick={() => { setRead(true); setTranscript(card.image_text); setChecked(false); onEdit(); }}>读取这份模拟答卷</button>
        <label>有效作答文字<textarea rows={5} value={transcript} disabled={!read || busy} onChange={e => { setTranscript(e.target.value); setChecked(false); onEdit(); }} /></label>
        <label className="check-field"><input type="checkbox" disabled={!read || busy} checked={checked} onChange={e => setChecked(e.target.checked)} />我已对照答题卡核对有效作答（包括空白、涂改）</label>
        <button className="button primary" disabled={!read || !checked || busy} onClick={() => onAction('draft', { transcript, transcription_confirmed: checked })}>关联答案并生成评分草稿</button>
        {changed && card.draft && <p className="alert warning">作答文字已修改，请重新生成草稿后再给分。</p>}
      </div>
    </section>
    <aside className="sim-marking">
      <h3>2. 核对答案与评分依据</h3>
      <p className="sim-source">{session.source.title} · {session.source.paper}<br />第 {session.question.number} 题 · 答案版本 v{session.source.version}（本轮已冻结）</p>
      <div className="sim-reference"><strong>题干</strong><p>{session.question.prompt}</p><strong>参考答案</strong><p>{session.question.answer}</p></div>
      <h3>3. 分项给分</h3>
      {card.draft && <div className="alert warning">{card.draft.reason}{!session.builtin && ' 自定义规则尚未接入 AI 自动评分。'}</div>}
      {rules.map(c => <div className="sim-rule" key={c.id}><label>{c.title}<span>{c.max_score} 分</span><input type="number" aria-label={`${c.title}得分`}
        min="0" max={c.max_score} step="0.01" placeholder="待给分" disabled={!card.draft || changed || busy} value={scores[c.id]}
        onChange={e => { setScores({ ...scores, [c.id]: e.target.value }); onEdit(); }} /></label><p>{c.description}</p></div>)}
      <div className="sim-total">本地总分 <strong>{Math.round(total * 100) / 100}</strong> / {rules.reduce((s, c) => s + c.max_score, 0)}<small>{valid ? '请教师最终确认' : '部分评分点尚未给分'}</small></div>
      <label>给分备注<textarea rows={3} value={note} maxLength={4000} disabled={busy} onChange={e => { setNote(e.target.value); onEdit(); }} /></label>
      <button className="button primary" disabled={!card.draft || changed || !valid || busy} onClick={() => onAction('review', {
        scores: Object.fromEntries(Object.entries(scores).map(([k, v]) => [k, Number(v)])), note,
      })}>确认本份给分（仅本地）</button>
      {card.review && <p className="alert success">已本地确认：{card.review.total} 分</p>}
      {card.history.length > 0 && <details><summary>历史给分记录（{card.history.length}）</summary>{card.history.map((h, i) => <p key={i}>{h.total} 分 · {h.note || '无备注'} · {new Date(h.created_at).toLocaleString('zh-CN')}</p>)}</details>}
    </aside>
  </>;
}
