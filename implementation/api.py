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
import time
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_ollama import OllamaLLM
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough

# ── Config ────────────────────────────────────────────────────────────────────

INDEX_DIR   = "faiss_index"
EMBED_MODEL = "BAAI/bge-small-en-v1.5"
LLM_MODEL   = "mistral"
TOP_K       = 5

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

_retriever = None
_llm_chain = None   # PROMPT | llm | parser  (no retriever — timed separately)


def _find_index_dir() -> str:
    """Locate the faiss_index folder regardless of CWD."""
    here = Path(__file__).parent
    candidates = [
        Path(os.getcwd()) / INDEX_DIR,
        here.parent / INDEX_DIR,
        here / INDEX_DIR,
    ]
    for path in candidates:
        if path.exists():
            return str(path)
    return INDEX_DIR  # fall back; will error with a clear message


def _format_docs(docs: list) -> str:
    return "\n\n---\n\n".join(doc.page_content for doc in docs)


# ── Lifespan (startup / shutdown) ────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _retriever, _llm_chain

    index_path = _find_index_dir()
    print(f"[startup] Loading embedding model ({EMBED_MODEL}) …")
    embeddings = HuggingFaceEmbeddings(
        model_name=EMBED_MODEL,
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True},
    )

    print(f"[startup] Loading FAISS index from '{index_path}/' …")
    vectorstore = FAISS.load_local(
        index_path,
        embeddings,
        allow_dangerous_deserialization=True,  # safe — you built this index yourself
    )
    _retriever = vectorstore.as_retriever(search_kwargs={"k": TOP_K})

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


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/chat")
async def chat(req: ChatRequest):
    question = req.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question must not be empty.")

    try:
        t0 = time.perf_counter()
        source_docs = _retriever.invoke(question)
        t1 = time.perf_counter()

        context = _format_docs(source_docs)
        answer  = _llm_chain.invoke({"context": context, "question": question})
        t2 = time.perf_counter()
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
    }
