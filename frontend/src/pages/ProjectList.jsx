import { useState, useEffect } from 'react'
import { listProjects, deleteProject } from '../api/client'

const STATUS_MAP = {
  uploading: { label: '上传中', color: 'text-tx-secondary border-tx-secondary/30' },
  extracting: { label: '提取中', color: 'text-tx-secondary border-tx-secondary/30' },
  uploading_gemini: { label: '上传Gemini', color: 'text-tx-secondary border-tx-secondary/30' },
  uploaded: { label: '已上传', color: 'text-tx-secondary border-tx-secondary/30' },
  understanding: { label: '理解中', color: 'text-accent-cyan border-accent-cyan/30' },
  awaiting_confirmation: { label: '待确认', color: 'text-accent-amber border-accent-amber/30' },
  confirmed: { label: '已确认', color: 'text-blue-400 border-blue-400/30' },
  generating: { label: '生成中', color: 'text-accent-cyan border-accent-cyan/30' },
  generated: { label: '已生成', color: 'text-accent-green border-accent-green/30' },
}

export default function ProjectList({ setView }) {
  const [projects, setProjects] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    load()
  }, [])

  async function load() {
    setLoading(true)
    setError('')
    try {
      const data = await listProjects()
      setProjects(data)
    } catch (err) {
      setError(err.message || '加载项目列表失败，请确认后端服务是否运行')
      setProjects([])
    } finally {
      setLoading(false)
    }
  }

  async function handleDelete(id, e) {
    e.stopPropagation()
    try {
      await deleteProject(id)
      setProjects(prev => prev.filter(p => p.id !== id))
    } catch (err) {
      console.error('删除失败:', err)
      alert('删除失败: ' + err.message)
    }
  }

  function handleClick(project) {
    const status = project.status
    if (['uploaded', 'understanding', 'awaiting_confirmation', 'confirmed', 'extracted', 'uploading_gemini', 'extracting', 'uploading'].includes(status)) {
      setView({ page: 'confirmation', projectId: project.id })
    } else {
      setView({ page: 'review', projectId: project.id })
    }
  }

  function formatDuration(sec) {
    const m = Math.floor(sec / 60)
    const s = Math.floor(sec % 60)
    return `${m}:${s.toString().padStart(2, '0')}`
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-8">
        <div>
          <h2 className="text-2xl font-bold mb-1">项目列表</h2>
          <p className="text-sm text-tx-secondary font-mono">// 选择项目继续，或新建字幕任务</p>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={load}
            disabled={loading}
            className="px-4 py-2.5 rounded-lg border border-bg-border text-tx-secondary font-mono text-sm hover:border-accent-cyan hover:text-accent-cyan transition-colors disabled:opacity-40"
          >
            ↻ {loading ? '加载中...' : '刷新'}
          </button>
          <button
            onClick={() => setView({ page: 'upload' })}
            className="btn-glow px-6 py-2.5 rounded-lg font-medium text-bg-base"
          >
            + 新建项目
          </button>
        </div>
      </div>

      {error && (
        <div className="mb-6 bg-accent-red/10 border border-accent-red/30 rounded-lg px-4 py-3 text-sm text-accent-red flex items-center justify-between">
          <span>⚠ {error}</span>
          <button onClick={load} className="underline hover:no-underline text-accent-red/80 ml-4 shrink-0">
            重试
          </button>
        </div>
      )}

      {loading ? (
        <div className="text-center py-20 text-tx-secondary font-mono">loading...</div>
      ) : projects.length === 0 ? (
        <div className="text-center py-20">
          <div className="text-6xl mb-4 opacity-20">🎙️</div>
          <p className="text-tx-secondary mb-4">还没有项目</p>
          <button
            onClick={() => setView({ page: 'upload' })}
            className="btn-glow px-6 py-2.5 rounded-lg font-medium text-bg-base"
          >
            上传第一个音频
          </button>
        </div>
      ) : (
        <div className="grid gap-3">
          {projects.map(p => {
            const st = STATUS_MAP[p.status] || { label: p.status, color: 'text-tx-secondary border-tx-secondary/30' }
            return (
              <div
                key={p.id}
                onClick={() => handleClick(p)}
                className="bg-bg-card border border-bg-border rounded-lg p-4 flex items-center justify-between hover:border-accent-cyan/50 hover:bg-bg-hover cursor-pointer transition-all group"
              >
                <div className="flex items-center gap-4">
                  <div className="w-10 h-10 rounded-lg bg-bg-base border border-bg-border flex items-center justify-center text-lg">
                    {p.source_file_type === 'video' ? '🎬' : '🎵'}
                  </div>
                  <div>
                    <h3 className="font-medium group-hover:text-accent-cyan transition-colors">{p.name}</h3>
                    <div className="flex items-center gap-3 text-xs text-tx-secondary mt-1 font-mono">
                      <span>{formatDuration(p.source_duration)}</span>
                      <span>·</span>
                      <span>{new Date(p.created_at).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })}</span>
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <span className={`terminal-tag ${st.color}`}>{st.label}</span>
                  <button
                    onClick={(e) => handleDelete(p.id, e)}
                    className="text-tx-dim hover:text-accent-red transition-colors px-2"
                  >
                    ✕
                  </button>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}