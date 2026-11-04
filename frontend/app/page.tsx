'use client';

import { FormEvent, useEffect, useState } from 'react';
import ResearchPanel from './ResearchPanel';

type Video = {id: string; title: string; platform: string; external_id: string; source_url?: string; comments_count?: number; is_demo?: boolean; collected_at?: string};
type ImportTask = {id: string; status: string; result?: unknown; error?: unknown; is_demo?: boolean; created_at?: string};
const sample = JSON.stringify({"adapter":"standard-json","is_demo":true,"data":{"videos":[{"platform":"demo","external_id":"demo-sky-001","title":"【模拟数据】天空为什么是蓝色？","source_url":"https://example.com/demo/sky","collected_at":"2026-10-20T08:00:00+08:00","published_at":null,"content":"这是测试采集接口的虚构内容，不来自抖音。","metrics":{"views":null,"likes":null},"comments":[{"external_id":"demo-c1","text":"【模拟评论】那日落为什么是红色？","likes":null},{"external_id":"demo-c2","text":"【模拟评论】能用三维动画解释散射吗？","likes":null}],"related_searches":["【模拟搜索】瑞利散射"],"tags":["模拟数据","光学"]}]}}, null, 2);

const csvColumns = 'platform,external_id,title,source_url,collected_at,content,published_at,comment_id,comment_text,comment_likes,related_searches,tags,views,likes';
const csvSample = csvColumns + '\n' + [
  ['demo', 'demo-sky-csv-001', '【模拟数据】天空为什么是蓝色？', 'https://example.com/demo/sky-csv', '2026-10-20T08:00:00+08:00', '【模拟内容】这是接口测试资料，不来自真实平台。', '', 'demo-csv-c1', '【模拟评论】那日落为什么是红色？', '', '【模拟搜索】瑞利散射|【模拟搜索】蓝天原理', '模拟数据|光学', '', ''],
  ['demo', 'demo-sky-csv-001', '【模拟数据】天空为什么是蓝色？', 'https://example.com/demo/sky-csv', '2026-10-20T08:00:00+08:00', '【模拟内容】这是接口测试资料，不来自真实平台。', '', 'demo-csv-c2', '【模拟评论】能用三维动画解释散射吗？', '', '【模拟搜索】瑞利散射|【模拟搜索】蓝天原理', '模拟数据|光学', '', ''],
].map(row => row.map(value => '"' + value.replaceAll('"', '""') + '"').join(',')).join('\n');

async function api(path: string, options?: RequestInit) {
  const response = await fetch(`/api${path}`, {credentials: 'same-origin', signal: AbortSignal.timeout(30000), ...options, headers: {'Content-Type': 'application/json', ...options?.headers}});
  const body = await response.json().catch(() => null);
  if (!response.ok) throw new Error(typeof body?.detail === 'string' ? body.detail : body?.detail ? JSON.stringify(body.detail) : `请求失败（${response.status}）`);
  return body;
}
const pretty = (value: unknown) => typeof value === 'string' ? value : JSON.stringify(value, null, 2);
const statusLabel: Record<string, string> = {queued: '排队中', pending: '等待处理', running: '处理中', processing: '处理中', completed: '已完成', succeeded: '已完成', failed: '失败'};

export default function Home() {
  const [auth, setAuth] = useState<'checking' | 'guest' | 'signed'>('checking');
  const [password, setPassword] = useState('');
  const [videos, setVideos] = useState<Video[]>([]);
  const [tasks, setTasks] = useState<ImportTask[]>([]);
  const [data, setData] = useState('');
  const [importFormat, setImportFormat] = useState<'json' | 'csv'>('json');
  const [demo, setDemo] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [query, setQuery] = useState('');
  const [detail, setDetail] = useState<Record<string, {comments: {id: string; text: string; likes: number | null}[]; snapshots: unknown[]}>>({});
  const [demoOnly, setDemoOnly] = useState(false);
  const [tab, setTab] = useState<'library' | 'imports' | 'research'>('library');

  async function refresh() {
    const [v, t] = await Promise.all([api('/videos'), api('/imports')]);
    setVideos(Array.isArray(v) ? v : v.items || []);
    setTasks(Array.isArray(t) ? t : t.items || []);
  }
  useEffect(() => { api('/auth/me').then(() => {setAuth('signed'); return refresh();}).catch(() => setAuth('guest')); }, []);
  useEffect(() => {
    if (auth !== 'signed' || !tasks.some(t => ['queued', 'pending', 'running', 'processing'].includes(t.status))) return;
    const timer = setInterval(() => {refresh().catch(e => setError(e.message));}, 3000);
    return () => clearInterval(timer);
  }, [auth, tasks]);

  async function login(e: FormEvent) {
    e.preventDefault(); setBusy(true); setError('');
    try {await api('/auth/login', {method: 'POST', body: JSON.stringify({password})}); setPassword(''); setAuth('signed'); await refresh();}
    catch (e) {setError(e instanceof Error ? e.message : '登录失败');} finally {setBusy(false);}
  }
  async function importData(e: FormEvent) {
    e.preventDefault(); setBusy(true); setError(''); setNotice('');
    try {
      let result: {id: string};
      if (importFormat === 'csv') {
        result = await api('/imports/csv', {method: 'POST', body: JSON.stringify({is_demo: demo, csv_text: data})});
      } else {
      const envelope = JSON.parse(data);
      if (envelope.data && envelope.adapter !== 'standard-json') throw new Error('仅支持 standard-json 适配器。');
      const parsed = envelope.data || envelope;
      const isDemo = envelope.data ? envelope.is_demo : demo;
      if (typeof isDemo !== 'boolean') throw new Error('完整导入 JSON 必须包含 is_demo 布尔字段。');
      if (!Array.isArray(parsed.videos)) throw new Error('JSON 顶层必须包含 videos 数组。');
      result = await api('/imports', {method: 'POST', body: JSON.stringify({adapter: 'standard-json', data: parsed, is_demo: isDemo})});
      }
      setNotice(`导入任务已提交：${result.id}。请在任务记录中查看处理结果。`); await refresh();
    } catch (e) {setError(e instanceof Error ? e.message : '导入失败');} finally {setBusy(false);}
  }

  if (auth === 'checking') return <main className="loading">正在连接私有工作台…</main>;
  if (auth === 'guest') return <main className="login-screen"><section className="login-card"><div className="brand-icon">知</div><p className="eyebrow">SCIENCE CREATOR WORKSPACE</p><h1>从好问题，<br />到好作品。</h1><p className="muted">登录你的私有科普编导工作台，让每一次创作从证据出发。</p><form onSubmit={login}><label htmlFor="password">工作台密码</label><input id="password" type="password" value={password} onChange={e => setPassword(e.target.value)} required autoComplete="current-password" placeholder="输入服务端配置的登录密码" />{error && <p role="alert" className="error">{error}</p>}<button disabled={busy} className="primary" type="submit">{busy ? '正在登录…' : '进入工作台 →'}</button></form><small>私有空间 · 数据默认不公开</small></section></main>;

  const filtered = videos.filter(v => (!demoOnly || v.is_demo) && `${v.title} ${v.platform} ${v.external_id}`.toLowerCase().includes(query.toLowerCase()));
  return <div className="shell"><aside><a className="brand" href="/"><span className="brand-icon">知</span><span>知序 <small>AI 科普编导工作台</small></span></a><p className="nav-label">创作空间</p><nav><button className={tab === 'library' ? 'active' : ''} onClick={() => setTab('library')}>▤ <span>内容资料库</span><b>{videos.length}</b></button><button className={tab === 'imports' ? 'active' : ''} onClick={() => setTab('imports')}>↥ <span>数据导入</span></button><button className={tab === 'research' ? 'active' : ''} onClick={() => setTab('research')}>◎ <span>需求与选题</span></button></nav><div className="phase-note"><span className="dot" /> M2 · 需求与选题<p>先积累真实资料，再发现值得解释的问题。</p></div><div className="private-note">◈ 私有工作台<br /><small>所有资料仅供个人创作使用</small></div></aside><main className="workspace"><header><span>我的工作台 <span className="separator">/</span> {tab === 'library' ? '内容资料库' : tab === 'research' ? '需求与选题' : '数据导入'}</span><span className="session"><span className="dot" /> 已登录 <button className="text-button" onClick={async () => {try {await api('/auth/logout', {method: 'POST'}); setAuth('guest'); setVideos([]); setTasks([]);} catch (e) {setError(e instanceof Error ? e.message : '退出失败');}}}>退出</button></span></header><div className="content"><div className="page-heading"><div><p className="eyebrow">YOUR CREATIVE FOUNDATION</p><h1>{tab === 'library' ? '每个好选题，都有迹可循。' : tab === 'research' ? '让观众的问题，成为选题的起点。' : '把观众的问题，带进工作台。'}</h1><p className="muted">{tab === 'library' ? '汇集视频、评论与相关搜索，为后续研究保留来源依据。' : tab === 'research' ? '从导入资料中提炼需求，查看证据和评分，再由你决定创作方向。' : '通过标准适配接口导入已有采集器的数据，保留原始资料与处理记录。'}</p></div>{tab === 'library' && <button className="primary" onClick={() => setTab('imports')}>＋ 导入资料</button>}</div>{error && <div role="alert" className="error banner">{error}</div>}{notice && <div role="status" className="success banner">{notice}</div>}
      {tab === 'research' ? <ResearchPanel /> : tab === 'library' ? <><div className="stats"><article><span>本页视频</span><strong>{videos.length}<small>条</small></strong></article><article><span>本页收录评论</span><strong>{videos.reduce((sum, v) => sum + (v.comments_count || 0), 0)}<small>条</small></strong></article><article><span>本页示例视频</span><strong>{videos.filter(v => v.is_demo).length}<small>条 · 明确区分</small></strong></article></div><section className="panel"><div className="panel-heading"><h2>内容资料库 <span className="count">{filtered.length}</span></h2><label className="checkbox"><input type="checkbox" checked={demoOnly} onChange={e => setDemoOnly(e.target.checked)} />仅示例</label><button className="text-button" onClick={() => {setError(''); refresh().catch(e => setError(e.message));}}>刷新</button><input className="search" aria-label="搜索资料" placeholder="在本页搜索标题、平台或来源编号" value={query} onChange={e => setQuery(e.target.value)} /></div>{filtered.length ? <div className="video-list">{filtered.map(v => <article className="video" key={v.id}><div className="video-icon">▤</div><div className="video-body"><div className="badges"><span>{v.platform}</span><span className={v.is_demo ? 'demo-badge' : 'real-badge'}>{v.is_demo ? '示例数据' : '导入数据'}</span></div><h3>{v.title}</h3><p>{v.comments_count ?? '未知'} 条评论 · 来源编号 {v.external_id}</p>{v.source_url && /^https?:\/\//i.test(v.source_url) && <a href={v.source_url} target="_blank" rel="noreferrer">查看来源 ↗</a>}<details onToggle={async e => {if (e.currentTarget.open && !detail[v.id]) {try {const result = await api(`/videos/${v.id}`); setDetail(old => ({...old, [v.id]: result}));} catch (e) {setError(e instanceof Error ? e.message : '详情加载失败');}}}}><summary>查看评论与指标</summary>{detail[v.id] ? <div className="video-detail">{detail[v.id].comments.map(c => <p key={c.id}>{c.text} · 点赞 {c.likes ?? '未知'}</p>)}{!detail[v.id].comments.length && <p>暂无评论</p>}<pre>{pretty(detail[v.id].snapshots)}</pre></div> : <p>正在加载…</p>}</details></div></article>)}</div> : <div className="empty"><div>▤</div><h3>{query ? '没有找到匹配资料' : '资料库还在等待第一个好问题'}</h3><p>{query ? '尝试调整标题、平台或来源编号。' : '导入已有采集器的视频与评论，开始积累创作证据。'}</p>{!query && <button className="secondary" onClick={() => setTab('imports')}>导入第一批资料 →</button>}</div>}</section><p className="footnote">当前展示最近 50 条资料，搜索和统计仅覆盖本页。需求与选题页面可分析导入资料。AI 编导将在后续里程碑接入。</p></> : <div className="import-grid"><section className="panel import-panel"><div className="panel-heading"><h2>资料导入</h2><label className="import-format">格式 <select aria-label="导入格式" value={importFormat} disabled={busy} onChange={e => {setImportFormat(e.target.value as 'json' | 'csv'); setData(''); setNotice(''); setError('');}}><option value="json">JSON</option><option value="csv">CSV</option></select></label></div><p className="muted">{importFormat === 'json' ? '支持完整导入请求（adapter / is_demo / data）或顶层包含 videos 数组的 JSON；完整请求以自身 is_demo 标记为准。' : '首行为固定列名，每行一条评论；同一视频的元数据请重复填写。related_searches 和 tags 用 | 分隔，未知指标留空。'}原始数据与标准化数据分别保存。</p><form onSubmit={importData}>{importFormat === 'csv' && <details className="csv-columns"><summary>查看固定 CSV 列</summary><code>{csvColumns}</code></details>}<label htmlFor="json">视频与评论数据</label><textarea id="json" value={data} onChange={e => setData(e.target.value)} placeholder={importFormat === 'json' ? '{ "videos": [...] }' : csvColumns} spellCheck={false} required /><label className="checkbox"><input type="checkbox" checked={demo} onChange={e => setDemo(e.target.checked)} />这是模拟或示例数据（会在资料库中明确标记）</label><div className="form-actions"><button className="secondary" type="button" onClick={() => {setData(importFormat === 'json' ? sample : csvSample); setDemo(true);}}>填入示例数据</button><button className="primary" type="submit" disabled={busy || !data.trim()}>{busy ? '正在提交…' : '提交导入 →'}</button></div></form><div className="import-help">首次测试可使用示例数据；示例不代表真实平台内容。时间字段须包含时区，不要填入 Cookie 或 API 密钥。</div></section><section className="panel task-panel"><div className="panel-heading"><h2>任务记录</h2><button className="text-button" onClick={() => {setError(''); refresh().catch(e => setError(e.message));}}>刷新</button></div>{tasks.length ? tasks.map(t => <article className="task" key={t.id}><div className="task-title"><strong>{statusLabel[t.status] || t.status}</strong><span className={t.is_demo ? 'demo-badge' : 'real-badge'}>{t.is_demo ? '示例' : '导入数据'}</span></div><code>{t.id}</code>{['failed', 'pending'].includes(t.status) && <button className="text-button" disabled={busy} onClick={async () => {setBusy(true); setError(''); try {await api(`/imports/${t.id}/retry`, {method: 'POST'}); await refresh();} catch (e) {setError(e instanceof Error ? e.message : '重试失败');} finally {setBusy(false);}}}>重试</button>}{t.error ? <pre className="error">{pretty(t.error)}</pre> : null}{t.result ? <details><summary>处理结果</summary><pre>{pretty(t.result)}</pre></details> : null}</article>) : <div className="empty compact"><h3>暂无导入记录</h3><p>提交后可在此查看处理结果。</p></div>}</section></div>}
    </div></main></div>;
}

