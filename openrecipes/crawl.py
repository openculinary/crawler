import json
import requests


def ingest_url(url):
    data = {'url': url}
    try:
        resp = requests.post('http://localhost:8080/api/recipes/crawl', data)
        resp.raise_for_status()
    except Exception as e:
        print(e)


with open('recipes.json', 'r') as f:
    for line in f:
        doc = json.loads(line)
        ingest_url(doc['url'])
        print('* Ingested {}'.format(doc['name']))
