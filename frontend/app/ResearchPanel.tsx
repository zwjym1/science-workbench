'use client';

import { useEffect, useState } from 'react';

type Dimension = 'demand' | 'evidence' | 'explainability' | 'freshness';
type Topic = {id: string; title: string; status: string; favorite: boolean; is_demo: boolean; engine: string; category: string; question: string; support_count: number; coverage: {videos: number; comments: number; unique_comments: number; searches: number}; evidence: {kind: string; video_id: string; comment_id?: string; text: string; source_url?: string; collected_at: string}[]; uncertainty: string; gap: string; score: number; scores: Record<Dimension, {value: number; reason: string}>};
type Job = {id: string; status: string; stage: string; error?: string; engine: string; is_demo: boolean};
const dimensions: Record<Dimension, string> = {demand: '观众需求', evidence: '证据支持', explainability: '解释与制作适配', freshness: '采集时效'};
const labels: Record<string, string> = {queued: '排队中', pending: '等待处理', running: '处理中', completed: '已完成', succeeded: '已完成', failed: '失败', candidate: '候选', approved: '已批准', rejected: '已拒绝', merged: '已合并'};
async function request(path: string, options?: RequestInit) {
  const response = await fetch(`/api${path}`, {...options, credentials: 'same-origin', signal: options?.signal ? AbortSignal.any([options.signal, AbortSignal.timeout(30000)]) : AbortSignal.timeout(30000), headers: {'Content-Type': 'application/json'}});
  const body = await response.json().catch(() => null);
  if (!response.ok) throw new Error(typeof body?.detail === 'string' ? body.detail : JSON.stringify(body?.detail || `请求失败（${response.status}）`));
  return body;
}

export default function ResearchPanel() {
  const [demo, setDemo] = useState(false);
  const [engine, setEngine] = useState('rules');
  const [config, setConfig] = useState<{model_available: boolean; provider?: string; model?: string} | null>(null);
  const [weights, setWeights] = useState<Record<Dimension, number>>({demand: 35, evidence: 25, explainability: 25, freshness: 15});
  const [topics, setTopics] = useState<Topic[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [status, setStatus] = useState('all');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const [mergeTarget, setMergeTarget] = useState('');
  useEffect(() => {request('/analysis-config').then(setConfig).catch(e => setError(e.message));}, []);
  useEffect(() => {
    const controller = new AbortController();
    async function refresh() {
      try {
        const [t, j] = await Promise.all([request(`/topics?is_demo=${demo}`, {signal: controller.signal}), request('/analysis-jobs', {signal: controller.signal})]);
        if (!controller.signal.aborted) {setTopics(t.items || []); setJobs((j.items || []).filter((job: Job) => job.is_demo === demo));}
      } catch (e) {if (!controller.signal.aborted) setError(e instanceof Error ? e.message : '读取分析结果失败');}
    }
    refresh();
    const timer = setInterval(refresh, 4000);
    return () => {controller.abort(); clearInterval(timer);};
  }, [demo, refreshKey]);
  async function mutate(path: string, method: string, data?: unknown) {
    setBusy(true); setError(''); setNotice('');
    try {await request(path, {method, ...(data === undefined ? {} : {body: JSON.stringify(data)})}); setRefreshKey(k => k + 1); return true;}
    catch (e) {setError(e instanceof Error ? e.message : '操作失败'); return false;}
    finally {setBusy(false);}
  }
  const selectedTopics = topics.filter(t => selected.includes(t.id));
  const visible = topics.filter(t => status === 'all' || (status === 'favorite' ? t.favorite : t.status === status));
  const weightTotal = Object.values(weights).reduce((a, b) => a + b, 0);
  return <div className="research">
    <section className="panel research-settings"><div className="panel-heading"><h2>需求分析与选题发现</h2><span className={demo ? 'demo-badge' : 'real-badge'}>{demo ? '模拟数据模式' : '真实导入模式'}</span></div>
      <div className="research-controls"><label>资料范围<select value={demo ? 'demo' : 'real'} disabled={busy} onChange={e => {setDemo(e.target.value === 'demo'); setTopics([]); setJobs([]); setSelected([]); setMergeTarget(''); setError(''); setNotice('');}}><option value="real">真实导入数据</option><option value="demo">模拟数据（仅验证流程）</option></select></label>
      <label>分析方式<select value={engine} onChange={e => setEngine(e.target.value)}><option value="rules">规则基线：文本归一与问题归组</option><option value="model" disabled={!config?.model_available}>已配置模型：语义需求分析</option></select></label></div>
      <p className="research-description muted">{config?.model_available ? `服务端模型：${config.provider || ''} / ${config.model || ''}。` : '尚无可用模型配置，模型分析不可用；请在服务端配置密钥，勿在页面输入。'} 规则基线不等同于 AI 语义聚类。模拟资料不会混入真实选题。</p>
      <fieldset className="weights"><legend>评分权重（合计 100）</legend>{(Object.keys(dimensions) as Dimension[]).map(key => <label key={key}>{dimensions[key]}<input type="number" min="0" max="100" step="1" value={weights[key]} onChange={e => setWeights(w => ({...w, [key]: Math.max(0, Math.min(100, Number(e.target.value) || 0))}))} /></label>)}</fieldset>
      <div className="research-actions"><p className="muted">评分仅用于启发式排序，不是播放量预测。当前权重合计：{weightTotal}</p><button className="primary" disabled={busy || weightTotal !== 100 || (engine === 'model' && !config?.model_available)} onClick={async () => {if (await mutate('/analysis-jobs', 'POST', {is_demo: demo, engine, weights})) setNotice('分析任务已提交。可在下方查看后台处理进度。');}}>开始分析 →</button></div>
    </section>
    {error && <p className="error banner" role="alert">{error}</p>}{notice && <p className="success banner" role="status">{notice}</p>}
    <section className="panel"><div className="panel-heading"><h2>后台任务</h2><button className="text-button" onClick={() => setRefreshKey(k => k + 1)}>刷新</button></div>{jobs.length ? jobs.slice(0, 8).map(j => <article className="task" key={j.id}><div className="task-title"><strong>{labels[j.status] || j.status} · {j.engine === 'model' ? '模型分析' : '规则基线'}</strong>{j.status === 'failed' && <button disabled={busy} className="text-button" onClick={() => mutate(`/analysis-jobs/${j.id}/retry`, 'POST')}>重试</button>}</div><p>{j.stage}</p><code>{j.id}</code>{j.error && <p className="error">{j.error}</p>}</article>) : <p className="research-description muted">此模式暂无任务。先导入相应数据，再开始分析。</p>}</section>
    <section className="panel"><div className="panel-heading"><h2>选题卡片 <span className="count">{visible.length}</span></h2><label>筛选 <select value={status} onChange={e => setStatus(e.target.value)}><option value="all">全部</option><option value="candidate">候选</option><option value="approved">已批准</option><option value="rejected">已拒绝</option><option value="favorite">已收藏</option><option value="merged">已合并</option></select></label></div>
    <p className="research-description muted">选择 2–3 张卡片比较；相同或相近需求可手动合并，原始来源继续保留。未发现需求时不会编造选题。</p>
    {selectedTopics.length >= 2 && <div className="comparison"><h3>选题比较</h3><div className="comparison-grid">{selectedTopics.map(t => <article key={t.id}><strong>{t.title}</strong><p>排序分 {Number(t.score).toFixed(1)}</p>{(Object.keys(dimensions) as Dimension[]).map(key => <p key={key}>{dimensions[key]}：{t.scores[key]?.value ?? '未知'}<small>{t.scores[key]?.reason}</small></p>)}<p>不确定性：{t.uncertainty}</p></article>)}</div><div className="research-controls"><label>合并后保留的目标选题<select value={mergeTarget} disabled={busy} onChange={e => setMergeTarget(e.target.value)}><option value="">请选择目标</option>{selectedTopics.filter(t => t.status !== 'merged').map(t => <option value={t.id} key={t.id}>{t.title}</option>)}</select></label><button className="secondary" disabled={busy || selectedTopics.length !== 2 || !mergeTarget || !selected.includes(mergeTarget) || selectedTopics.some(t => t.status === 'merged')} onClick={async () => {const source = selectedTopics.find(t => t.id !== mergeTarget); if (source && await mutate(`/topics/${source.id}/merge`, 'POST', {target_id: mergeTarget})) {setSelected([]); setMergeTarget(''); setNotice('选题已合并。');}}}>合并两项</button></div></div>}
    <div className="topic-grid">{visible.map(t => <article className="topic-card" key={t.id}><div className="task-title"><span className={t.is_demo ? 'demo-badge' : 'real-badge'}>{t.is_demo ? '模拟资料' : '真实导入资料'} · {labels[t.status] || t.status}</span><label className="checkbox"><input type="checkbox" checked={selected.includes(t.id)} disabled={!selected.includes(t.id) && selected.length >= 3} onChange={e => {setSelected(ids => e.target.checked ? [...ids, t.id] : ids.filter(id => id !== t.id)); setMergeTarget('');}} />比较</label></div><h3>{t.title}</h3><p className="topic-question">{t.question}</p><p className="muted">{t.category} · {t.engine === 'model' ? '模型分析' : '规则基线'} · 排序分 {Number(t.score).toFixed(1)}</p><p>去重需求表达 {t.support_count} 项 · 覆盖 {t.coverage?.videos ?? 0} 条视频 / {t.coverage?.comments ?? 0} 条评论 / 去重后 {t.coverage?.unique_comments ?? 0} 条 / {t.coverage?.searches ?? 0} 个搜索词</p><p><strong>内容缺口：</strong>{t.gap}</p><p><strong>不确定性：</strong>{t.uncertainty}</p><details><summary>查看评分依据与原文证据（{t.evidence.length}）</summary>{(Object.keys(dimensions) as Dimension[]).map(key => <p key={key}><strong>{dimensions[key]}：{t.scores[key]?.value ?? '未知'}</strong><br />{t.scores[key]?.reason}</p>)}{t.evidence.map((e, index) => <blockquote key={`${e.comment_id || e.video_id}-${index}`}><span>{e.kind === 'comment' ? '评论原文' : '相关搜索'}</span><p>{e.text}</p><small>视频 {e.video_id} · 采集于 {e.collected_at ? new Date(e.collected_at).toLocaleString('zh-CN') : '未知'}</small>{e.source_url && /^https?:\/\//i.test(e.source_url) && <a target="_blank" rel="noreferrer" href={e.source_url}>查看来源 ↗</a>}</blockquote>)}</details><div className="topic-actions"><button disabled={busy} className="text-button" onClick={() => mutate(`/topics/${t.id}`, 'PATCH', {favorite: !t.favorite})}>{t.favorite ? '★ 已收藏' : '☆ 收藏'}</button>{t.status !== 'merged' && <><button disabled={busy || t.status === 'approved'} className="text-button" onClick={() => mutate(`/topics/${t.id}`, 'PATCH', {status: 'approved'})}>批准</button><button disabled={busy || t.status === 'rejected'} className="text-button" onClick={() => mutate(`/topics/${t.id}`, 'PATCH', {status: 'rejected'})}>拒绝</button>{t.status !== 'candidate' && <button disabled={busy} className="text-button" onClick={() => mutate(`/topics/${t.id}`, 'PATCH', {status: 'candidate'})}>恢复候选</button>}</>}</div></article>)}</div>{!visible.length && <div className="empty compact"><h3>暂无匹配选题</h3><p>{demo ? '当前为模拟模式，请先在数据导入页导入明确标注的示例资料，再运行分析。' : '请先导入真实视频、评论和搜索词，或显式切换模拟模式验证流程。'}</p></div>}</section>
  </div>;
}
