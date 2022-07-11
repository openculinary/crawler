from http import HTTPStatus
import json
from random import shuffle
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def ingest_url(url):
    headers = {"Host": "backend"}
    data = urlencode({"url": url}).encode("utf-8")
    request = Request("https://localhost:30080/recipes/crawl", data, headers)
    try:
        with urlopen(request) as response:
            if response.status == HTTPStatus.OK:
                return
            print(f"! Crawling url={url} failed with status={response.status}")
    except Exception as e:
        print(f"! Crawling url={url} failed with exception={e}")


with open("recipes.json", "r") as f:
    docs = []
    for line in f:
        docs.append(json.loads(line))

    shuffle(docs)
    for doc in docs:
        ingest_url(doc["url"])
        print("* Processed {}".format(doc["name"]))
