import argparse

import pg8000

from actions import recrawl


def query_crawl_urls(where):
    where = where or "true"
    query = f"select url " f"from crawl_urls " f"where {where} " f"order by random()"

    db = pg8000.connect(host="192.168.100.1", user="api", database="api")
    cursor = db.cursor()
    results = cursor.execute(query)
    for (url,) in results.fetchall():
        yield url
    cursor.close()


parser = argparse.ArgumentParser(description="Recrawl recipes")
parser.add_argument("--where", help="SQL WHERE clause to select crawl_urls")
parser.add_argument("--recrawl", action="store_true", help="Invoke recrawling")
args = parser.parse_args()

for url in query_crawl_urls(args.where):
    if args.recrawl:
        recrawl(url)
        print(f"* Processed URL {url} for recrawling")
    else:
        print(f"* Found URL {url}")
