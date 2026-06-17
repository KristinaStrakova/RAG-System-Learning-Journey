import json
import re
import time
from pathlib import Path
from urllib.parse import quote, urlparse

import requests
from bs4 import BeautifulSoup
from requests.exceptions import RequestException, JSONDecodeError

TIMEOUT_SECONDS = 20
MAX_RETRIES = 3
REQUEST_DELAY_SECONDS = 0.35
EXCLUDED_TITLE_TERMS = ["gallery", "blu-ray&dvd", "policy", "volume", "disambiguation"]
USER_AGENT = "RAGShowScraper/1.0 (learning project)"


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", name.lower()).strip("_")
    return slug or "new_show"


def normalize_fandom_base(raw_url: str) -> str:
    url = raw_url.strip()
    if not url:
        raise ValueError("Fandom URL is required.")

    if not re.match(r"^https?://", url, flags=re.IGNORECASE):
        url = f"https://{url}"

    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if not host.endswith("fandom.com"):
        raise ValueError("URL must point to a fandom.com wiki.")

    labels = host.split(".")
    if len(labels) < 3 or not labels[0]:
        raise ValueError("Invalid fandom host; expected something like deadpool.fandom.com")

    return f"https://{labels[0]}.fandom.com/wiki/"


def wiki_api_url(wiki_base: str) -> str:
    parsed = urlparse(wiki_base)
    return f"{parsed.scheme}://{parsed.netloc}/api.php"


def should_skip_title(title: str) -> bool:
    normalized = title.lower()
    return any(term in normalized for term in EXCLUDED_TITLE_TERMS)


def fetch_json(api_url: str, params: dict, max_retries: int = MAX_RETRIES):
    """Fetch JSON with retries; return None if response is not valid JSON."""
    headers = {"User-Agent": USER_AGENT}

    for attempt in range(1, max_retries + 1):
        try:
            response = requests.get(api_url, params=params, headers=headers, timeout=TIMEOUT_SECONDS)
            response.raise_for_status()
            return response.json()
        except JSONDecodeError:
            preview = response.text[:120].replace("\n", " ") if "response" in locals() else "<no response body>"
            print(f"[warn] Non-JSON response on attempt {attempt}/{max_retries}. Preview: {preview}")
        except RequestException as exc:
            print(f"[warn] Request failed on attempt {attempt}/{max_retries}: {exc}")

        time.sleep(attempt)

    return None


def get_all_pages(wiki_base: str) -> list[str]:
    api_url = wiki_api_url(wiki_base)
    pages: list[str] = []
    apcontinue = ""

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

        res = fetch_json(api_url, params)
        if not res or "query" not in res:
            print("[error] Could not fetch page list from API.")
            break

        pages.extend(res["query"]["allpages"])

        if "continue" in res:
            apcontinue = res["continue"].get("apcontinue", "")
            if not apcontinue:
                break
        else:
            break

    titles = [p["title"] for p in pages if p.get("title")]
    seen = set()
    deduped = []
    for title in titles:
        if title in seen:
            continue
        seen.add(title)
        deduped.append(title)
    return deduped


def get_page_content(wiki_base: str, title: str) -> str | None:
    api_url = wiki_api_url(wiki_base)
    params = {
        "action": "parse",
        "page": title,
        "prop": "text",
        "format": "json",
    }

    res = fetch_json(api_url, params)

    if not res or "parse" not in res:
        print(f"[warn] Skipping page due to parse/API issue: {title}")
        return None

    html = res["parse"]["text"].get("*")
    if not html:
        return None

    soup = BeautifulSoup(html, "html.parser")
    content = soup.get_text(separator=" ", strip=True)
    return re.sub(r"\s+", " ", content).strip()


def select_titles_interactively(titles: list[str]) -> list[str]:
    print(f"\n[info] Found {len(titles)} pages.")
    print("Selection options:")
    print("  - Press Enter for all filtered pages")
    print("  - Type a comma list of indices like: 1,4,10")
    print("  - Type a range like: 1-30")

    preview_count = min(30, len(titles))
    print(f"\nFirst {preview_count} pages:")
    for i, title in enumerate(titles[:preview_count], start=1):
        print(f"  {i:>3}. {title}")

    raw = input("\nChoose pages by index/range (or Enter for all): ").strip()
    if not raw:
        return titles

    selected_indices = set()
    chunks = [item.strip() for item in raw.split(",") if item.strip()]
    for chunk in chunks:
        if "-" in chunk:
            parts = chunk.split("-", 1)
            if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
                continue
            start_i = int(parts[0])
            end_i = int(parts[1])
            lo = max(1, min(start_i, end_i))
            hi = min(len(titles), max(start_i, end_i))
            for idx in range(lo, hi + 1):
                selected_indices.add(idx)
        elif chunk.isdigit():
            idx = int(chunk)
            if 1 <= idx <= len(titles):
                selected_indices.add(idx)

    if not selected_indices:
        print("[warn] Invalid selection; defaulting to all pages.")
        return titles

    return [titles[idx - 1] for idx in sorted(selected_indices)]


def prompt_show_name(default_name: str) -> str:
    print("\n[info] Scraping complete. Choose a show folder name for the app.")
    typed = input(f"Show name (default: {default_name}): ").strip()
    return slugify(typed or default_name)


def save_dataset_for_show(show_name: str, dataset: list[dict]) -> Path:
    show_dir = Path("shows") / show_name
    show_dir.mkdir(parents=True, exist_ok=True)

    output_file = show_dir / "dataset.json"
    with output_file.open("w", encoding="utf-8") as handle:
        json.dump(dataset, handle, ensure_ascii=False, indent=2)

    return output_file


def main():
    raw_url = input("Paste any Fandom URL (e.g. https://deadpool.fandom.com/wiki/Special:AllPages): ")
    try:
        wiki_base = normalize_fandom_base(raw_url)
    except ValueError as exc:
        print(f"[error] {exc}")
        return

    print(f"[info] Normalized wiki base: {wiki_base}")
    print(f"[info] Using page list URL: {wiki_base}Special:AllPages")

    all_titles = get_all_pages(wiki_base)
    filtered_titles = [t for t in all_titles if not should_skip_title(t)]
    skipped = len(all_titles) - len(filtered_titles)
    print(f"[info] Keeping {len(filtered_titles)} pages, skipped {skipped} by title filter.")

    if not filtered_titles:
        print("[error] No pages available after filtering.")
        return

    selected_titles = select_titles_interactively(filtered_titles)
    print(f"[info] Selected {len(selected_titles)} pages to scrape.")

    dataset = []
    for index, title in enumerate(selected_titles, start=1):
        print(f"[{index}/{len(selected_titles)}] Fetching: {title}")
        content = get_page_content(wiki_base, title)

        if content and len(content) >= 80:
            dataset.append(
                {
                    "title": title,
                    "content": content,
                    "url": f"{wiki_base}{quote(title.replace(' ', '_'))}",
                }
            )

        time.sleep(REQUEST_DELAY_SECONDS)

    if not dataset:
        print("[error] No usable pages were scraped.")
        return

    default_name = slugify(urlparse(wiki_base).netloc.split(".")[0])
    show_name = prompt_show_name(default_name)
    output_path = save_dataset_for_show(show_name, dataset)

    print("\n[done] Dataset saved for app integration:")
    print(f"       {output_path}")
    print("[next] Build FAISS index for this show so it appears in the picker.")


if __name__ == "__main__":
    main()