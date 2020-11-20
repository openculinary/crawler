from datetime import datetime, timedelta
from flask import Flask, request
import kubernetes
from tldextract import TLDExtract
import requests
from requests.exceptions import ConnectionError, ReadTimeout
from socket import gethostname
from time import sleep
from urllib.parse import urljoin

from recipe_scrapers._abstract import HEADERS
from recipe_scrapers.__version__ import __version__ as rs_version
from recipe_scrapers import (
    scrape_me as scrape_recipe,
    WebsiteNotImplementedError,
)


def request_patch(self, *args, **kwargs):
    kwargs['proxies'] = kwargs.pop('proxies', {
        'http': 'http://proxy:3128',
        'https': 'http://proxy:3128',
    })
    kwargs['timeout'] = kwargs.pop('timeout', 5)
    kwargs['verify'] = kwargs.pop('verify', '/etc/ssl/k8s/proxy-cert/ca.crt')
    return self.request_orig(*args, **kwargs)


setattr(
    requests.sessions.Session, 'request_orig',
    requests.sessions.Session.request
)
requests.sessions.Session.request = request_patch

app = Flask(__name__)


def parse_directions(descriptions):
    directions = requests.post(
        url='http://direction-parser-service',
        data={'descriptions[]': descriptions},
    ).json()
    return [
        {**{'index': index}, **direction}
        for index, direction in enumerate(directions)
    ]


def parse_ingredients(descriptions):
    ingredients = requests.post(
        url='http://ingredient-parser-service',
        data={'descriptions[]': descriptions},
    ).json()
    return [
        {**{'index': index}, **ingredient}
        for index, ingredient in enumerate(ingredients)
    ]


tldextract = TLDExtract(suffix_list_urls=None)
domain_backoffs = {}


def get_domain(url):
    url_info = tldextract(url)
    return f'{url_info.domain}.{url_info.suffix}'


@app.before_first_request
def before_first_request():
    app.image_version = determine_image_version()


def determine_image_version():
    kubernetes.config.load_incluster_config()
    client = kubernetes.client.CoreV1Api()
    pod = client.read_namespaced_pod(namespace='default', name=gethostname())
    app = pod.metadata.labels['app']
    container = next(filter(lambda c: c.name == app, pod.spec.containers))
    return container.image.split(':')[-1] if container else None


@app.route('/resolve', methods=['POST'])
def resolve():
    url = request.form.get('url')
    if not url:
        return {'error': {
            'message': 'url parameter is required',
        }}, 400

    response = requests.get(url, headers=HEADERS)
    return {
        'metadata': {
            'service_version': app.image_version,
            'recipe_scrapers_version': rs_version,
        },
        'url': {
            'resolves_to': response.url
        },
    }


@app.route('/crawl', methods=['POST'])
def crawl():
    url = request.form.get('url')
    if not url:
        return {'error': {
            'message': 'url parameter is required',
        }}, 400

    domain = get_domain(url)
    if domain in domain_backoffs:
        start = domain_backoffs[domain]['timestamp']
        duration = domain_backoffs[domain]['duration']

        if datetime.utcnow() < (start + duration):
            print(f'* Backing off for {domain}')
            sleep(duration.seconds)
            return {'error': {
                'message': f'backing off for {domain}',
            }}, 429

    try:
        scrape = scrape_recipe(url, timeout=5, proxies={
            'http': 'http://proxy:3128',
            'https': 'http://proxy:3128',
        })
    except (ConnectionError, ReadTimeout):
        duration = timedelta(seconds=1)
        if domain in domain_backoffs:
            duration += domain_backoffs[domain]['duration']
        domain_backoffs[domain] = {
            'timestamp': datetime.utcnow(),
            'duration': duration
        }
        print(f'* Setting backoff on {domain} for {duration.seconds} seconds')
        sleep(duration.seconds)
        return {'error': {
            'message': f'timeout; adding backoff for {domain}',
        }}, 429
    except WebsiteNotImplementedError:
        return {'error': {
            'message': 'website is not implemented',
        }}, 501

    try:
        author = scrape.author()
    except NotImplementedError:
        author = None

    try:
        scraped_image = scrape.image() or super(type(scrape), scrape).image()
    except NotImplementedError:
        return {'error': {
            'message': 'image retrieval is not implemented',
        }}, 501

    if not scraped_image:
        return {'error': {
            'message': 'could not find recipe image',
        }}, 404

    directions = parse_directions(scrape.instructions().split('\n'))
    ingredients = scrape.ingredients()
    try:
        ingredients = parse_ingredients(ingredients)
    except Exception:
        return {'error': {
            'message': f'ingredient parsing failed for: {ingredients}'
        }}, 400

    if not ingredients:
        return {'error': {
            'message': 'could not find recipe ingredient',
        }}, 404

    time = scrape.total_time()
    if not time:
        return {'error': {
            'message': 'could not find recipe timing info',
        }}, 404

    servings = 1
    yields = scrape.yields()
    if yields:
        tokens = yields.split()
        try:
            servings = int(tokens[0])
        except Exception:
            return {'error': {
                'message': f'servings parsing failed for: {yields}',
            }}, 400

    try:
        rating = float(scrape.ratings())
    except NotImplementedError:
        rating = 4.0
    rating = 3.0 if not 1 <= rating <= 5 else rating
    rating = 4.75 if rating == 5.0 else rating

    return {
        'metadata': {
            'service_version': app.image_version,
            'recipe_scrapers_version': rs_version,
        },
        'recipe': {
            'title': scrape.title(),
            'src': url,
            'domain': domain,
            'ingredients': ingredients,
            'directions': directions,
            'author': author,
            'image_src': urljoin(url, scraped_image),
            'servings': servings,
            'time': time,
            'rating': rating,
        },
    }
