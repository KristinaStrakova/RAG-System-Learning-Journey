"""
Step 1: Build the vector index from frieren_dataset.json
Run this ONCE. It will create a `faiss_index/` folder you can reuse.

Usage:
    python 1_build_index.py
    python 1_build_index.py --json path/to/frieren_dataset.json
"""

import json
import argparse
from pathlib import Path
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS

# ── Config ────────────────────────────────────────────────────────────────────

DEFAULT_JSON   = "frieren_dataset_both_seasons.json"
INDEX_DIR      = "faiss_index"
EMBED_MODEL    = "BAAI/bge-small-en-v1.5"   # fast, free, ~130 MB download
CHUNK_SIZE     = 700   # characters (not tokens — keep headroom for special chars)
CHUNK_OVERLAP  = 100

# ── Helpers ───────────────────────────────────────────────────────────────────

def load_json(path: str) -> list[dict]:
    print(f"[1/4] Loading JSON from '{path}' …")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    print(f"      Loaded {len(data)} pages.")
    return data


def to_documents(data: list[dict]) -> list[Document]:
    """
    Convert raw JSON records to LangChain Documents.
    Each record: { "title": str, "content": str, "url": str }
    """
    docs = []
    for record in data:
        title   = record.get("title", "")
        content = record.get("content", "")
        url     = record.get("url", "")

        # Skip pages with almost no content (redirect stubs, etc.)
        if len(content.strip()) < 80:
            continue

        # Prepend the title so every chunk knows which article it came from
        text = f"Article: {title}\n\n{content}"
        docs.append(Document(
            page_content=text,
            metadata={"title": title, "url": url}
        ))

    print(f"      {len(docs)} non-empty pages converted to Documents.")
    return docs


def chunk_documents(docs: list[Document]) -> list[Document]:
    print(f"[2/4] Chunking (size={CHUNK_SIZE}, overlap={CHUNK_OVERLAP}) …")
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        # Split on paragraph breaks first, then sentences, then words
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    chunks = splitter.split_documents(docs)
    print(f"      {len(chunks)} chunks created.")
    return chunks


def build_index(chunks: list[Document], model_name: str) -> FAISS:
    print(f"[3/4] Embedding with '{model_name}' (first run downloads the model) …")
    embeddings = HuggingFaceEmbeddings(
        model_name=model_name,
        model_kwargs={"device": "cpu"},        # change to "cuda" if you have a GPU
        encode_kwargs={"normalize_embeddings": True},  # needed for cosine similarity
    )
    vectorstore = FAISS.from_documents(chunks, embeddings)
    print(f"      Embedding done.")
    return vectorstore


def save_index(vectorstore: FAISS, output_dir: str) -> None:
    print(f"[4/4] Saving index to '{output_dir}/' …")
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    vectorstore.save_local(output_dir)
    print(f"      Done! Index saved.\n")
    print("Next step: run  python 2_chat.py")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--json",  default=DEFAULT_JSON, help="Path to frieren_dataset.json")
    parser.add_argument("--index", default=INDEX_DIR,    help="Output folder for FAISS index")
    args = parser.parse_args()

    data        = load_json(args.json)
    docs        = to_documents(data)
    chunks      = chunk_documents(docs)
    vectorstore = build_index(chunks, EMBED_MODEL)
    save_index(vectorstore, args.index)


if __name__ == "__main__":
    main()