import argparse

import pg8000

from actions import recrawl


def query_recipe_urls(where):
    where = where or 'true'
    query = (
        f'select url'
        f'from recipe_urls'
        f'where {where}'
        f'order by random()'
    )

    db = pg8000.connect(host='192.168.100.1', user='api', database='api')
    cursor = db.cursor()
    results = cursor.execute(query)
    for (url,) in results.fetchall():
        yield url
    cursor.close()


parser = argparse.ArgumentParser(description='Recrawl recipes')
parser.add_argument('--where', help='SQL WHERE clause to select recipe_urls')
parser.add_argument('--recrawl', action='store_true', help='Invoke recrawling')
args = parser.parse_args()

for url in query_recipe_urls(args.where):
    if args.recrawl:
        recrawl(url)
        print(f'* Queued URL {url} for recrawling')
    else:
        print(f'* Found URL {url}')
