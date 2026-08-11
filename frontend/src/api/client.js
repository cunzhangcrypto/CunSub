const BASE = '/api'

export async function uploadFile(file, name) {
  const form = new FormData()
  form.append('file', file)
  if (name) form.append('name', name)
  const res = await fetch(`${BASE}/projects/upload`, { method: 'POST', body: form })
  if (!res.ok) throw new Error('上传文件失败')
  return res.json()
}

export async function extractAudio(id) {
  const res = await fetch(`${BASE}/projects/${id}/extract`, { method: 'POST' })
  if (!res.ok) throw new Error('提取音频失败')
  return res.json()
}

export async function uploadToGemini(id) {
  const res = await fetch(`${BASE}/projects/${id}/upload-gemini`, { method: 'POST' })
  if (!res.ok) {
    let msg = '上传到 Gemini 失败'
    try {
      const err = await res.json()
      msg = err.detail || msg
    } catch {}
    throw new Error(msg)
  }
  return res.json()
}

export async function checkGeminiHealth() {
  try {
    const res = await fetch(`${BASE}/health/gemini`, { method: 'GET' })
    return await res.json()
  } catch {
    return { ok: false, message: '无法连接后端服务' }
  }
}

export async function getBranding() {
  try {
    const res = await fetch(`${BASE}/branding`, { method: 'GET' })
    if (!res.ok) return null
    return await res.json()
  } catch {
    return null
  }
}

export function subscribeProgress(id, onProgress) {
  const es = new EventSource(`${BASE}/projects/${id}/progress`)
  es.onmessage = (e) => {
    try {
      const data = JSON.parse(e.data)
      onProgress(data)
      if (data.percent >= 100) es.close()
    } catch (err) {}
  }
  es.onerror = () => es.close()
  return es
}

export async function listProjects() {
  const res = await fetch(`${BASE}/projects`)
  return res.json()
}

export async function getProject(id) {
  const res = await fetch(`${BASE}/projects/${id}`)
  return res.json()
}

export async function deleteProject(id) {
  await fetch(`${BASE}/projects/${id}`, { method: 'DELETE' })
}

export async function startUnderstanding(id) {
  const res = await fetch(`${BASE}/workflow/${id}/understand`, { method: 'POST' })
  if (!res.ok) throw new Error('理解失败')
  return res.json()
}

export async function getUnderstanding(id) {
  const res = await fetch(`${BASE}/workflow/${id}/understanding`)
  return res.json()
}

export async function confirmTerms(id, termsMapping, additionalTerms, termCorrections) {
  const res = await fetch(`${BASE}/workflow/${id}/confirm`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      terms_mapping: termsMapping,
      additional_terms: additionalTerms,
      term_corrections: termCorrections || {}
    })
  })
  if (!res.ok) throw new Error('确认失败')
  return res.json()
}

export async function startGeneration(id) {
  const res = await fetch(`${BASE}/workflow/${id}/generate`, { method: 'POST' })
  if (!res.ok) {
    let msg = '生成失败'
    try {
      const err = await res.json()
      msg = err.detail || msg
    } catch {}
    throw new Error(msg)
  }
  return res.json()
}

export async function getSubtitles(id) {
  const res = await fetch(`${BASE}/workflow/${id}/subtitles`)
  return res.json()
}

export async function setSubtitleOffset(id, offsetMs) {
  const res = await fetch(`${BASE}/workflow/${id}/offset?offset_ms=${offsetMs}`, { method: 'POST' })
  if (!res.ok) throw new Error('设置偏移失败')
  return res.json()
}

export async function editSubtitle(id, idx, text) {
  const res = await fetch(`${BASE}/workflow/${id}/subtitles/${idx}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text })
  })
  return res.json()
}

export async function exportSubtitles(id, format) {
  const res = await fetch(`${BASE}/export/${id}?format=${format}`, { method: 'POST' })
  if (!res.ok) {
    let msg = '导出失败'
    try {
      const err = await res.json()
      msg = err.detail || msg
    } catch {}
    throw new Error(msg)
  }
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  // 优先用后端下发的文件名(带品牌标识 _by_cunsub),解析 Content-Disposition 头
  const cd = res.headers.get('Content-Disposition') || ''
  const match = cd.match(/filename="?([^";]+)"?/)
  a.download = match ? match[1] : `subtitles.${format}`
  a.click()
  URL.revokeObjectURL(url)
}

export function getAudioClipUrl(id, start) {
  return `${BASE}/projects/${id}/audio-clip?start=${start}`
}

export function parseHintToSeconds(hint) {
  if (!hint) return 0
  const match = hint.match(/(\d+):(\d+)/)
  if (match) return parseInt(match[1]) * 60 + parseInt(match[2])
  const minMatch = hint.match(/(\d+)\s*分/)
  if (minMatch) return parseInt(minMatch[1]) * 60
  const secMatch = hint.match(/(\d+)\s*秒/)
  if (secMatch) return parseInt(secMatch[1])
  return 0
}
