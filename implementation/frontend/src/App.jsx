import { useState, useRef, useEffect } from 'react'

// ── Highlight query words inside a chunk of text ───────────────────────────
function HighlightedText({ text, query }) {
  if (!query?.trim()) return <>{text}</>

  const escaped = [...new Set(query.split(/\s+/).filter(w => w.length > 3))]
    .map(w => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))

  if (!escaped.length) return <>{text}</>

  // split() with a capture group interleaves matches at odd indices
  const parts = text.split(new RegExp(`(${escaped.join('|')})`, 'gi'))

  return (
    <>
      {parts.map((part, i) =>
        i % 2 === 1
          ? <mark key={i}>{part}</mark>
          : <span key={i}>{part}</span>
      )}
    </>
  )
}

// ── One retrieved chunk card ───────────────────────────────────────────────
function SourceCard({ source, index, query }) {
  const [expanded, setExpanded] = useState(false)
  const PREVIEW = 260
  const long = source.content.length > PREVIEW
  const displayText = expanded || !long
    ? source.content
    : source.content.slice(0, PREVIEW) + '…'

  return (
    <div className="source-card">
      <div className="source-card-header">
        <span className="source-badge">#{index + 1}</span>
        <span className="source-title">{source.title}</span>
        {source.url && (
          <a
            className="source-link"
            href={source.url}
            target="_blank"
            rel="noopener noreferrer"
          >
            ↗
          </a>
        )}
      </div>

      <p className="source-text">
        <HighlightedText text={displayText} query={query} />
      </p>

      {long && (
        <button className="toggle-btn" onClick={() => setExpanded(v => !v)}>
          {expanded ? '▲ Show less' : '▼ Show more'}
        </button>
      )}
    </div>
  )
}

// ── Request timeline bar ───────────────────────────────────────────
function TimingBar({ timings }) {
  if (!timings) return null
  const { retrieval, llm, total } = timings
  const retPct = Math.round((retrieval / total) * 100)
  const llmPct = 100 - retPct

  return (
    <div className="timing-wrap">
      <div className="timing-track">
        <div
          className="timing-seg retrieval-seg"
          style={{ width: `${retPct}%` }}
          title={`Embed + FAISS search: ${retrieval}s`}
        />
        <div
          className="timing-seg llm-seg"
          style={{ width: `${llmPct}%` }}
          title={`LLM generation: ${llm}s`}
        />
      </div>
      <div className="timing-labels">
        <span className="timing-label retrieval-label">
          <span className="dot retrieval-dot" /> Retrieval&nbsp;{retrieval}s
        </span>
        <span className="timing-label llm-label">
          <span className="dot llm-dot" /> LLM&nbsp;{llm}s
        </span>
        <span className="timing-total">Total&nbsp;{total}s</span>
      </div>
    </div>
  )
}

// ── Animated typing dots ───────────────────────────────────────────────────
function TypingDots() {
  return (
    <span className="typing-dots">
      <span /><span /><span />
    </span>
  )
}

// ── Single message bubble ─────────────────────────────────────────────────
function ChatMessage({ msg, isActive, onClick }) {
  const isUser = msg.role === 'user'
  const clickable = !isUser && msg.sources

  return (
    <div
      className={[
        'chat-msg',
        isUser ? 'user' : 'bot',
        isActive ? 'active' : '',
        clickable ? 'clickable' : '',
      ].join(' ')}
      onClick={clickable ? onClick : undefined}
      title={clickable ? 'Click to inspect sources' : undefined}
    >
      <div className="bubble">
        <p>{msg.content}</p>
        {!isUser && (
          <>
            <TimingBar timings={msg.timings} />
            <div className="bubble-meta">
              {msg.sources?.length > 0 && (
                <span className="sources-badge">{msg.sources.length} chunks</span>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  )
}

// ── App ────────────────────────────────────────────────────────────────────
export default function App() {
  const [messages,  setMessages]  = useState([])
  const [input,     setInput]     = useState('')
  const [loading,   setLoading]   = useState(false)
  const [activeIdx, setActiveIdx] = useState(null)
  const bottomRef = useRef(null)

  // auto-scroll chat to bottom
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  // sources + query for the currently selected bot message
  const activeSources = activeIdx !== null ? (messages[activeIdx]?.sources ?? null) : null
  const activeQuery   = activeIdx !== null ? (messages[activeIdx - 1]?.content ?? '') : ''

  async function send(e) {
    e.preventDefault()
    const question = input.trim()
    if (!question || loading) return

    setInput('')
    const userIdx = messages.length
    setMessages(prev => [...prev, { role: 'user', content: question }])
    setLoading(true)

    try {
      const res = await fetch('/chat', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ question }),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }))
        throw new Error(err.detail ?? `HTTP ${res.status}`)
      }
      const data = await res.json()
      const botIdx = userIdx + 1
      setMessages(prev => [...prev, {
        role:    'bot',
        content: data.answer,
        timings: data.timings ?? null,
        sources: data.sources ?? [],
      }])
      setActiveIdx(botIdx)
    } catch (err) {
      setMessages(prev => [...prev, {
        role:         'bot',
        content:      `⚠ ${err.message ?? 'Could not reach the API. Is the backend running?'}`,
        responseTime: null,
        sources:      [],
      }])
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="layout">

      {/* ── Left: Chat ──────────────────────────────────────────────────── */}
      <div className="chat-pane">
        <div className="chat-header">
          <h1>Frieren Grimoire</h1>
          <p>Chronicles Indexed with RAG · FAISS · Ollama</p>
        </div>

        <div className="messages-area">
          {messages.length === 0 && !loading && (
            <div className="placeholder">
              Ask anything about <em>Frieren: Beyond Journey's End</em>
            </div>
          )}

          {messages.map((msg, i) => (
            <ChatMessage
              key={i}
              msg={msg}
              isActive={i === activeIdx}
              onClick={() => setActiveIdx(i)}
            />
          ))}

          {loading && (
            <div className="chat-msg bot">
              <div className="bubble"><TypingDots /></div>
            </div>
          )}

          <div ref={bottomRef} />
        </div>

        <form className="input-row" onSubmit={send}>
          <input
            value={input}
            onChange={e => setInput(e.target.value)}
            placeholder="Ask about Frieren…"
            disabled={loading}
            autoFocus
          />
          <button type="submit" disabled={loading || !input.trim()}>
            Send
          </button>
        </form>
      </div>

      {/* ── Right: Retrieved Chunks ─────────────────────────────────────── */}
      <div className="sources-pane">
        <div className="sources-header">
          <h2>Retrieved Chunks</h2>
          {activeSources && (
            <span className="chunk-count">{activeSources.length} chunks</span>
          )}
        </div>

        {activeSources === null ? (
          <p className="sources-placeholder">
            After each answer, click any bot message to inspect the wiki
            chunks the RAG system retrieved. Query keywords are highlighted.
          </p>
        ) : activeSources.length === 0 ? (
          <p className="sources-placeholder">No sources found for this query.</p>
        ) : (
          <div className="sources-list">
            {activeSources.map((src, i) => (
              <SourceCard key={i} source={src} index={i} query={activeQuery} />
            ))}
          </div>
        )}
      </div>

    </div>
  )
}
