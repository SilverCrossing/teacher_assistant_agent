import { useEffect, useState } from 'react';
import { api, materialFile } from './api';

type Point = { id: string; title: string; description: string; max_score: number };
type Question = { number: string; prompt: string; answer: string; criteria: Point[] };
type Source = { id: string; name: string; role: string; size: number; text: string; warning: string; mime: string };
export type Exam = {
  id: string; title: string; subject: string; paper: string; version: number;
  confirmed: boolean; questions: Question[]; files: Source[];
};
const roles: Record<string, string> = { paper: '试卷题目', answer: '参考答案', rubric: '评分细则' };
const newQuestion = (): Question => ({
  number: '', prompt: '', answer: '',
  criteria: [{ id: crypto.randomUUID(), title: '评分点 1', description: '', max_score: 1 }],
});

export function Materials() {
  const [exams, setExams] = useState<Exam[]>([]);
  const [exam, setExam] = useState<Exam | null>(null);
  const [title, setTitle] = useState('');
  const [subject, setSubject] = useState('');
  const [paper, setPaper] = useState('A卷');
  const [role, setRole] = useState('paper');
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [preview, setPreview] = useState<{ data: string; name: string } | null>(null);

  useEffect(() => { api<Exam[]>('/materials').then(setExams).catch(e => setError(e.message)); }, []);
  // 未保存的编辑在刷新或关闭窗口前提醒教师。
  useEffect(() => {
    const warn = (e: BeforeUnloadEvent) => { if (dirty) { e.preventDefault(); e.returnValue = ''; } };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [dirty]);
  const operate = async (fn: () => Promise<void>) => {
    setBusy(true); setError(''); setMessage('');
    try { await fn(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  const accept = (next: Exam) => {
    setExam(next); setDirty(false);
    setExams(old => [next, ...old.filter(e => e.id !== next.id)]);
  };
  const change = (next: Exam) => { setExam({ ...next, confirmed: false }); setDirty(true); };
  const question = (index: number, next: Question) => {
    if (exam) change({ ...exam, questions: exam.questions.map((q, i) => i === index ? next : q) });
  };
  const save = (confirmed: boolean) => operate(async () => {
    if (!exam) return;
    const next = await api<Exam>(`/materials/${exam.id}`, {
      title: exam.title, subject: exam.subject, paper: exam.paper, expected_version: exam.version,
      questions: exam.questions, confirmed,
    });
    accept(next); setMessage(confirmed ? '已确认并保存此版本，可用于关联已授权的学校任务。' : '草稿已保存。');
  });
  const upload = (files: File[]) => operate(async () => {
    if (!exam) return;
    let current = exam;
    for (const file of files) {
      if (file.size > 15 * 1024 * 1024) throw new Error(`${file.name} 超过 15 MB，请拆分。`);
      const response = await materialFile(`/materials/${exam.id}/files`, file, current.version, role);
      current = await response.json() as Exam;
      accept(current); // 多文件上传部分成功时也保留新版本，便于继续上传。
    }
    setMessage('原件已保存在本机。请核对提取文字，并按题号整理下方内容。');
  });
  const openFile = (file: Source, view: boolean) => operate(async () => {
    if (!exam) return;
    const response = await materialFile(`/materials/${exam.id}/files/${file.id}`);
    const blob = await response.blob();
    if (view && file.mime.startsWith('image/')) {
      const reader = new FileReader();
      reader.onload = () => setPreview({ data: String(reader.result), name: file.name });
      reader.readAsDataURL(blob);
    } else {
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url; link.download = file.name; link.click();
      setTimeout(() => URL.revokeObjectURL(url), 10000);
      setMessage('原件已下载，可使用本机的 PDF 或 Word 阅读器打开核对。');
    }
  });
  return <div className="materials">
    <section className="panel">
      <h2>试卷与答案库</h2>
      <p className="muted">先导入题目和参考答案，再按小题整理评分依据。资料只保存在本机，导入不会调用云端模型。</p>
      {error && <div className="alert error" role="alert">{error}</div>}
      {message && <div className="alert success" role="status">{message}</div>}
      <fieldset disabled={busy}>
        <form className="exam-create" onSubmit={e => { e.preventDefault(); void operate(async () => {
          if (dirty && !window.confirm('当前内容尚未保存，是否放弃编辑并新建试卷？')) return;
          accept(await api<Exam>('/materials', { title, subject, paper }));
          setTitle(''); setMessage('试卷已建立，请上传对应材料。');
        }); }}>
          <label>考试名称<input required maxLength={160} value={title} onChange={e => setTitle(e.target.value)} placeholder="例如：高一化学第一次月考" /></label>
          <label>学科<input required maxLength={80} value={subject} onChange={e => setSubject(e.target.value)} placeholder="例如：化学" /></label>
          <label>卷别<input required maxLength={80} value={paper} onChange={e => setPaper(e.target.value)} placeholder="A卷 / B卷 / 通用" /></label>
          <button className="button primary">新建试卷</button>
        </form>
        <label>打开已有试卷<select value={exam?.id || ''} onChange={e => {
          const next = exams.find(x => x.id === e.target.value);
          if (next && (!dirty || window.confirm('当前内容尚未保存，是否放弃编辑并切换？'))) {
            accept(next); setPreview(null); setMessage('');
          }
        }}><option value="" disabled>请选择试卷</option>{exams.map(e => <option key={e.id} value={e.id}>{e.title} · {e.paper} · v{e.version} · {e.confirmed ? '已确认' : '待核对'}</option>)}</select></label>
      </fieldset>
    </section>
    {exam && <section className="panel">
      <h2>{exam.title} <span className="muted">v{exam.version} · {dirty ? '有未保存修改' : exam.confirmed ? '已确认' : '待核对'}</span></h2>
      <fieldset disabled={busy}>
        <div className="exam-create">
          <label>考试名称<input value={exam.title} maxLength={160} onChange={e => change({ ...exam, title: e.target.value })} /></label>
          <label>学科<input value={exam.subject} maxLength={80} onChange={e => change({ ...exam, subject: e.target.value })} /></label>
          <label>卷别<input value={exam.paper} maxLength={80} onChange={e => change({ ...exam, paper: e.target.value })} /></label>
        </div>
        <h3>1. 上传原件</h3>
        <p className="muted">支持 PDF（最多 100 页）、DOCX、TXT、MD、PNG、JPG；每个文件最多 15 MB，每份试卷最多 30 个文件。扫描 PDF 和图片尚不支持自动 OCR，公式需人工核对。</p>
        <div className="upload-row">
          <label>材料类型<select value={role} onChange={e => setRole(e.target.value)}>{Object.entries(roles).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
          <label>选择文件（可多选）<input type="file" multiple accept=".pdf,.docx,.txt,.md,.png,.jpg,.jpeg" disabled={dirty}
            onChange={e => { const files = Array.from(e.target.files || []); e.target.value = ''; if (files.length) void upload(files); }} /></label>
        </div>
        {dirty && <p className="muted">请先保存当前编辑，再继续上传原件。</p>}
        {exam.files.length === 0 && <p className="muted">尚未上传原件，也可以直接在下方录入题目与答案。</p>}
        {exam.files.map(file => <details key={file.id} className="source-file">
          <summary>{roles[file.role]} · {file.name} · {Math.ceil(file.size / 1024)} KB</summary>
          <div className="settings-actions">
            {file.mime.startsWith('image/') && <button className="button" onClick={() => void openFile(file, true)}>查看原图</button>}
            <button className="button" onClick={() => void openFile(file, false)}>下载原件</button>
          </div>
          {file.warning && <p className="alert warning">{file.warning}</p>}
          <label>提取文字（供复制整理，不会自动作为评分依据）<textarea readOnly rows={8} value={file.text || '没有可提取的文字，请查看原件并手动录入。'} /></label>
        </details>)}
        {preview && <div className="source-preview"><button className="button small" onClick={() => setPreview(null)}>关闭原图</button><p>{preview.name}</p><img src={preview.data} alt={preview.name} /></div>}
        <h3>2. 按题号整理</h3>
        <p className="muted">建议每个独立评分的小题建一条，例如 15(1)ii-2。题干应包含作答要求；参考答案保留上下标、反应条件和等价答案。</p>
        {exam.questions.map((q, i) => <article className="material-question" key={i}>
          <div className="material-question-head"><strong>第 {i + 1} 条 · 共 {q.criteria.reduce((s, p) => s + (Number(p.max_score) || 0), 0)} 分</strong>
            <button className="button small danger" onClick={() => {
              if (window.confirm('从当前编辑中移除此题？保存后才会生效。')) change({ ...exam, questions: exam.questions.filter((_, n) => n !== i) });
            }}>移除此题</button></div>
          <label>题号 / 小题号<input value={q.number} maxLength={80} placeholder="例如 15(1)ii-2" onChange={e => question(i, { ...q, number: e.target.value })} /></label>
          <label>完整题干与作答要求<textarea rows={4} maxLength={16000} value={q.prompt} onChange={e => question(i, { ...q, prompt: e.target.value })} /></label>
          <label>参考答案 / 可接受的等价答案<textarea rows={4} maxLength={16000} value={q.answer} onChange={e => question(i, { ...q, answer: e.target.value })} /></label>
          {q.criteria.map((point, j) => <div className="material-point" key={point.id}>
            <label>评分点名称<input maxLength={200} value={point.title} onChange={e => question(i, { ...q, criteria: q.criteria.map((p, n) => n === j ? { ...p, title: e.target.value } : p) })} /></label>
            <label>满分<input type="number" min="0.01" max="1000" step="0.01" value={point.max_score || ''} onChange={e => question(i, { ...q, criteria: q.criteria.map((p, n) => n === j ? { ...p, max_score: Number(e.target.value) } : p) })} /></label>
            <label>给分 / 扣分规则<textarea rows={2} maxLength={2000} value={point.description} onChange={e => question(i, { ...q, criteria: q.criteria.map((p, n) => n === j ? { ...p, description: e.target.value } : p) })} /></label>
            <button className="button small" disabled={q.criteria.length <= 1} onClick={() => question(i, { ...q, criteria: q.criteria.filter((_, n) => n !== j) })}>移除评分点</button>
          </div>)}
          <button className="button small" onClick={() => question(i, { ...q, criteria: [...q.criteria, { id: crypto.randomUUID(), title: `评分点 ${q.criteria.length + 1}`, description: '', max_score: 1 }] })}>添加评分点</button>
        </article>)}
        <button className="button" onClick={() => change({ ...exam, questions: [...exam.questions, newQuestion()] })}>添加小题</button>
        <div className="settings-actions">
          <button className="button" onClick={() => void save(false)}>保存草稿</button>
          <button className="button primary" disabled={!exam.questions.length} onClick={() => void save(true)}>已核对题干、答案和评分点，确认保存</button>
        </div>
        <p className="muted">修改或补充原件后需重新确认。已有阅卷任务保留创建时的版本，后续修改不会改变历史评分依据。</p>
      </fieldset>
      {busy && <p role="status">正在处理，请稍候…</p>}
    </section>}
  </div>;
}
