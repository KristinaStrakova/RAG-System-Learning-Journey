import requests
from bs4 import BeautifulSoup
import json
import time

BASE_URL = "https://frieren.fandom.com/api.php"

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

        res = requests.get(BASE_URL, params=params).json()
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

    res = requests.get(BASE_URL, params=params).json()

    if "parse" not in res:
        return None

    html = res["parse"]["text"]["*"]
    soup = BeautifulSoup(html, "html.parser")

    return soup.get_text()


def main():
    titles = get_all_pages()
    dataset = []

    for title in titles:
        print(f"Fetching: {title}")
        content = get_page_content(title)

        if content:
            dataset.append({
                "title": title,
                "content": content,
                "url": f"https://frieren.fandom.com/wiki/{title.replace(' ', '_')}"
            })

        time.sleep(1)  # be polite

    with open("frieren_dataset.json", "w", encoding="utf-8") as f:
        json.dump(dataset, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()