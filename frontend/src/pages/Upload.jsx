import { useState, useRef, useEffect } from 'react'
import { uploadFile, extractAudio, uploadToGemini, startUnderstanding, subscribeProgress, checkGeminiHealth } from '../api/client'

function fmtElapsed(sec) {
  if (sec == null) return ''
  if (sec < 60) return `${sec.toFixed(1)}s`
  const m = Math.floor(sec / 60)
  const s = Math.round(sec % 60)
  return `${m}m${s}s`
}

const STEPS = [
  { key: 'uploading', label: '上传文件', hint: '接收文件并落盘' },
  { key: 'extracting', label: '提取音频', hint: 'MP3 直接复制,视频才转码' },
  { key: 'uploading_gemini', label: '上传 Gemini', hint: '上传到 Google File API' },
  { key: 'understanding', label: 'AI 理解', hint: 'Gemini 分析音频内容' },
]

export default function Upload({ setView }) {
  const [file, setFile] = useState(null)
  const [name, setName] = useState('')
  const [phase, setPhase] = useState('idle')
  const [error, setError] = useState('')
  const [dragOver, setDragOver] = useState(false)
  const [progress, setProgress] = useState({})  // {uploading: 100, extracting: 45, ...}
  const [stepTimes, setStepTimes] = useState({})  // {uploading: 2.3, extracting: 1.5, ...} 完成后的耗时
  const [currentElapsed, setCurrentElapsed] = useState(0) // 当前步骤实时跳动秒数
  const stepStartRef = useRef({})
  const inputRef = useRef(null)
  const esRef = useRef(null)

  // phase 变化时:存上一个步骤的最终时间,启动新步骤实时计时
  useEffect(() => {
    const stepKeys = STEPS.map(s => s.key)
    if (!stepKeys.includes(phase)) return
    stepStartRef.current[phase] = Date.now()
    setCurrentElapsed(0)
    const timer = setInterval(() => {
      setCurrentElapsed((Date.now() - stepStartRef.current[phase]) / 1000)
    }, 100)
    return () => {
      clearInterval(timer)
      const start = stepStartRef.current[phase]
      if (start) {
        const elapsed = (Date.now() - start) / 1000
        setStepTimes(prev => ({ ...prev, [phase]: elapsed }))
      }
      setCurrentElapsed(0)
    }
  }, [phase])

  useEffect(() => () => { if (esRef.current) esRef.current.close() }, [])

  function handleFile(f) {
    setFile(f)
    setName(f.name.replace(/\.[^.]+$/, ''))
  }

  function handleDrop(e) {
    e.preventDefault()
    setDragOver(false)
    const f = e.dataTransfer.files[0]
    if (f) handleFile(f)
  }

  async function handleSubmit() {
    if (!file) return
    setError('')
    setProgress({})

    // 预检:Gemini 连通性
    setPhase('checking')
    const health = await checkGeminiHealth()
    if (!health.ok) {
      setError(health.message)
      setPhase('error')
      return
    }

    try {
      // Step 1: upload file
      setPhase('uploading')
      setProgress(p => ({ ...p, uploading: 10 }))
      const upRes = await uploadFile(file, name)
      setProgress(p => ({ ...p, uploading: 100 }))

      // Start SSE for steps 2-4
      esRef.current = subscribeProgress(upRes.id, (data) => {
        setProgress(p => ({ ...p, [data.step]: data.percent }))
      })

      // Step 2: extract audio
      setPhase('extracting')
      setProgress(p => ({ ...p, extracting: 5 }))
      await extractAudio(upRes.id)

      // Step 3: upload to gemini
      setPhase('uploading_gemini')
      setProgress(p => ({ ...p, uploading_gemini: 5 }))
      await uploadToGemini(upRes.id)

      // Step 4: understand
      setPhase('understanding')
      setProgress(p => ({ ...p, understanding: 5 }))
      await startUnderstanding(upRes.id)
      setProgress(p => ({ ...p, understanding: 100 }))

      if (esRef.current) esRef.current.close()
      setView({ page: 'confirmation', projectId: upRes.id })
    } catch (e) {
      // 从后端响应里提取具体错误信息
      let msg = e.message || '处理失败'
      if (e.message && e.message.includes('代理')) msg = e.message
      setError(msg)
      setPhase('error')
      if (esRef.current) esRef.current.close()
    }
  }

  // Loading state with 4-step progress + percentage
  if (STEPS.some(s => s.key === phase)) {
    const currentIdx = STEPS.findIndex(s => s.key === phase)
    return (
      <div className="max-w-xl mx-auto">
        <div className="flex flex-col items-center py-12">
          <div className="relative w-20 h-20 mb-8">
            <div className="absolute inset-0 rounded-full border-2 border-bg-border"></div>
            <div className="absolute inset-0 rounded-full border-2 border-transparent border-t-accent-cyan animate-spin"></div>
            <div className="absolute inset-2 rounded-full border-2 border-transparent border-t-accent-purple animate-spin-slow"></div>
          </div>

          <h3 className="text-xl font-medium mb-2">处理中</h3>
          <p className="text-tx-secondary font-mono text-sm mb-8">// 请耐心等待，不要关闭页面</p>

          {/* Step list with percentage */}
          <div className="w-full space-y-3">
            {STEPS.map((step, i) => {
              const done = i < currentIdx
              const active = i === currentIdx
              const pct = progress[step.key] || 0
              const stepDone = pct >= 100
              return (
                <div
                  key={step.key}
                  className={`p-3 rounded-lg border transition-all ${
                    active
                      ? 'border-accent-cyan bg-accent-cyan/5'
                      : stepDone || done
                      ? 'border-accent-green/30 bg-accent-green/5'
                      : 'border-bg-border opacity-40'
                  }`}
                >
                  <div className="flex items-center gap-3">
                    <div className={`w-7 h-7 rounded-full flex items-center justify-center text-sm font-mono shrink-0 ${
                      active ? 'bg-accent-cyan text-bg-base' : (stepDone || done) ? 'bg-accent-green text-bg-base' : 'bg-bg-base text-tx-dim'
                    }`}>
                      {(stepDone || done) ? '✓' : i + 1}
                    </div>
                    <div className="flex-1 text-left min-w-0">
                      <div className={`text-sm font-medium ${active ? 'text-accent-cyan' : (stepDone || done) ? 'text-accent-green' : 'text-tx-secondary'}`}>
                        {step.label}
                      </div>
                      <div className="text-xs text-tx-dim font-mono truncate">{step.hint}</div>
                    </div>
                    {active && (
                      <span className="text-sm font-mono text-accent-cyan shrink-0 min-w-[3em] text-right">
                        {pct}%
                      </span>
                    )}
                    {active && (
                      <span className="text-xs font-mono text-accent-cyan/80 shrink-0 tabular-nums">
                        ⏱ {fmtElapsed(currentElapsed)}
                      </span>
                    )}
                    {(stepDone || done) && stepTimes[step.key] != null && (
                      <span className="text-xs font-mono text-accent-green/80 shrink-0 tabular-nums">
                        ⏱ {fmtElapsed(stepTimes[step.key])}
                      </span>
                    )}
                  </div>
                  {/* per-step progress bar */}
                  {(active || stepDone || done) && (
                    <div className="h-1 bg-bg-base rounded-full mt-2 ml-10 overflow-hidden">
                      <div
                        className={`h-full rounded-full transition-all duration-300 ${stepDone || done ? 'bg-accent-green' : 'progress-flow'}`}
                        style={{ width: `${pct}%` }}
                      ></div>
                    </div>
                  )}
                </div>
              )
            })}
          </div>

          {/* overall progress */}
          <div className="w-full mt-6">
            <div className="flex justify-between text-xs text-tx-dim font-mono mb-1">
              <span>总进度</span>
              <span>
                {currentIdx + 1} / {STEPS.length}
                {Object.values(stepTimes).length > 0 && (
                  <span className="ml-3 text-accent-green/70">
                    累计 {fmtElapsed(Object.values(stepTimes).reduce((a, b) => a + b, 0))}
                  </span>
                )}
              </span>
            </div>
            <div className="h-1.5 bg-bg-card rounded-full overflow-hidden">
              <div
                className="h-full progress-flow rounded-full transition-all duration-500"
                style={{ width: `${((currentIdx + 1) / STEPS.length) * 100}%` }}
              ></div>
            </div>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="max-w-2xl mx-auto">
      <div className="mb-8">
        <button
          onClick={() => setView({ page: 'list' })}
          className="text-tx-secondary hover:text-accent-cyan transition-colors text-sm mb-4 font-mono"
        >
          ← 返回列表
        </button>
        <h2 className="text-2xl font-bold mb-1">上传音频/视频</h2>
        <p className="text-sm text-tx-secondary font-mono">// 支持 MP3 / WAV / MP4 / MOV 等格式</p>
      </div>

      <div
        onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
        onClick={() => inputRef.current?.click()}
        className={`border-2 border-dashed rounded-xl p-12 text-center cursor-pointer transition-all ${
          dragOver ? 'border-accent-cyan bg-accent-cyan/5' : 'border-bg-border hover:border-accent-cyan/50'
        }`}
      >
        <input
          ref={inputRef}
          type="file"
          className="hidden"
          accept="audio/*,video/*"
          onChange={(e) => e.target.files[0] && handleFile(e.target.files[0])}
        />
        {file ? (
          <div>
            <div className="text-4xl mb-3">{file.type.startsWith('video') ? '🎬' : '🎵'}</div>
            <p className="font-medium text-accent-cyan">{file.name}</p>
            <p className="text-sm text-tx-secondary mt-1 font-mono">
              {(file.size / 1024 / 1024).toFixed(1)} MB
            </p>
            <p className="text-xs text-accent-cyan mt-2 font-mono">✓ 已选择，点击可重新选择</p>
          </div>
        ) : (
          <div>
            <div className="text-5xl mb-4 opacity-40 animate-pulse">📁</div>
            <p className="text-tx-primary text-lg font-medium mb-2">点击此处选择文件</p>
            <p className="text-sm text-tx-secondary">或拖拽文件到此处</p>
            <p className="text-xs text-tx-dim mt-3 font-mono">支持 MP3 / WAV / MP4 / MOV / MKV</p>
          </div>
        )}
      </div>

      <div className="mt-6 space-y-4">
        <div>
          <label className="block text-sm text-tx-secondary mb-2 font-mono">项目名称</label>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            disabled={!file}
            className="w-full bg-bg-card border border-bg-border rounded-lg px-4 py-2.5 text-tx-primary focus:border-accent-cyan focus:outline-none transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            placeholder={file ? '给这个项目起个名字' : '请先选择文件'}
          />
        </div>

        {error && (
          <div className="bg-accent-red/10 border border-accent-red/30 rounded-lg px-4 py-3 text-sm text-accent-red">
            {error}
          </div>
        )}

        <div className="flex gap-3">
          <button
            onClick={() => setView({ page: 'list' })}
            className="px-6 py-2.5 rounded-lg border border-bg-border text-tx-secondary hover:border-tx-secondary transition-colors"
          >
            取消
          </button>
          <button
            onClick={handleSubmit}
            disabled={!file}
            className="btn-glow flex-1 py-2.5 rounded-lg font-medium text-bg-base disabled:opacity-30 disabled:cursor-not-allowed disabled:bg-bg-border disabled:bg-none"
          >
            {file ? '上传并开始分析' : '请先选择文件'}
          </button>
        </div>
      </div>
    </div>
  )
}
