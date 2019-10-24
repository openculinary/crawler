import json
from random import shuffle
import requests


def ingest_url(url):
    data = {'url': url}
    try:
        resp = requests.post(
            url='http://localhost:30080/api/recipes/crawl',
            headers={'Host': 'api'},
            data=data
        )
        resp.raise_for_status()
    except Exception as e:
        print(e)


with open('recipes.json', 'r') as f:
    docs = []
    for line in f:
        docs.append(json.loads(line))

    shuffle(docs)
    for doc in docs:
        ingest_url(doc['url'])
        print('* Ingested {}'.format(doc['name']))
