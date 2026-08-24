import { useState, useEffect } from 'react'
import ProjectList from './pages/ProjectList'
import Upload from './pages/Upload'
import Confirmation from './pages/Confirmation'
import Review from './pages/Review'
import Cover from './pages/Cover'
import { getBranding } from './api/client'

// 与后端 config.BRANDING_SECRET 对应(开源项目里公开,属"增加难度"而非绝对防护)
const BRANDING_SECRET = 'cunsub-czlab-2026-br4nd'

async function verifySignature(data, signature) {
  try {
    const payload = JSON.stringify(data)
    const enc = new TextEncoder()
    const key = await crypto.subtle.importKey(
      'raw', enc.encode(BRANDING_SECRET), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']
    )
    const sig = await crypto.subtle.sign('HMAC', key, enc.encode(payload))
    const hex = Array.from(new Uint8Array(sig)).map(b => b.toString(16).padStart(2, '0')).join('')
    return hex === signature
  } catch {
    return false
  }
}

function Footer() {
  const [branding, setBranding] = useState(null)
  const [tampered, setTampered] = useState(false)

  useEffect(() => {
    let mounted = true
    let retries = 0
    const MAX_RETRIES = 12

    async function load() {
      if (!mounted) return
      const res = await getBranding()
      if (!mounted) return
      if (res) {
        // 后端已返回: 校验签名
        const ok = await verifySignature(res.data, res.signature)
        if (!mounted) return
        if (ok) setBranding(res.data)
        else setTampered(true) // 签名不匹配才是真的被篡改
        return
      }
      // 后端未就绪(start 时浏览器先于后端打开), 稍后重试
      retries += 1
      if (retries < MAX_RETRIES) setTimeout(load, 1500)
    }
    load()
    return () => { mounted = false }
  }, [])

  // 后端未下发或校验失败:显示警示而非被抹掉的空白
  if (tampered || !branding) {
    return (
      <footer className="border-t border-bg-border bg-bg-base/80 backdrop-blur mt-auto">
        <div className="max-w-6xl mx-auto px-6 py-4 text-center">
          <span className="text-xs text-accent-red font-mono">
            ⚠ 版权信息校验失败 · Powered by CunSub (czlab.dev)
          </span>
        </div>
      </footer>
    )
  }

  return (
    <footer className="border-t border-bg-border bg-bg-base/80 backdrop-blur mt-auto">
      <div className="max-w-6xl mx-auto px-6 py-4 text-center text-xs font-mono">
        <span className="text-tx-dim">©{new Date().getFullYear()} {branding.app_name} ·</span>{' '}
        <a
          href={branding.lab_url}
          target="_blank"
          rel="noopener noreferrer"
          className="text-tx-secondary hover:text-accent-cyan transition-colors"
        >
          {branding.lab_name}
        </a>
        <span className="text-tx-dim"> · </span>
        <a
          href={branding.blog_url}
          target="_blank"
          rel="noopener noreferrer"
          className="text-tx-secondary hover:text-accent-cyan transition-colors"
        >
          {branding.blog_name}
        </a>
      </div>
    </footer>
  )
}

function Header({ onHome }) {
  return (
    <header className="border-b border-bg-border bg-bg-base/80 backdrop-blur sticky top-0 z-50">
      <div className="max-w-6xl mx-auto px-6 py-4 flex items-center justify-between">
        <button onClick={onHome} className="flex items-center gap-3 group">
          <img
            src="/cunsub-logo-icon.png"
            alt="CunSub Logo"
            className="w-9 h-9 rounded-lg bg-bg-card border border-accent-cyan/40 p-0.5 group-hover:animate-glow"
          />
          <div className="text-left">
            <h1 className="text-lg font-bold gradient-text leading-tight">CunSub</h1>
            <p className="text-xs text-tx-secondary font-mono">村长实验室 · AI字幕工作流</p>
          </div>
        </button>
        <div className="terminal-tag border-accent-cyan/30 text-accent-cyan">
          v1.0
        </div>
      </div>
    </header>
  )
}

export default function App() {
  const [view, setView] = useState({ page: 'list', projectId: null })

  const goHome = () => setView({ page: 'list', projectId: null })

  const renderPage = () => {
    switch (view.page) {
      case 'list':
        return <ProjectList setView={setView} />
      case 'upload':
        return <Upload setView={setView} />
      case 'confirmation':
        return <Confirmation projectId={view.projectId} setView={setView} />
      case 'review':
        return <Review projectId={view.projectId} setView={setView} />
      case 'cover':
        return <Cover projectId={view.projectId} setView={setView} />
      default:
        return <ProjectList setView={setView} />
    }
  }

  return (
    <div className="min-h-screen grid-bg flex flex-col">
      <Header onHome={goHome} />
      <main className="max-w-6xl mx-auto px-6 py-8 w-full flex-1">
        {renderPage()}
      </main>
      <Footer />
    </div>
  )
}
