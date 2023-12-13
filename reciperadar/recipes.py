import argparse

import pg8000

from actions import recrawl, reindex


def query_recipes(where):
    where = where or "true"
    query = (
        f"select id, dst, title "
        f"from recipes "
        f"where {where} "
        f"order by random()"
    )

    db = pg8000.connect(host="192.168.100.1", user="backend", database="backend")
    cursor = db.cursor()
    results = cursor.execute(query)
    for recipe_id, dst, title in results.fetchall():
        yield recipe_id, dst, title
    cursor.close()


parser = argparse.ArgumentParser(description="Reindex recipes")
parser.add_argument("--where", help="SQL WHERE clause to select recipes")
parser.add_argument("--recrawl", action="store_true", help="Invoke recrawling")
parser.add_argument("--reindex", action="store_true", help="Invoke reindexing")
args = parser.parse_args()

for recipe_id, dst, title in query_recipes(args.where):
    if args.recrawl:
        recrawl(dst)
        print(f"* Processed recipe {title} for recrawling")
    elif args.reindex:
        reindex(recipe_id)
        print(f"* Processed recipe {title} for reindexing")
    else:
        print(f"* Found recipe {title}")
