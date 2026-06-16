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
from pathlib import Path
from typing import Any
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
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


@app.get("/shows")
async def shows():
    items = _show_records()
    return {
        "shows": [{"id": s["id"], "name": s["name"]} for s in items],
    }


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
