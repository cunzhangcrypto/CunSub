import { useState, useEffect, useRef } from 'react'
import { getUnderstanding, confirmTerms, startGeneration, getAudioClipUrl, parseHintToSeconds } from '../api/client'

function fmtElapsed(sec) {
  if (sec == null) return '0s'
  if (sec < 60) return `${sec.toFixed(1)}s`
  const m = Math.floor(sec / 60)
  const s = Math.round(sec % 60)
  return `${m}m${s}s`
}

export default function Confirmation({ projectId, setView }) {
  const [loading, setLoading] = useState(true)
  const [data, setData] = useState(null)
  const [confirmations, setConfirmations] = useState({})
  const [keepAi, setKeepAi] = useState({})
  const [additionalTerms, setAdditionalTerms] = useState([])
  const [newTerm, setNewTerm] = useState('')
  const [termCorrections, setTermCorrections] = useState({}) // 已识别术语修正：{原写法: 正确写法}
  const [editingTerm, setEditingTerm] = useState(null) // 当前正在编辑的术语 key
  const [phase, setPhase] = useState('ready') // ready/confirming/generating
  const [error, setError] = useState('')
  const [elapsed, setElapsed] = useState(0) // 当前阶段已用秒数
  const audioRef = useRef(null)
  const timerRef = useRef(null)

  // 阶段计时:进入 confirming/generating 时开始,ready 时停止
  useEffect(() => {
    if (phase === 'confirming' || phase === 'generating') {
      const start = Date.now()
      setElapsed(0)
      timerRef.current = setInterval(() => {
        setElapsed((Date.now() - start) / 1000)
      }, 100)
    } else {
      if (timerRef.current) {
        clearInterval(timerRef.current)
        timerRef.current = null
      }
    }
    return () => {
      if (timerRef.current) clearInterval(timerRef.current)
    }
  }, [phase])

  useEffect(() => {
    load()
  }, [])

  async function load() {
    try {
      const result = await getUnderstanding(projectId)
      setData(result)
      const initKeep = {}
      const initConfirm = {}
      result.suspected_errors?.forEach(err => {
        initKeep[err.word] = true
        initConfirm[err.word] = err.ai_guess
      })
      setKeepAi(initKeep)
      setConfirmations(initConfirm)
    } catch (e) {
      setError('加载理解结果失败，可能还在处理中')
    } finally {
      setLoading(false)
    }
  }

  const errors = data?.suspected_errors || []
  const processedCount = errors.filter(err => keepAi[err.word] || confirmations[err.word]?.trim()).length
  const totalCount = errors.length
  const allProcessed = processedCount === totalCount

  function playClip(hint) {
    const start = parseHintToSeconds(hint)
    if (audioRef.current) {
      audioRef.current.src = getAudioClipUrl(projectId, Math.max(0, start - 2))
      audioRef.current.play()
    }
  }

  function handleConfirmChange(word, value) {
    setConfirmations(prev => ({ ...prev, [word]: value }))
    setKeepAi(prev => ({ ...prev, [word]: false }))
  }

  function toggleKeepAi(word) {
    setKeepAi(prev => {
      const next = !prev[word]
      if (next) {
        const err = errors.find(e => e.word === word)
        setConfirmations(prev2 => ({ ...prev2, [word]: err?.ai_guess || '' }))
      }
      return { ...prev, [word]: next }
    })
  }

  function addTerm() {
    if (newTerm.trim() && !additionalTerms.includes(newTerm.trim())) {
      setAdditionalTerms([...additionalTerms, newTerm.trim()])
      setNewTerm('')
    }
  }

  async function handleConfirmAndGenerate() {
    if (!allProcessed) return
    setPhase('confirming')
    setError('')
    try {
      const termsMapping = {}
      errors.forEach(err => {
        termsMapping[err.word] = confirmations[err.word] || err.ai_guess
      })
      // 只保留真正改动的术语修正
      const realCorrections = {}
      Object.entries(termCorrections).forEach(([k, v]) => {
        if (v && v.trim() && v.trim() !== k) realCorrections[k] = v.trim()
      })
      await confirmTerms(projectId, termsMapping, additionalTerms, realCorrections)

      setPhase('generating')
      await startGeneration(projectId)

      setView({ page: 'review', projectId })
    } catch (e) {
      setError(e.message || '处理失败')
      setPhase('ready')
    }
  }

  // 加载态
  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center py-32">
        <div className="relative w-16 h-16 mb-6">
          <div className="absolute inset-0 rounded-full border-2 border-bg-border"></div>
          <div className="absolute inset-0 rounded-full border-2 border-transparent border-t-accent-cyan animate-spin"></div>
        </div>
        <p className="text-tx-secondary font-mono">// 加载理解结果...</p>
      </div>
    )
  }

  // 确认中 / 生成中
  if (phase === 'confirming' || phase === 'generating') {
    return (
      <div className="flex flex-col items-center justify-center py-32">
        <div className="relative w-20 h-20 mb-8">
          <div className="absolute inset-0 rounded-full border-2 border-bg-border"></div>
          <div className="absolute inset-0 rounded-full border-2 border-transparent border-t-accent-cyan animate-spin"></div>
          <div className="absolute inset-2 rounded-full border-2 border-transparent border-t-accent-purple animate-spin-slow"></div>
        </div>
        <h3 className="text-xl font-medium mb-2">
          {phase === 'confirming' ? '提交确认中...' : 'AI 正在生成字幕...'}
        </h3>
        <p className="text-tx-secondary font-mono text-sm">
          {phase === 'confirming'
            ? '// 保存术语词典'
            : '// 基于确认术语重新转录音频，可能需要 1-2 分钟'}
        </p>
        <p className="text-accent-cyan font-mono text-lg mt-2 tabular-nums">
          ⏱ {fmtElapsed(elapsed)}
        </p>
        {phase === 'generating' && (
          <div className="w-64 h-1 bg-bg-card rounded-full mt-6 overflow-hidden">
            <div className="h-full progress-flow rounded-full" style={{ width: '100%' }}></div>
          </div>
        )}
      </div>
    )
  }

  if (error && !data) {
    return (
      <div className="text-center py-20">
        <p className="text-accent-red mb-4">{error}</p>
        <button onClick={() => setView({ page: 'list' })} className="text-accent-cyan hover:underline">
          返回列表
        </button>
      </div>
    )
  }

  return (
    <div>
      <audio ref={audioRef} className="hidden" />

      <button
        onClick={() => setView({ page: 'list' })}
        className="text-tx-secondary hover:text-accent-cyan transition-colors text-sm mb-4 font-mono"
      >
        ← 返回列表
      </button>

      <h2 className="text-2xl font-bold mb-1">确认门 · 术语校准</h2>
      <p className="text-sm text-tx-secondary font-mono mb-6">// 确认专业词汇后才会生成字幕</p>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* 左侧：内容摘要 */}
        <div className="space-y-4">
          <div className="bg-bg-card border border-bg-border rounded-xl p-5">
            <div className="flex items-center gap-2 mb-3">
              <span className="terminal-tag border-accent-cyan/30 text-accent-cyan">A</span>
              <h3 className="font-medium">内容摘要</h3>
            </div>
            <p className="text-sm text-tx-primary leading-relaxed">{data?.content_summary}</p>
          </div>

          {data?.key_points?.length > 0 && (
            <div className="bg-bg-card border border-bg-border rounded-xl p-5">
              <h3 className="font-medium mb-3">📌 关键内容</h3>
              <ul className="space-y-2">
                {data.key_points.map((point, i) => (
                  <li key={i} className="text-sm text-tx-primary flex items-start gap-2">
                    <span className="text-accent-cyan mt-0.5">▸</span>
                    <span>{point}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {data?.technical_terms?.length > 0 && (
            <div className="bg-bg-card border border-bg-border rounded-xl p-5">
              <div className="flex items-center gap-2 mb-1">
                <h3 className="font-medium">📚 已识别术语</h3>
              </div>
              <p className="text-xs text-tx-dim font-mono mb-3">// 点术语可修正错误写法</p>
              <div className="flex flex-wrap gap-2">
                {data.technical_terms.map((t, i) => {
                  const original = t.term
                  const corrected = termCorrections[original]
                  const isCorrected = corrected && corrected !== original
                  const isEditing = editingTerm === original
                  if (isEditing) {
                    return (
                      <input
                        key={i}
                        autoFocus
                        value={corrected ?? original}
                        onChange={(e) => setTermCorrections(prev => ({ ...prev, [original]: e.target.value }))}
                        onBlur={() => setEditingTerm(null)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') setEditingTerm(null)
                          if (e.key === 'Escape') {
                            setTermCorrections(prev => {
                              const next = { ...prev }
                              delete next[original]
                              return next
                            })
                            setEditingTerm(null)
                          }
                        }}
                        className="bg-bg-base border border-accent-cyan rounded-lg px-3 py-1 text-sm text-tx-primary focus:outline-none w-40"
                        placeholder="输入正确写法"
                      />
                    )
                  }
                  return (
                    <button
                      key={i}
                      onClick={() => setEditingTerm(original)}
                      className={`terminal-tag transition-colors cursor-text ${isCorrected ? 'border-accent-green/30 text-accent-green' : 'border-accent-purple/30 text-accent-purple hover:border-accent-cyan/50'}`}
                      title={t.context ? `${t.context}\n(点击修正)` : '点击修正'}
                    >
                      {isCorrected ? (
                        <span className="line-through opacity-60">{original}</span>
                      ) : original}
                      {isCorrected && <span className="ml-1">→ {corrected}</span>}
                      {!isCorrected && <span className="ml-1 opacity-50">✎</span>}
                    </button>
                  )
                })}
              </div>
              {Object.keys(termCorrections).filter(k => termCorrections[k] && termCorrections[k] !== k).length > 0 && (
                <p className="text-xs text-accent-green font-mono mt-3">
                  ✓ 已修正 {Object.keys(termCorrections).filter(k => termCorrections[k] && termCorrections[k] !== k).length} 个术语
                </p>
              )}
            </div>
          )}

          {/* 补充术语 */}
          <div className="bg-bg-card border border-bg-border rounded-xl p-5">
            <h3 className="font-medium mb-3">➕ 补充术语</h3>
            <div className="flex gap-2 mb-2">
              <input
                value={newTerm}
                onChange={(e) => setNewTerm(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && addTerm()}
                className="flex-1 bg-bg-base border border-bg-border rounded-lg px-3 py-2 text-sm focus:border-accent-cyan focus:outline-none"
                placeholder="输入术语后回车"
              />
              <button
                onClick={addTerm}
                className="px-4 py-2 rounded-lg border border-bg-border text-tx-secondary hover:border-accent-cyan hover:text-accent-cyan transition-colors text-sm"
              >
                添加
              </button>
            </div>
            {additionalTerms.length > 0 && (
              <div className="flex flex-wrap gap-2 mt-2">
                {additionalTerms.map((t, i) => (
                  <span key={i} className="terminal-tag border-accent-green/30 text-accent-green flex items-center gap-1">
                    {t}
                    <button onClick={() => setAdditionalTerms(additionalTerms.filter((_, j) => j !== i))} className="hover:text-accent-red">
                      ✕
                    </button>
                  </span>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* 右侧：疑似错误词 */}
        <div className="space-y-3">
          <div className="flex items-center gap-2 mb-2">
            <span className="terminal-tag border-accent-amber/30 text-accent-amber">B</span>
            <h3 className="font-medium">疑似错误词</h3>
            <span className="text-xs text-tx-secondary font-mono ml-auto">
              {processedCount}/{totalCount} 已处理
            </span>
          </div>

          {errors.length === 0 ? (
            <div className="bg-bg-card border border-bg-border rounded-xl p-8 text-center text-tx-secondary">
              没有检测到疑似错误词
            </div>
          ) : (
            errors.map((err, i) => {
              const isKept = keepAi[err.word]
              const isProcessed = isKept || confirmations[err.word]?.trim()
              return (
                <div
                  key={i}
                  className={`bg-bg-card border rounded-xl p-4 transition-all ${
                    isProcessed ? 'border-accent-green/30' : 'border-accent-amber/30'
                  }`}
                >
                  <div className="flex items-start justify-between mb-3">
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="text-xs text-tx-dim font-mono">#{i + 1}</span>
                        <span className="text-tx-secondary line-through text-sm">{err.word}</span>
                      </div>
                      <p className="text-lg font-medium text-accent-cyan mt-1">
                        → {err.ai_guess}
                      </p>
                    </div>
                    <button
                      onClick={() => playClip(err.audio_hint)}
                      className="terminal-tag border-accent-cyan/30 text-accent-cyan hover:bg-accent-cyan/10 transition-colors flex items-center gap-1"
                    >
                      ▶ {err.audio_hint}
                    </button>
                  </div>

                  {/* 置信度 */}
                  <div className="flex items-center gap-2 mb-3">
                    <span className="text-xs text-tx-secondary font-mono">置信度</span>
                    <div className="flex-1 h-1.5 bg-bg-base rounded-full overflow-hidden">
                      <div
                        className={`h-full rounded-full ${err.confidence > 0.7 ? 'bg-accent-green' : err.confidence > 0.4 ? 'bg-accent-amber' : 'bg-accent-red'}`}
                        style={{ width: `${err.confidence * 100}%` }}
                      />
                    </div>
                    <span className="text-xs text-tx-secondary font-mono">{Math.round(err.confidence * 100)}%</span>
                  </div>

                  {/* 备选 */}
                  {err.alternatives?.length > 0 && (
                    <div className="flex flex-wrap gap-1 mb-3">
                      {err.alternatives.map((alt, j) => (
                        <button
                          key={j}
                          onClick={() => handleConfirmChange(err.word, alt)}
                          className={`terminal-tag transition-colors ${
                            confirmations[err.word] === alt
                              ? 'border-accent-cyan text-accent-cyan bg-accent-cyan/10'
                              : 'border-bg-border text-tx-secondary hover:border-accent-cyan/50'
                          }`}
                        >
                          {alt}
                        </button>
                      ))}
                    </div>
                  )}

                  {/* 确认输入 */}
                  <div className="flex items-center gap-2">
                    <input
                      value={confirmations[err.word] || ''}
                      onChange={(e) => handleConfirmChange(err.word, e.target.value)}
                      className={`flex-1 bg-bg-base border rounded-lg px-3 py-2 text-sm focus:outline-none transition-colors ${
                        isKept ? 'border-bg-border text-tx-secondary' : 'border-accent-cyan text-tx-primary'
                      }`}
                      placeholder="确认正确的写法"
                    />
                    <label className="flex items-center gap-1.5 text-xs text-tx-secondary cursor-pointer whitespace-nowrap">
                      <input
                        type="checkbox"
                        checked={isKept || false}
                        onChange={() => toggleKeepAi(err.word)}
                        className="accent-accent-cyan"
                      />
                      保留AI
                    </label>
                  </div>
                </div>
              )
            })
          )}

          {error && (
            <div className="bg-accent-red/10 border border-accent-red/30 rounded-lg px-4 py-3 text-sm text-accent-red">
              {error}
            </div>
          )}
        </div>
      </div>

      {/* 底部操作栏 */}
      <div className="sticky bottom-0 mt-8 -mx-6 px-6 py-4 bg-bg-base/90 backdrop-blur border-t border-bg-border">
        <div className="flex items-center justify-between max-w-6xl mx-auto">
          <div className="text-sm">
            <span className="text-tx-secondary font-mono">进度: </span>
            <span className={allProcessed ? 'text-accent-green' : 'text-accent-amber'}>
              {processedCount}/{totalCount}
            </span>
            <span className="text-tx-secondary font-mono"> 已处理</span>
          </div>
          <button
            onClick={handleConfirmAndGenerate}
            disabled={!allProcessed}
            className="btn-glow px-8 py-2.5 rounded-lg font-medium text-bg-base"
          >
            {allProcessed ? '确认并生成字幕 →' : '请先处理所有疑似词'}
          </button>
        </div>
      </div>
    </div>
  )
}
