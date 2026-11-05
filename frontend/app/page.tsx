'use client'
import { ChangeEvent, useEffect, useState } from 'react'

const API = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
type Activity = { event_type: string; message: string; created_at: string }
type Dashboard = { counts: Record<string, number>; activity: Activity[] }
type Video = { id: number; filename: string; status: string; duration_seconds?: number; width?: number; height?: number }
type Moment = { id: number; start_seconds: number; end_seconds: number; title?: string; hook: string; rationale: string; category?: string; score: number; status: string }
type Clip = { id: number; video_id: number; storage_path: string; duration_seconds: number; width?: number; height?: number; title?: string; status: string }
type Service = { service_name: string; status: string }
type Health = Record<string, { status: string; model_available?: boolean }>

export default function Home() {
  const [data, setData] = useState<Dashboard | null>(null)
  const [health, setHealth] = useState<Health | null>(null)
  const [services, setServices] = useState<Service[]>([])
  const [videos, setVideos] = useState<Video[]>([])
  const [moments, setMoments] = useState<Record<number, Moment[]>>({})
  const [clips, setClips] = useState<Clip[]>([])
  const [file, setFile] = useState<File | null>(null)
  const [busy, setBusy] = useState('')
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  async function request(path: string, init?: RequestInit) {
    const response = await fetch(`${API}${path}`, init)
    const body = await response.json().catch(() => ({}))
    if (!response.ok) throw new Error(body.detail || `Request failed (${response.status})`)
    return body
  }

  async function refresh() {
    const [dashboard, integration, serviceState, videoList, clipList] = await Promise.all([
      request('/api/dashboard'), request('/api/integrations'), request('/api/services'), request('/api/videos'), request('/api/clips')
    ])
    setData(dashboard); setHealth(integration); setServices(serviceState); setVideos(videoList); setClips(clipList)
  }

  useEffect(() => { refresh().catch(e => setError(e.message)) }, [])

  async function run(label: string, action: () => Promise<void>) {
    setBusy(label); setError(''); setMessage('')
    try { await action(); setMessage(`${label} completed`); await refresh() } catch (e) { setError(e instanceof Error ? e.message : 'Request failed') } finally { setBusy('') }
  }

  async function upload(event: React.FormEvent) {
    event.preventDefault()
    if (!file) return setError('Choose an authorized video first')
    await run('Upload', async () => {
      const form = new FormData(); form.append('file', file)
      await request('/api/videos/upload?authorized=true', { method: 'POST', body: form })
      setFile(null)
    })
  }

  async function loadMoments(videoId: number) {
    const result = await request(`/api/videos/${videoId}/moments`)
    setMoments(previous => ({ ...previous, [videoId]: result }))
  }

  const cards = [['channels', 'Source channels'], ['videos', 'Imported videos'], ['jobs', 'Processing jobs'], ['moments', 'Candidate moments'], ['clips', 'Generated clips'], ['pending_approval', 'Pending approval'], ['scheduled', 'Scheduled clips'], ['published', 'Published clips'], ['failures', 'Failures']]
  return <main>
    <header><div><p className="eyebrow">VIRALFLOW AI</p><h1>Authorized video → reviewable Shorts</h1><p className="muted">Local AI workflow. Nothing is published automatically.</p></div><span className="badge">Local pipeline</span></header>
    {error && <div className="notice error">{error}</div>}
    {message && <div className="notice success">{message}</div>}
    <section className="grid">{cards.map(([key, label]) => <article className="card" key={key}><span>{label}</span><strong>{data?.counts?.[key] ?? '—'}</strong></article>)}</section>
    <section className="panel workflow"><div className="panelHead"><h2>Process an authorized video</h2><span className="muted">upload → transcribe → analyze</span></div><form onSubmit={upload} className="uploadForm"><input type="file" accept="video/*" onChange={(e: ChangeEvent<HTMLInputElement>) => setFile(e.target.files?.[0] || null)} /><button disabled={!file || !!busy}>{busy === 'Upload' ? 'Uploading…' : 'Upload authorized video'}</button></form><p className="muted">Only use videos you own, licensed, or are explicitly authorized to process.</p></section>
    <section className="columns"><article className="panel"><div className="panelHead"><h2>Integration health</h2><span className="muted">real checks</span></div>{health ? Object.entries(health).map(([name, value]) => <div className="health" key={name}><span>{name}</span><span className={`status ${value.status}`}>{value.status}{value.model_available === false ? ' / model missing' : ''}</span></div>) : <p className="muted">Checking local services…</p>}</article><article className="panel"><div className="panelHead"><h2>Automation state</h2><span className="muted">backend state</span></div>{services.map(service => <div className="health" key={service.service_name}><span>{service.service_name.replaceAll('_', ' ')}</span><span className={`status ${service.status}`}>{service.status}</span></div>)}</article></section>
    <section className="panel"><div className="panelHead"><h2>Video processing</h2><span className="muted">actual database records</span></div>{videos.length ? videos.map(video => <div className="videoRow" key={video.id}><div><b>{video.filename}</b><small>{video.status} · {video.duration_seconds ? `${video.duration_seconds.toFixed(1)}s` : 'duration unknown'}</small></div><div className="actions"><button disabled={!!busy} onClick={() => run('Transcription', async () => { await request(`/api/videos/${video.id}/transcribe`, { method: 'POST', body: JSON.stringify({}), headers: { 'Content-Type': 'application/json' } }) })}>Transcribe</button><button disabled={!!busy} onClick={() => run('Qwen analysis', async () => { await request(`/api/videos/${video.id}/analyze`, { method: 'POST', body: JSON.stringify({ target_duration: 30 }), headers: { 'Content-Type': 'application/json' } }); await loadMoments(video.id) })}>Analyze moments</button><button className="secondary" onClick={() => loadMoments(video.id).catch(e => setError(e.message))}>View moments</button></div>{moments[video.id]?.map(moment => <div className="moment" key={moment.id}><div><b>{moment.title || moment.hook}</b><small>{moment.start_seconds.toFixed(1)}s–{moment.end_seconds.toFixed(1)}s · score {moment.score}/10 · {moment.category || 'general'}</small><p>{moment.rationale}</p></div><div className="actions"><button disabled={!!busy} onClick={() => run('Clip extraction', async () => { await request(`/api/moments/${moment.id}/extract`, { method: 'POST', body: JSON.stringify({ duration_seconds: 30 }), headers: { 'Content-Type': 'application/json' } }) })}>Generate clip</button></div></div>)}</div>) : <p className="muted">No videos yet.</p>}</section>
    <section className="panel"><div className="panelHead"><h2>Generated clips</h2><span className="muted">preview and subtitle output</span></div>{clips.length ? <div className="clipGrid">{clips.map(clip => <article className="clipCard" key={clip.id}><video controls preload="metadata" src={`${API}/api/clips/${clip.id}/file`} /><b>{clip.title || `Clip ${clip.id}`}</b><small>{clip.status} · {clip.duration_seconds.toFixed(1)}s · {clip.width}×{clip.height}</small><div className="actions"><button disabled={!!busy} onClick={() => run('Subtitle generation', async () => { await request(`/api/clips/${clip.id}/subtitles?subtitle_format=srt&burn_in=true`, { method: 'POST' }) })}>Burn subtitles</button><button disabled={!!busy} onClick={() => run('Approval', async () => { await request(`/api/clips/${clip.id}/review`, { method: 'POST', body: JSON.stringify({ status: 'approved' }), headers: { 'Content-Type': 'application/json' } }) })}>Approve</button></div></article>)}</div> : <p className="muted">Generated clips will appear here after a moment is selected.</p>}</section>
    <div className="notice"><b>Rights boundary:</b> monitoring a public channel does not grant permission to download or republish its videos.</div>
  </main>
}
