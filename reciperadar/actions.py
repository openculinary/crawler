import requests


def recrawl(url):
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


def reindex(recipe_id):
    data = {'recipe_id': recipe_id}
    try:
        resp = requests.post(
            url='http://localhost:30080/api/recipes/index',
            headers={'Host': 'api'},
            data=data
        )
        resp.raise_for_status()
    except Exception as e:
        print(e)
