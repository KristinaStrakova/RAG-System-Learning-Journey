# RAG-System-Learning-Journey

## Prototype Pipeline (Used in This Repo)

This prototype uses a local Retrieval-Augmented Generation (RAG) pipeline with a scraped Frieren wiki dataset, FAISS retrieval, and an Ollama LLM.

### 1) Data collection
- Script: `data_scraper.py`
- Source: Frieren Fandom MediaWiki API
- Output: `frieren_dataset.json`
- What it does:
	- Fetches all page titles from the wiki API.
	- Pulls each page's parsed HTML.
	- Strips HTML to plain text with BeautifulSoup.
	- Saves records as: title, content, url.

### 2) Show structure
- Each show lives in `shows/<show_name>/` with two required files:
  - `dataset.json`: The wiki data scraped from the wiki API
  - `faiss_index/`: Pre-built FAISS index (run `build_index.py` once to create)
- Example: `shows/frieren_both_seasons/` contains:
  - `dataset.json`
  - `faiss_index/` (with `index.faiss` and `index.pkl` inside)

### 3) Backend startup
- API: `implementation/api.py` (FastAPI)
- What it does on startup:
	- Loads the embedding model (`BAAI/bge-small-en-v1.5`).
	- Scans `shows/` folder for shows with pre-built FAISS indexes.
	- Creates retriever with `k=5` top chunks.
	- Connects to local Ollama model (`mistral` by default).

### 4) Query-time RAG flow
For each user question posted to `/chat`:
1. User selects a show from the picker on initial page load.
2. Retrieve top-k relevant chunks from that show's FAISS index.
3. Concatenate retrieved chunks as context.
4. Inject context + question into a constrained prompt.
5. Generate answer with Ollama LLM.
6. Return answer + source chunks + timings (retrieval, llm, total).

### 5) Frontend interaction
- UI: `implementation/frontend/src/App.jsx`
- What it shows:
	- **Initial screen:** Show picker listing all available shows from `/shows/` (only those with pre-built FAISS indexes).
	- Click to select a show → enters chat immediately.
	- **Chat screen:** Chat interface with "Switch to different show" button in header.
	- Returned answer from backend.
	- Retrieved chunks for each bot response.
	- Query-term highlighting in chunk text.
	- Retrieval vs LLM timing bar.

## Run the Prototype

Open two terminals.

Terminal 1 (backend, from repo root):

```bash
uvicorn implementation.api:app --reload
```

Terminal 2 (frontend):

```bash
cd implementation
cd frontend
npm run dev
```

## End-to-End Summary

`Wiki API → JSON dataset → Chunking → Embeddings → FAISS index (in shows/<show>/faiss_index/) → User picks show → Retrieve top-k → Prompt with context → Ollama generation → Answer + sources + timings in UI`