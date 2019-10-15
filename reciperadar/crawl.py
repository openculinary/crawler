import pg8000
import requests

DB_URI = f'postgresql+pg8000://api@192.168.100.1/api'


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


db = pg8000.connect(host='192.168.100.1', user='api', database='api')
results = db.cursor().execute('select src, title from recipes where indexed_at is not null')
for result in results.fetchall():
    url, title = result
    ingest_url(url)
    print('* Ingested {}'.format(title))
