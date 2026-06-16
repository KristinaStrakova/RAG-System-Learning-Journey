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

### 2) Document preparation and indexing
- Script: `implementation/build_index.py`
- Input: `frieren_dataset.json`
- Output: `faiss_index/` (vector index files)
- What it does:
	- Converts each JSON record into a LangChain Document.
	- Skips very short content pages.
	- Prepends article title into chunk text.
	- Splits documents with RecursiveCharacterTextSplitter
		- chunk size: 700 chars
		- overlap: 100 chars
	- Embeds chunks using `BAAI/bge-small-en-v1.5` (normalized embeddings, CPU).
	- Builds and saves a local FAISS index.

### 3) Backend startup
- API: `implementation/api.py` (FastAPI)
- What it does on startup:
	- Loads the same embedding model (`BAAI/bge-small-en-v1.5`).
	- Loads the saved FAISS index from `faiss_index/`.
	- Creates retriever with `k=5` top chunks.
	- Connects to local Ollama model (`mistral` by default).

### 4) Query-time RAG flow
For each user question posted to `/chat`:
1. Retrieve top-k relevant chunks from FAISS.
2. Concatenate retrieved chunks as context.
3. Inject context + question into a constrained prompt.
4. Generate answer with Ollama LLM.
5. Return answer + source chunks + timings (retrieval, llm, total).

### 5) Frontend interaction
- UI: `implementation/frontend/src/App.jsx`
- What it shows:
	- Chat interface for user questions.
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

`Wiki API -> JSON dataset -> Chunking -> Embeddings -> FAISS index -> Retrieve top-k -> Prompt with context -> Ollama generation -> Answer + sources + timings in UI`