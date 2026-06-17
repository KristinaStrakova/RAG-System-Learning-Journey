import { useState, useRef, useEffect } from 'react'

// ── Show Picker Screen ───────────────────────────────────────────────────
function ShowPicker({ shows, loading, onSelect, onAddShow }) {
  return (
    <div className="show-picker-overlay">
      <div className="show-picker-modal">
        <h1>Frieren Grimoire</h1>
        <p className="picker-subtitle">Select a show to begin</p>

        {loading ? (
          <div className="picker-loading">Loading shows…</div>
        ) : shows.length === 0 ? (
          <div className="picker-error">
            No shows found in <code>/shows</code> folder
          </div>
        ) : (
          <div className="show-list">
            {shows.map(show => (
              <button
                key={show.id}
                className="show-item"
                onClick={() => onSelect(show.id)}
              >
                <span className="show-name">{show.name}</span>
              </button>
            ))}
          </div>
        )}

        <button className="add-show-btn" onClick={onAddShow}>
          Add another show
        </button>
      </div>
    </div>
  )
}

function AddShowPanel({
  fandomUrl,
  setFandomUrl,
  pages,
  pageFilter,
  setPageFilter,
  selectedTitles,
  onToggleTitle,
  onLoadPages,
  onSelectAllFiltered,
  onClearSelection,
  onCreateShow,
  onBack,
  pagesLoading,
  creatingShow,
  error,
}) {
  const filteredPages = pageFilter.trim()
    ? pages.filter(page => page.title.toLowerCase().includes(pageFilter.toLowerCase()))
    : pages

  return (
    <div className="show-picker-overlay">
      <div className="show-picker-modal add-show-modal">
        <h1>Add A Show</h1>
        <p className="picker-subtitle">Paste any Fandom URL and pick chapters to include</p>

        <div className="add-show-input-row">
          <input
            value={fandomUrl}
            onChange={e => setFandomUrl(e.target.value)}
            placeholder="https://deadpool.fandom.com/wiki/Special:AllPages"
            disabled={pagesLoading || creatingShow}
          />
          <button onClick={onLoadPages} disabled={!fandomUrl.trim() || pagesLoading || creatingShow}>
            {pagesLoading ? 'Loading…' : 'Load chapters'}
          </button>
        </div>

        {error && <div className="picker-error">{error}</div>}

        {pages.length > 0 && (
          <>
            <div className="chapter-toolbar">
              <input
                value={pageFilter}
                onChange={e => setPageFilter(e.target.value)}
                placeholder="Filter chapters"
                disabled={creatingShow}
              />
              <button onClick={onSelectAllFiltered} disabled={filteredPages.length === 0 || creatingShow}>
                Select visible
              </button>
              <button onClick={onClearSelection} disabled={selectedTitles.size === 0 || creatingShow}>
                Clear
              </button>
            </div>

            <div className="chapter-count">
              {selectedTitles.size} selected / {pages.length} total
            </div>

            <div className="chapter-list">
              {filteredPages.map(page => (
                <label key={page.title} className="chapter-item">
                  <input
                    type="checkbox"
                    checked={selectedTitles.has(page.title)}
                    onChange={() => onToggleTitle(page.title)}
                    disabled={creatingShow}
                  />
                  <span>{page.title}</span>
                </label>
              ))}
            </div>

            <button
              className="create-show-btn"
              onClick={onCreateShow}
              disabled={selectedTitles.size === 0 || creatingShow}
            >
              {creatingShow ? 'Creating show…' : 'Create show from selected chapters'}
            </button>
          </>
        )}

        <button className="back-btn" onClick={onBack} disabled={pagesLoading || creatingShow}>
          Back to show list
        </button>
      </div>
    </div>
  )
}

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
  const [shows, setShows] = useState([])
  const [selectedShow, setSelectedShow] = useState('')
  const [showsLoading, setShowsLoading] = useState(true)
  const [pickerMode, setPickerMode] = useState('select')
  const [fandomUrl, setFandomUrl] = useState('')
  const [pages, setPages] = useState([])
  const [pageFilter, setPageFilter] = useState('')
  const [selectedTitles, setSelectedTitles] = useState(new Set())
  const [pagesLoading, setPagesLoading] = useState(false)
  const [creatingShow, setCreatingShow] = useState(false)
  const [addShowError, setAddShowError] = useState('')
  const bottomRef = useRef(null)

  // auto-scroll chat to bottom
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  async function loadShows() {
    try {
      const res = await fetch('/shows')
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setShows(data.shows ?? [])
    } catch {
      setShows([])
    } finally {
      setShowsLoading(false)
    }
  }

  // load show choices from backend
  useEffect(() => {
    loadShows()
  }, [])

  // Handle show selection from picker
  const handleShowSelect = (showId) => {
    setSelectedShow(showId)
    setMessages([])
  }

  const handleToggleTitle = (title) => {
    setSelectedTitles(prev => {
      const next = new Set(prev)
      if (next.has(title)) {
        next.delete(title)
      } else {
        next.add(title)
      }
      return next
    })
  }

  const handleSelectAllFiltered = () => {
    const visible = pageFilter.trim()
      ? pages.filter(page => page.title.toLowerCase().includes(pageFilter.toLowerCase()))
      : pages

    setSelectedTitles(prev => {
      const next = new Set(prev)
      visible.forEach(page => next.add(page.title))
      return next
    })
  }

  const handleClearSelection = () => {
    setSelectedTitles(new Set())
  }

  const handleLoadPages = async () => {
    const url = fandomUrl.trim()
    if (!url) return

    setPagesLoading(true)
    setAddShowError('')
    setPages([])
    setSelectedTitles(new Set())

    try {
      const res = await fetch('/shows/preview-pages', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ fandom_url: url }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        throw new Error(data.detail || `HTTP ${res.status}`)
      }
      setPages(data.pages ?? [])
    } catch (err) {
      setAddShowError(err.message ?? 'Could not load chapters from the provided URL.')
    } finally {
      setPagesLoading(false)
    }
  }

  const handleCreateShow = async () => {
    if (selectedTitles.size === 0) return

    setCreatingShow(true)
    setAddShowError('')
    try {
      const res = await fetch('/shows/create-from-fandom', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          fandom_url: fandomUrl.trim(),
          selected_titles: Array.from(selectedTitles),
        }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        throw new Error(data.detail || `HTTP ${res.status}`)
      }

      await loadShows()
      setPickerMode('select')
      setPages([])
      setSelectedTitles(new Set())
      setPageFilter('')
      setFandomUrl('')
      handleShowSelect(data.show?.id || '')
    } catch (err) {
      setAddShowError(err.message ?? 'Could not create show from selected chapters.')
    } finally {
      setCreatingShow(false)
    }
  }

  const handleBackToShowList = () => {
    setPickerMode('select')
    setPages([])
    setSelectedTitles(new Set())
    setPageFilter('')
    setAddShowError('')
  }

  // Show picker if no show selected yet
  if (!selectedShow) {
    if (pickerMode === 'add') {
      return (
        <AddShowPanel
          fandomUrl={fandomUrl}
          setFandomUrl={setFandomUrl}
          pages={pages}
          pageFilter={pageFilter}
          setPageFilter={setPageFilter}
          selectedTitles={selectedTitles}
          onToggleTitle={handleToggleTitle}
          onLoadPages={handleLoadPages}
          onSelectAllFiltered={handleSelectAllFiltered}
          onClearSelection={handleClearSelection}
          onCreateShow={handleCreateShow}
          onBack={handleBackToShowList}
          pagesLoading={pagesLoading}
          creatingShow={creatingShow}
          error={addShowError}
        />
      )
    }

    return (
      <ShowPicker
        shows={shows}
        loading={showsLoading}
        onSelect={handleShowSelect}
        onAddShow={() => setPickerMode('add')}
      />
    )
  }

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
        body:    JSON.stringify({
          question,
          show: selectedShow || null,
        }),
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
          <div className="show-selector">
            <span className="current-show">{shows.find(s => s.id === selectedShow)?.name || selectedShow}</span>
            <button className="switch-show-btn" onClick={() => setSelectedShow('')} title="Switch to different show">
              Switch to different show
            </button>
          </div>
        </div>

        <div className="messages-area">
          {messages.length === 0 && !loading && (
            <div className="placeholder">
              Ask anything from the selected show
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
            placeholder="Ask a question from the selected show…"
            disabled={loading}
            autoFocus
          />
          <button
            type="submit"
            disabled={loading || !input.trim()}
          >
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
