"""
Step 2: Chat with your Frieren wiki using RAG
Requires the `faiss_index/` folder built by 1_build_index.py
Requires Ollama running locally:  https://ollama.com
    ollama pull mistral          (4 GB, recommended)
    ollama pull llama3           (alternative)

Usage:
    python 2_chat.py
    python 2_chat.py --model llama3 --top-k 6
"""

import argparse
import json
import re
from pathlib import Path
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_ollama import OllamaLLM
from langchain_core.documents import Document
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough
from langchain_text_splitters import RecursiveCharacterTextSplitter

# ── Config ────────────────────────────────────────────────────────────────────

SHOWS_DIR = "shows"
EMBED_MODEL = "BAAI/bge-small-en-v1.5"   # must match what you used in 1_build_index.py
LLM_MODEL   = "mistral"                  # any model you've pulled in Ollama
TOP_K       = 5                          # how many chunks to retrieve per query
CHUNK_SIZE = 700
CHUNK_OVERLAP = 100

# ── Prompt ────────────────────────────────────────────────────────────────────

PROMPT = PromptTemplate(
    input_variables=["context", "question"],
    template="""You are a helpful assistant who answers questions about the anime and manga series "Frieren: Beyond Journey's End".
Use ONLY the information in the context passages below to answer.
If the answer is not in the context, say "I don't have enough information about that in the wiki."
Always be concise and friendly.

Context:
{context}

Question: {question}

Answer:"""
)

# ── Helpers ───────────────────────────────────────────────────────────────────

def format_docs(docs: list) -> str:
    """Concatenate retrieved chunks into a single context string."""
    return "\n\n---\n\n".join(doc.page_content for doc in docs)


def show_sources(docs: list) -> None:
    """Print the wiki pages that were used to answer."""
    seen = set()
    sources = []
    for doc in docs:
        url   = doc.metadata.get("url", "")
        title = doc.metadata.get("title", "unknown")
        if url not in seen:
            seen.add(url)
            sources.append(f"  • {title}  →  {url}")
    if sources:
        print("\n  Sources used:")
        print("\n".join(sources))


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", name.lower()).strip("_")
    return slug or "dataset"


def show_records(shows_dir: str) -> list[dict]:
    path = Path(shows_dir)
    if not path.exists():
        return []

    records = []
    for show_folder in sorted(path.iterdir()):
        if not show_folder.is_dir():
            continue
        faiss_index = show_folder / "faiss_index"
        dataset_file = show_folder / "dataset.json"
        # Only include shows that have both a FAISS index and dataset
        if faiss_index.exists() and dataset_file.exists():
            records.append({
                "id": slugify(show_folder.name),
                "name": show_folder.name,
                "folder": str(show_folder),
                "file": str(dataset_file),
                "index": str(faiss_index),
            })
    return records


def choose_show(shows: list[dict]) -> dict | None:
    if not shows:
        return None

    print("\nAvailable shows:")
    for i, show in enumerate(shows, start=1):
        print(f"  {i}. {show['name']} ({show['id']})")

    while True:
        raw = input("Select show number (or press Enter for #1): ").strip()
        if raw == "":
            return shows[0]
        if raw.isdigit() and 1 <= int(raw) <= len(shows):
            return shows[int(raw) - 1]
        print("Invalid selection. Try again.")


def to_documents(data: list[dict]) -> list[Document]:
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


def chunk_documents(docs: list[Document]) -> list[Document]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    return splitter.split_documents(docs)


def load_show_index(embeddings, show: dict):
    index_dir = show["index"]
    print(f"Loading FAISS index for '{show['name']}' from '{index_dir}' …")
    vectorstore = FAISS.load_local(
        index_dir,
        embeddings,
        allow_dangerous_deserialization=True,
    )
    return vectorstore

# ── Setup ─────────────────────────────────────────────────────────────────────

def load_chain(embed_model: str, llm_model: str, top_k: int, show: dict | None = None):
    print("Loading embedding model …")
    embeddings = HuggingFaceEmbeddings(
        model_name=embed_model,
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True},
    )

    if show is None:
        raise RuntimeError("No show selected.")

    vectorstore = load_show_index(embeddings, show)
    retriever = vectorstore.as_retriever(search_kwargs={"k": top_k})

    print(f"Connecting to Ollama ({llm_model}) …")
    llm = OllamaLLM(model=llm_model, temperature=0.2)

    chain = (
        {"context": retriever | format_docs, "question": RunnablePassthrough()}
        | PROMPT
        | llm
        | StrOutputParser()
    )

    print("Ready!\n")
    return chain, retriever


# ── Chat loop ─────────────────────────────────────────────────────────────────

def chat(chain, retriever) -> None:
    print("=" * 55)
    print("  Frieren Wiki RAG Chat  (type 'quit' to exit)")
    print("=" * 55)

    while True:
        try:
            question = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        if not question:
            continue
        if question.lower() in {"quit", "exit", "q"}:
            print("Goodbye!")
            break

        # Retrieve source docs separately so we can display them
        source_docs = retriever.invoke(question)

        print("Thinking …\n")
        answer = chain.invoke(question)

        print(f"Bot: {answer}")
        show_sources(source_docs)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--shows-dir", default=SHOWS_DIR, help="Folder with show folders")
    parser.add_argument("--model", default=LLM_MODEL, help="Ollama model name")
    parser.add_argument("--top-k", default=TOP_K, type=int, help="Chunks to retrieve")
    parser.add_argument("--show", default=None, help="Show id")
    args = parser.parse_args()

    shows = show_records(args.shows_dir)
    selected = None
    if args.show:
        selected = next((s for s in shows if s["id"] == args.show), None)
        if selected is None:
            print(f"Show '{args.show}' not found in '{args.shows_dir}'.")
            return
    elif shows:
        selected = choose_show(shows)

    if selected is None:
        print("No show selected.")
        return

    chain, retriever = load_chain(
        EMBED_MODEL,
        args.model,
        args.top_k,
        show=selected,
    )
    chat(chain, retriever)


if __name__ == "__main__":
    main()