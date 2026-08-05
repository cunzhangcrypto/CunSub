import { useState, useEffect } from 'react'
import { getSubtitles, editSubtitle, exportSubtitles } from '../api/client'

export default function Review({ projectId, setView }) {
  const [subtitles, setSubtitles] = useState([])
  const [loading, setLoading] = useState(true)
  const [editingIdx, setEditingIdx] = useState(null)
  const [editText, setEditText] = useState('')
  const [exporting, setExporting] = useState('')
  const [exportError, setExportError] = useState('')

  useEffect(() => {
    load()
  }, [])

  async function load() {
    try {
      const data = await getSubtitles(projectId)
      setSubtitles(data)
    } finally {
      setLoading(false)
    }
  }

  function startEdit(sub) {
    setEditingIdx(sub.idx)
    setEditText(sub.text)
  }

  async function saveEdit(idx) {
    await editSubtitle(projectId, idx, editText)
    setSubtitles(subtitles.map(s => s.idx === idx ? { ...s, text: editText, edited: 1 } : s))
    setEditingIdx(null)
  }

  async function handleExport(format) {
    setExporting(format)
    setExportError('')
    try {
      await exportSubtitles(projectId, format)
    } catch (e) {
      setExportError(e.message || '导出失败')
    } finally {
      setExporting('')
    }
  }

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center py-32">
        <div className="relative w-16 h-16 mb-6">
          <div className="absolute inset-0 rounded-full border-2 border-bg-border"></div>
          <div className="absolute inset-0 rounded-full border-2 border-transparent border-t-accent-cyan animate-spin"></div>
        </div>
        <p className="text-tx-secondary font-mono">// 加载字幕...</p>
      </div>
    )
  }

  const editedCount = subtitles.filter(s => s.edited).length

  return (
    <div>
      <button
        onClick={() => setView({ page: 'list' })}
        className="text-tx-secondary hover:text-accent-cyan transition-colors text-sm mb-4 font-mono"
      >
        ← 返回列表
      </button>

      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-2xl font-bold mb-1">审校字幕</h2>
          <p className="text-sm text-tx-secondary font-mono">
            // 共 {subtitles.length} 条 · 已编辑 {editedCount} 条 · 点击文本可编辑
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-tx-secondary font-mono mr-1">导出:</span>
          {['srt', 'vtt', 'ass'].map(fmt => (
            <button
              key={fmt}
              onClick={() => handleExport(fmt)}
              disabled={exporting !== ''}
              className="px-4 py-2 rounded-lg border border-bg-border text-sm font-mono hover:border-accent-cyan hover:text-accent-cyan transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {exporting === fmt ? '导出中...' : `.${fmt}`}
            </button>
          ))}
        </div>
      </div>

      {exportError && (
        <div className="bg-accent-red/10 border border-accent-red/30 rounded-lg px-4 py-3 text-sm text-accent-red mb-4">
          {exportError}
        </div>
      )}

      {subtitles.length === 0 ? (
        <div className="bg-bg-card border border-bg-border rounded-xl p-12 text-center text-tx-secondary">
          没有字幕数据
        </div>
      ) : (
        <div className="bg-bg-card border border-bg-border rounded-xl overflow-hidden">
          {subtitles.map((sub) => (
            <div
              key={sub.idx}
              className="flex items-start gap-4 px-4 py-3 border-b border-bg-border last:border-0 hover:bg-bg-hover/50 transition-colors"
            >
              <span className="text-xs text-tx-dim font-mono w-8 mt-1">
                {sub.idx.toString().padStart(3, '0')}
              </span>
              <div className="text-xs text-tx-secondary font-mono w-28 mt-1">
                <div>{sub.start_time}</div>
                <div className="text-tx-dim">{sub.end_time}</div>
              </div>
              <div className="flex-1">
                {editingIdx === sub.idx ? (
                  <div className="flex gap-2">
                    <input
                      value={editText}
                      onChange={(e) => setEditText(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') saveEdit(sub.idx)
                        if (e.key === 'Escape') setEditingIdx(null)
                      }}
                      className="flex-1 bg-bg-base border border-accent-cyan rounded px-2 py-1 text-sm focus:outline-none"
                      autoFocus
                    />
                    <button
                      onClick={() => saveEdit(sub.idx)}
                      className="text-xs text-accent-green hover:underline whitespace-nowrap"
                    >
                      保存
                    </button>
                    <button
                      onClick={() => setEditingIdx(null)}
                      className="text-xs text-tx-secondary hover:underline"
                    >
                      取消
                    </button>
                  </div>
                ) : (
                  <p
                    onClick={() => startEdit(sub)}
                    className={`text-sm cursor-text hover:text-accent-cyan transition-colors ${
                      sub.edited ? 'text-accent-green' : 'text-tx-primary'
                    }`}
                  >
                    {sub.text}
                  </p>
                )}
              </div>
              {sub.edited ? (
                <span className="text-xs text-accent-green font-mono mt-1">✎</span>
              ) : null}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
