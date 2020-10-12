import requests


def recrawl(url):
    data = {'url': url}
    try:
        resp = requests.post(
            url='http://localhost:30080/recipes/crawl',
            headers={'Host': 'backend'},
            data=data
        )
        resp.raise_for_status()
    except Exception as e:
        print(e)


def reindex(recipe_id):
    data = {'recipe_id': recipe_id}
    try:
        resp = requests.post(
            url='http://localhost:30080/recipes/index',
            headers={'Host': 'backend'},
            data=data
        )
        resp.raise_for_status()
    except Exception as e:
        print(e)
