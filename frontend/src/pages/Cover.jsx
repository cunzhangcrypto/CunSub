import { useState, useEffect } from 'react'
import { analyzeCover, getCoverFields, buildCoverPrompt } from '../api/client'

export default function Cover({ projectId, setView }) {
  const [fields, setFields] = useState({ title: '', cover_text: '', category: '' })
  const [analyzing, setAnalyzing] = useState(false)
  const [building, setBuilding] = useState(false)
  const [prompt, setPrompt] = useState('')
  const [error, setError] = useState('')
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    getCoverFields(projectId).then(d => {
      if (d) setFields({ title: d.title || '', cover_text: d.cover_text || '', category: d.category || '' })
    }).catch(() => {})
  }, [])

  function update(key, value) {
    setFields(prev => ({ ...prev, [key]: value }))
  }

  async function handleAnalyze() {
    setAnalyzing(true)
    setError('')
    try {
      const d = await analyzeCover(projectId)
      setFields({ title: d.title || '', cover_text: d.cover_text || '', category: d.category || '' })
    } catch (e) {
      setError(e.message || '分析失败')
    } finally {
      setAnalyzing(false)
    }
  }

  async function handleBuild() {
    if (!fields.title.trim() && !fields.cover_text.trim()) {
      return setError('请先填写标题或界面显示文字')
    }
    setBuilding(true)
    setError('')
    try {
      const d = await buildCoverPrompt(projectId, fields)
      setPrompt(d.prompt)
    } catch (e) {
      setError(e.message || '生成提示词失败')
    } finally {
      setBuilding(false)
    }
  }

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(prompt)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {}
  }

  return (
    <div>
      <button
        onClick={() => setView({ page: 'review', projectId })}
        className="text-tx-secondary hover:text-accent-cyan transition-colors text-sm mb-4 font-mono"
      >
        ← 返回审校
      </button>

      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-2xl font-bold mb-1">封面复刻提示词</h2>
          <p className="text-sm text-tx-secondary font-mono">
            // 提炼封面三要素 → 确认修改 → 填入复刻模板 → 一键复制
          </p>
        </div>
        <button
          onClick={handleAnalyze}
          disabled={analyzing}
          className="btn-glow px-4 py-2 rounded-lg text-sm font-medium text-white disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {analyzing ? 'AI 提炼中...' : 'AI 从字幕提炼'}
        </button>
      </div>

      {error && (
        <div className="bg-accent-red/10 border border-accent-red/30 rounded-lg px-4 py-3 text-sm text-accent-red mb-4">
          {error}
        </div>
      )}

      {/* 三要素表单 */}
      <div className="bg-bg-card border border-bg-border rounded-xl p-5 mb-4">
        <div className="text-sm text-tx-primary font-medium mb-4">封面所需内容（可手动修改）</div>
        <div className="space-y-4">
          <div>
            <label className="text-xs text-tx-dim font-mono block mb-1.5">标题</label>
            <input
              value={fields.title}
              onChange={e => update('title', e.target.value)}
              placeholder="视频标题（简洁有力，30字以内）"
              className="w-full bg-bg-base border border-bg-border rounded-lg px-3 py-2.5 text-sm focus:border-accent-cyan focus:outline-none"
            />
          </div>
          <div>
            <label className="text-xs text-tx-dim font-mono block mb-1.5">
              界面显示文字（封面大字，≤8字，全封面唯一文字）
            </label>
            <input
              value={fields.cover_text}
              onChange={e => update('cover_text', e.target.value)}
              placeholder="如：免费白嫖、字幕不再翻车"
              className="w-full bg-bg-base border border-bg-border rounded-lg px-3 py-2.5 text-sm focus:border-accent-cyan focus:outline-none"
            />
          </div>
          <div>
            <label className="text-xs text-tx-dim font-mono block mb-1.5">账号领域</label>
            <input
              value={fields.category}
              onChange={e => update('category', e.target.value)}
              placeholder="如：网站相关、科技科普、工具教程"
              className="w-full bg-bg-base border border-bg-border rounded-lg px-3 py-2.5 text-sm focus:border-accent-cyan focus:outline-none"
            />
          </div>
        </div>

        <div className="mt-5">
          <button
            onClick={handleBuild}
            disabled={building}
            className="btn-glow px-6 py-2.5 rounded-lg font-medium text-white disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {building ? '生成中...' : '确定 · 填入复刻提示词'}
          </button>
        </div>
      </div>

      {/* 复刻提示词模板说明 */}
      <div className="bg-bg-card border border-bg-border rounded-xl p-5 mb-4">
        <div className="text-sm text-tx-primary font-medium mb-2">复刻提示词模板</div>
        <p className="text-xs text-tx-secondary font-mono leading-relaxed whitespace-pre-wrap">
{`你是一个 AI 封面复刻助手…（拆解参考封面 → 迁移新内容 → 输出提示词）

按要求生成Youtube高点击率的视频封面图。封面禁止出现标题文字。
标题：${fields.title || '（待填）'}
界面显示文字：${fields.cover_text || '（待填）'}
账号领域：${fields.category || '（待填）'}
画面比例：16：9
是否有人像：否
参考程度：高度参考`}
        </p>
        <p className="text-xs text-tx-dim font-mono mt-2">
          // 点击"确定"后，将上面三个字段填入完整模板，生成最终可复制的提示词
        </p>
      </div>

      {/* 最终提示词 */}
      {prompt && (
        <div className="bg-bg-card border border-bg-border rounded-xl overflow-hidden">
          <div className="flex items-center justify-between px-5 py-3 border-b border-bg-border">
            <span className="text-sm text-tx-primary font-medium">最终复刻提示词</span>
            <button
              onClick={handleCopy}
              className="px-4 py-1.5 rounded-lg border border-bg-border text-sm font-mono hover:border-accent-cyan hover:text-accent-cyan transition-colors"
            >
              {copied ? '已复制 ✓' : '一键复制'}
            </button>
          </div>
          <pre className="px-5 py-4 text-sm text-tx-secondary whitespace-pre-wrap font-sans leading-relaxed max-h-[28rem] overflow-y-auto">
            {prompt}
          </pre>
        </div>
      )}
    </div>
  )
}
