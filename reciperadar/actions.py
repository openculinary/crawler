from http import HTTPStatus
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def recrawl(url):
    headers = {"Host": "backend"}
    data = urlencode({"url": url}).encode("utf-8")
    request = Request("http://localhost:30080/recipes/crawl", data, headers)
    try:
        with urlopen(request) as response:
            if response.status == HTTPStatus.OK:
                return
            print(f"! Crawling url={url} failed with status={response.status}")
    except Exception as e:
        print(f"! Crawling url={url} failed with exception={e}")


def reindex(recipe_id):
    headers = {"Host": "backend"}
    data = urlencode({"recipe_id": recipe_id}).encode("utf-8")
    request = Request("https://localhost:30080/recipes/index", data, headers)
    try:
        with urlopen(request) as response:
            if response.status == HTTPStatus.OK:
                return
            print(f"! Indexing recipe_id={recipe_id} failed: status={response.status}")
    except Exception as e:
        print(f"! Indexing recipe_id={recipe_id} failed: exception={e}")
