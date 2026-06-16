import requests
from bs4 import BeautifulSoup
import json
import time
from requests.exceptions import RequestException, JSONDecodeError

BASE_URL = "https://frieren.fandom.com/api.php"
TIMEOUT_SECONDS = 20
MAX_RETRIES = 3
EXCLUDED_TITLE_TERMS = ["gallery", "blu-ray&dvd", "policy", "volume"]


def should_skip_title(title: str) -> bool:
    normalized = title.lower()
    return any(term in normalized for term in EXCLUDED_TITLE_TERMS)


def fetch_json(params, max_retries=MAX_RETRIES):
    """Fetch JSON with retries; return None if response is not valid JSON."""
    headers = {
        "User-Agent": "FrierenRAGScraper/1.0 (learning project)"
    }

    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.get(BASE_URL, params=params, headers=headers, timeout=TIMEOUT_SECONDS)
            resp.raise_for_status()
            return resp.json()
        except JSONDecodeError:
            preview = resp.text[:120].replace("\n", " ") if 'resp' in locals() else "<no response body>"
            print(f"[warn] Non-JSON response on attempt {attempt}/{max_retries}. Preview: {preview}")
        except RequestException as exc:
            print(f"[warn] Request failed on attempt {attempt}/{max_retries}: {exc}")

        time.sleep(attempt)

    return None

def get_all_pages():
    pages = []
    apcontinue = ""

    while True:
        params = {
            "action": "query",
            "list": "allpages",
            "aplimit": "max",
            "format": "json"
        }
        if apcontinue:
            params["apcontinue"] = apcontinue

        res = fetch_json(params)
        if not res or "query" not in res:
            print("[error] Could not fetch page list from API.")
            break

        pages.extend(res["query"]["allpages"])

        if "continue" in res:
            apcontinue = res["continue"]["apcontinue"]
        else:
            break

    return [p["title"] for p in pages]


def get_page_content(title):
    params = {
        "action": "parse",
        "page": title,
        "prop": "text",
        "format": "json"
    }

    res = fetch_json(params)

    if not res or "parse" not in res:
        print(f"[warn] Skipping page due to parse/API issue: {title}")
        return None

    html = res["parse"]["text"]["*"]
    soup = BeautifulSoup(html, "html.parser")

    return soup.get_text()


def main():
    titles = get_all_pages()
    filtered_titles = [t for t in titles if not should_skip_title(t)]

    skipped = len(titles) - len(filtered_titles)
    print(f"[info] Keeping {len(filtered_titles)} pages, skipped {skipped} by title filter.")

    dataset = []

    for title in filtered_titles:
        print(f"Fetching: {title}")
        content = get_page_content(title)

        if content:
            dataset.append({
                "title": title,
                "content": content,
                "url": f"https://frieren.fandom.com/wiki/{title.replace(' ', '_')}"
            })

        time.sleep(1)  # be polite

    with open("frieren_dataset_both_seasons.json", "w", encoding="utf-8") as f:
        json.dump(dataset, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()