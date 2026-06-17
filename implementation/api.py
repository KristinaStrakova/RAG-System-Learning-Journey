"""
FastAPI backend for the Frieren Wiki RAG Chat.

Run from the workspace root:
    uvicorn implementation.api:app --reload
or from the implementation/ folder:
    uvicorn api:app --reload

Requires the faiss_index/ folder built by build_index.py.
Requires Ollama running locally with a model pulled:
    ollama pull mistral
"""

import os
import re
import json
import time
import shutil
from pathlib import Path
from typing import Any
from contextlib import asynccontextmanager
from urllib.parse import quote, urlparse

import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_ollama import OllamaLLM
from langchain_core.documents import Document
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_text_splitters import RecursiveCharacterTextSplitter

# ── Config ────────────────────────────────────────────────────────────────────

SHOWS_DIR = "shows"
EMBED_MODEL = "BAAI/bge-small-en-v1.5"
LLM_MODEL   = "mistral"
TOP_K       = 3
CHUNK_SIZE = 700
CHUNK_OVERLAP = 100

PROMPT = PromptTemplate(
    input_variables=["context", "question"],
    template="""You are a helpful assistant who answers questions about the anime and manga series "Frieren: Beyond Journey's End".
Use ONLY the information in the context passages below to answer.
If the answer is not in the context, say "I don't have enough information about that in the wiki."
Always be concise and friendly.

Context:
{context}

Question: {question}

Answer:""",
)

# ── Globals (populated at startup) ───────────────────────────────────────────

_embeddings = None
_default_retriever = None
_dataset_retrievers: dict[str, Any] = {}
_llm_chain = None   # PROMPT | llm | parser  (no retriever — timed separately)
_SCRAPER_USER_AGENT = "FrierenRAG/1.0 (show builder)"


def _find_shows_dir() -> Path:
    """Locate the shows folder regardless of CWD."""
    here = Path(__file__).parent
    candidates = [
        Path(os.getcwd()) / SHOWS_DIR,
        here.parent / SHOWS_DIR,
        here / SHOWS_DIR,
    ]
    for path in candidates:
        if path.exists() and path.is_dir():
            return path
    return candidates[0]


def _format_docs(docs: list) -> str:
    return "\n\n---\n\n".join(doc.page_content for doc in docs)


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", name.lower()).strip("_")
    return slug or "dataset"


def _normalize_fandom_base(url: str) -> tuple[str, str]:
    """
    Convert any fandom URL to canonical base: https://{show}.fandom.com/wiki/
    Returns (wiki_base, suggested_show_name).
    """
    raw = url.strip()
    if not raw:
        raise HTTPException(status_code=400, detail="Fandom URL is required.")

    if not re.match(r"^https?://", raw, flags=re.IGNORECASE):
        raw = f"https://{raw}"

    parsed = urlparse(raw)
    host = parsed.netloc.lower()
    if not host.endswith("fandom.com"):
        raise HTTPException(status_code=400, detail="URL must point to a fandom.com wiki.")

    labels = host.split(".")
    if len(labels) < 3:
        raise HTTPException(status_code=400, detail="Invalid fandom host format.")

    show_key = labels[0]
    if not show_key:
        raise HTTPException(status_code=400, detail="Could not infer show name from URL.")

    wiki_base = f"https://{show_key}.fandom.com/wiki/"
    suggested_show_name = _slugify(show_key)
    return wiki_base, suggested_show_name


def _wiki_api_url(wiki_base: str) -> str:
    parsed = urlparse(wiki_base)
    return f"{parsed.scheme}://{parsed.netloc}/api.php"


def _fetch_all_fandom_titles(wiki_base: str) -> list[str]:
    api_url = _wiki_api_url(wiki_base)
    headers = {"User-Agent": _SCRAPER_USER_AGENT}

    titles: list[str] = []
    apcontinue = None

    while True:
        params = {
            "action": "query",
            "list": "allpages",
            "apnamespace": "0",
            "aplimit": "max",
            "format": "json",
        }
        if apcontinue:
            params["apcontinue"] = apcontinue

        response = requests.get(api_url, params=params, headers=headers, timeout=30)
        response.raise_for_status()
        payload = response.json()

        page_titles = [p.get("title", "").strip() for p in payload.get("query", {}).get("allpages", [])]
        titles.extend([t for t in page_titles if t])

        continuation = payload.get("continue")
        if not continuation:
            break
        apcontinue = continuation.get("apcontinue")
        if not apcontinue:
            break

    seen = set()
    unique_titles = []
    for title in titles:
        if title in seen:
            continue
        seen.add(title)
        unique_titles.append(title)
    return unique_titles


def _fetch_page_content(wiki_base: str, title: str) -> tuple[str | None, str]:
    api_url = _wiki_api_url(wiki_base)
    headers = {"User-Agent": _SCRAPER_USER_AGENT}
    params = {
        "action": "parse",
        "page": title,
        "prop": "text",
        "format": "json",
    }

    response = requests.get(api_url, params=params, headers=headers, timeout=30)
    response.raise_for_status()
    payload = response.json()

    html = payload.get("parse", {}).get("text", {}).get("*")
    if not html:
        return None, ""

    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(separator=" ", strip=True)
    text = re.sub(r"\s+", " ", text).strip()

    page_url = f"{wiki_base}{quote(title.replace(' ', '_'))}"
    return text, page_url


def _create_show_from_selected_titles(
    fandom_url: str,
    selected_titles: list[str],
    show_name: str | None = None,
) -> dict[str, Any]:
    global _embeddings

    if _embeddings is None:
        raise HTTPException(status_code=503, detail="Embeddings are not ready yet. Try again in a moment.")

    wiki_base, suggested_show_name = _normalize_fandom_base(fandom_url)
    folder_name = _slugify(show_name or suggested_show_name)
    if not folder_name:
        raise HTTPException(status_code=400, detail="Show name is invalid.")

    cleaned_titles = [t.strip() for t in selected_titles if t and t.strip()]
    if not cleaned_titles:
        raise HTTPException(status_code=400, detail="Select at least one chapter/page.")

    shows_dir = _find_shows_dir()
    shows_dir.mkdir(parents=True, exist_ok=True)
    show_dir = shows_dir / folder_name

    if show_dir.exists():
        raise HTTPException(status_code=400, detail=f"Show '{folder_name}' already exists.")

    show_dir.mkdir(parents=True, exist_ok=False)

    records: list[dict[str, str]] = []
    skipped = 0

    try:
        for title in cleaned_titles:
            try:
                content, page_url = _fetch_page_content(wiki_base, title)
            except Exception:
                skipped += 1
                continue

            if not content or len(content) < 80:
                skipped += 1
                continue

            records.append({
                "title": title,
                "content": content,
                "url": page_url,
            })

        if not records:
            raise HTTPException(status_code=400, detail="No usable content found from selected pages.")

        dataset_path = show_dir / "dataset.json"
        with dataset_path.open("w", encoding="utf-8") as handle:
            json.dump(records, handle, ensure_ascii=False, indent=2)

        docs = _to_documents(records)
        chunks = _chunk_documents(docs)
        if not chunks:
            raise HTTPException(status_code=400, detail="Selected pages did not produce enough content to index.")

        vectorstore = FAISS.from_documents(chunks, _embeddings)
        index_dir = show_dir / "faiss_index"
        index_dir.mkdir(parents=True, exist_ok=True)
        vectorstore.save_local(str(index_dir))

        show_id = _slugify(folder_name)
        _dataset_retrievers.pop(show_id, None)

        return {
            "id": show_id,
            "name": folder_name,
            "dataset_path": str(dataset_path),
            "index_path": str(index_dir),
            "kept_pages": len(records),
            "skipped_pages": skipped,
            "wiki_base": wiki_base,
            "all_pages_url": f"{wiki_base}Special:AllPages",
        }
    except HTTPException:
        shutil.rmtree(show_dir, ignore_errors=True)
        raise
    except Exception as exc:
        shutil.rmtree(show_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"Failed to create show: {exc}")


def _stream_create_show_from_selected_titles(
    fandom_url: str,
    selected_titles: list[str],
    show_name: str | None = None,
):
    global _embeddings

    show_dir: Path | None = None
    created_show_dir = False

    try:
        if _embeddings is None:
            raise HTTPException(status_code=503, detail="Embeddings are not ready yet. Try again in a moment.")

        wiki_base, suggested_show_name = _normalize_fandom_base(fandom_url)
        folder_name = _slugify(show_name or suggested_show_name)
        if not folder_name:
            raise HTTPException(status_code=400, detail="Show name is invalid.")

        cleaned_titles = [t.strip() for t in selected_titles if t and t.strip()]
        if not cleaned_titles:
            raise HTTPException(status_code=400, detail="Select at least one chapter/page.")

        shows_dir = _find_shows_dir()
        shows_dir.mkdir(parents=True, exist_ok=True)
        show_dir = shows_dir / folder_name

        if show_dir.exists():
            raise HTTPException(status_code=400, detail=f"Show '{folder_name}' already exists.")

        show_dir.mkdir(parents=True, exist_ok=False)
        created_show_dir = True

        records: list[dict[str, str]] = []
        skipped = 0
        total = len(cleaned_titles)

        yield {
            "type": "start",
            "current": 0,
            "total": total,
            "title": "Starting chapter scrape...",
            "stage": "start",
            "kept_pages": 0,
            "skipped_pages": 0,
        }

        for index, title in enumerate(cleaned_titles, start=1):
            try:
                content, page_url = _fetch_page_content(wiki_base, title)
            except Exception:
                skipped += 1
                yield {
                    "type": "progress",
                    "current": index,
                    "total": total,
                    "title": title,
                    "stage": "skipped",
                    "reason": "request_failed",
                    "kept_pages": len(records),
                    "skipped_pages": skipped,
                }
                continue

            if not content or len(content) < 80:
                skipped += 1
                yield {
                    "type": "progress",
                    "current": index,
                    "total": total,
                    "title": title,
                    "stage": "skipped",
                    "reason": "insufficient_content",
                    "kept_pages": len(records),
                    "skipped_pages": skipped,
                }
                continue

            records.append({
                "title": title,
                "content": content,
                "url": page_url,
            })

            yield {
                "type": "progress",
                "current": index,
                "total": total,
                "title": title,
                "stage": "kept",
                "kept_pages": len(records),
                "skipped_pages": skipped,
            }

        if not records:
            raise HTTPException(status_code=400, detail="No usable content found from selected pages.")

        yield {
            "type": "indexing",
            "current": total,
            "total": total,
            "title": "Building FAISS index...",
            "stage": "indexing",
            "kept_pages": len(records),
            "skipped_pages": skipped,
        }

        dataset_path = show_dir / "dataset.json"
        with dataset_path.open("w", encoding="utf-8") as handle:
            json.dump(records, handle, ensure_ascii=False, indent=2)

        docs = _to_documents(records)
        chunks = _chunk_documents(docs)
        if not chunks:
            raise HTTPException(status_code=400, detail="Selected pages did not produce enough content to index.")

        vectorstore = FAISS.from_documents(chunks, _embeddings)
        index_dir = show_dir / "faiss_index"
        index_dir.mkdir(parents=True, exist_ok=True)
        vectorstore.save_local(str(index_dir))

        show_id = _slugify(folder_name)
        _dataset_retrievers.pop(show_id, None)

        yield {
            "type": "done",
            "show": {"id": show_id, "name": folder_name},
            "kept_pages": len(records),
            "skipped_pages": skipped,
            "all_pages_url": f"{wiki_base}Special:AllPages",
        }
    except HTTPException as exc:
        if created_show_dir and show_dir is not None:
            shutil.rmtree(show_dir, ignore_errors=True)
        yield {
            "type": "error",
            "detail": str(exc.detail),
        }
    except Exception as exc:
        if created_show_dir and show_dir is not None:
            shutil.rmtree(show_dir, ignore_errors=True)
        yield {
            "type": "error",
            "detail": f"Failed to create show: {exc}",
        }


def _show_records() -> list[dict]:
    """Find all shows with pre-built FAISS indexes."""
    shows_dir = _find_shows_dir()
    if not shows_dir.exists():
        return []

    records = []
    for show_folder in sorted(shows_dir.iterdir()):
        if not show_folder.is_dir():
            continue
        faiss_index = show_folder / "faiss_index"
        dataset_file = show_folder / "dataset.json"
        # Only include shows that have both a FAISS index and dataset
        if faiss_index.exists() and dataset_file.exists():
            records.append({
                "id": _slugify(show_folder.name),
                "name": show_folder.name,
                "folder": str(show_folder),
                "file": str(dataset_file),
                "index": str(faiss_index),
            })
    return records


def _to_documents(data: list[dict]) -> list[Document]:
    docs = []
    for record in data:
        title = record.get("title", "")
        content = record.get("content", "")
        url = record.get("url", "")

        if len(content.strip()) < 80:
            continue

        docs.append(Document(
            page_content=f"Article: {title}\n\n{content}",
            metadata={"title": title, "url": url},
        ))
    return docs


def _chunk_documents(docs: list[Document]) -> list[Document]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    return splitter.split_documents(docs)


def _load_show_retriever(show: dict):
    """Load FAISS index for a show."""
    global _embeddings

    if show["id"] in _dataset_retrievers:
        return _dataset_retrievers[show["id"]]

    index_dir = show["index"]
    print(f"[show] Loading FAISS index for '{show['name']}' from '{index_dir}' …")
    vectorstore = FAISS.load_local(
        index_dir,
        _embeddings,
        allow_dangerous_deserialization=True,
    )

    retriever = vectorstore.as_retriever(search_kwargs={"k": TOP_K})
    _dataset_retrievers[show["id"]] = retriever
    return retriever


def _get_retriever(show_id: str | None):
    if not show_id:
        raise HTTPException(
            status_code=400,
            detail="No show selected.",
        )

    shows = _show_records()
    selected = next((s for s in shows if s["id"] == show_id), None)
    if selected is None:
        raise HTTPException(status_code=400, detail=f"Unknown show: {show_id}")

    return _load_show_retriever(selected)


# ── Lifespan (startup / shutdown) ────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _embeddings, _llm_chain

    print(f"[startup] Loading embedding model ({EMBED_MODEL}) …")
    _embeddings = HuggingFaceEmbeddings(
        model_name=EMBED_MODEL,
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True},
    )

    shows = _show_records()
    print(f"[startup] Found {len(shows)} available shows.")

    print(f"[startup] Connecting to Ollama ({LLM_MODEL}) …")
    llm = OllamaLLM(model=LLM_MODEL, temperature=0.2)

    # Only prompt → llm → parse; retrieval is done separately so we can time each step
    _llm_chain = PROMPT | llm | StrOutputParser()

    print("[startup] API ready!")
    yield
    # nothing to tear down


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(title="Frieren RAG API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# ── Routes ────────────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    question: str
    show: str | None = None


class PreviewPagesRequest(BaseModel):
    fandom_url: str
    limit: int = 2000


class CreateShowFromFandomRequest(BaseModel):
    fandom_url: str
    selected_titles: list[str]
    show_name: str | None = None


@app.get("/shows")
async def shows():
    items = _show_records()
    return {
        "shows": [{"id": s["id"], "name": s["name"]} for s in items],
    }


@app.post("/shows/preview-pages")
async def preview_pages(req: PreviewPagesRequest):
    wiki_base, suggested_show_name = _normalize_fandom_base(req.fandom_url)

    try:
        titles = _fetch_all_fandom_titles(wiki_base)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not load page list from fandom wiki: {exc}")

    safe_limit = max(50, min(req.limit, 5000))
    limited_titles = titles[:safe_limit]

    return {
        "wiki_base": wiki_base,
        "all_pages_url": f"{wiki_base}Special:AllPages",
        "suggested_show_name": suggested_show_name,
        "total_pages": len(titles),
        "returned_pages": len(limited_titles),
        "truncated": len(titles) > len(limited_titles),
        "pages": [{"title": title} for title in limited_titles],
    }


@app.post("/shows/create-from-fandom")
async def create_show_from_fandom(req: CreateShowFromFandomRequest):
    show = _create_show_from_selected_titles(
        fandom_url=req.fandom_url,
        selected_titles=req.selected_titles,
        show_name=req.show_name,
    )
    return {
        "message": "Show created successfully.",
        "show": {"id": show["id"], "name": show["name"]},
        "kept_pages": show["kept_pages"],
        "skipped_pages": show["skipped_pages"],
        "all_pages_url": show["all_pages_url"],
    }


@app.post("/shows/create-from-fandom/stream")
async def create_show_from_fandom_stream(req: CreateShowFromFandomRequest):
    def event_stream():
        for event in _stream_create_show_from_selected_titles(
            fandom_url=req.fandom_url,
            selected_titles=req.selected_titles,
            show_name=req.show_name,
        ):
            yield json.dumps(event, ensure_ascii=False) + "\n"

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/chat")
async def chat(req: ChatRequest):
    question = req.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question must not be empty.")

    try:
        retriever = _get_retriever(req.show)

        t0 = time.perf_counter()
        source_docs = retriever.invoke(question)
        t1 = time.perf_counter()

        context = _format_docs(source_docs)
        answer  = _llm_chain.invoke({"context": context, "question": question})
        t2 = time.perf_counter()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    timings = {
        "retrieval": round(t1 - t0, 3),
        "llm":       round(t2 - t1, 3),
        "total":     round(t2 - t0, 3),
    }

    sources = [
        {
            "title":   doc.metadata.get("title", "unknown"),
            "url":     doc.metadata.get("url", ""),
            "content": doc.page_content,
        }
        for doc in source_docs
    ]

    return {
        "answer":  answer,
        "sources": sources,
        "timings": timings,
        "show": req.show,
    }
