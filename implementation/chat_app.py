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
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_ollama import OllamaLLM
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough

# ── Config ────────────────────────────────────────────────────────────────────

INDEX_DIR   = "faiss_index"
EMBED_MODEL = "BAAI/bge-small-en-v1.5"   # must match what you used in 1_build_index.py
LLM_MODEL   = "mistral"                  # any model you've pulled in Ollama
TOP_K       = 5                          # how many chunks to retrieve per query

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

# ── Setup ─────────────────────────────────────────────────────────────────────

def load_chain(index_dir: str, embed_model: str, llm_model: str, top_k: int):
    print("Loading embedding model …")
    embeddings = HuggingFaceEmbeddings(
        model_name=embed_model,
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True},
    )

    print(f"Loading FAISS index from '{index_dir}/' …")
    vectorstore = FAISS.load_local(
        index_dir,
        embeddings,
        allow_dangerous_deserialization=True,   # safe — you built this index yourself
    )
    retriever = vectorstore.as_retriever(search_kwargs={"k": top_k})

    print(f"Connecting to Ollama ({llm_model}) …")
    llm = OllamaLLM(model=llm_model, temperature=0.2)

    # LCEL chain:  retrieved docs → format → prompt → llm → parse
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
    parser.add_argument("--index", default=INDEX_DIR,       help="FAISS index folder")
    parser.add_argument("--model", default=LLM_MODEL,       help="Ollama model name")
    parser.add_argument("--top-k", default=TOP_K, type=int, help="Chunks to retrieve")
    args = parser.parse_args()

    chain, retriever = load_chain(args.index, EMBED_MODEL, args.model, args.top_k)
    chat(chain, retriever)


if __name__ == "__main__":
    main()