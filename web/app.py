from datetime import datetime, timedelta
from flask import Flask, abort, jsonify, request
import kubernetes
from tldextract import TLDExtract
from recipe_scrapers._abstract import HEADERS
import requests
from requests.exceptions import ConnectionError, ReadTimeout
from socket import gethostname
from time import sleep
from urllib.parse import urljoin

from recipe_scrapers import (
    __version__ as rs_version,
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
        proxies={}
    ).json()
    return [
        {**{'index': index}, **direction}
        for index, direction in enumerate(directions)
    ]


def parse_ingredients(descriptions):
    ingredients = requests.post(
        url='http://ingredient-parser-service',
        data={'descriptions[]': descriptions},
        proxies={}
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
        return abort(400)

    response = requests.get(url, headers=HEADERS)
    return jsonify({
        'metadata': {
            'service_version': app.image_version,
            'recipe_scrapers_version': rs_version,
        },
        'url': {
            'resolves_to': response.url
        },
    })


@app.route('/crawl', methods=['POST'])
def crawl():
    url = request.form.get('url')
    if not url:
        return abort(400)

    domain = get_domain(url)
    if domain in domain_backoffs:
        start = domain_backoffs[domain]['timestamp']
        duration = domain_backoffs[domain]['duration']

        if datetime.utcnow() < (start + duration):
            print(f'* Backing off for {domain}')
            sleep(duration.seconds)
            return abort(429)

    try:
        scrape = scrape_recipe(url)
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
        return abort(429)
    except WebsiteNotImplementedError:
        return abort(501)

    try:
        scraped_image = scrape.image() or super(type(scrape), scrape).image()
    except NotImplementedError:
        return abort(501)

    if not scraped_image:
        return abort(404)

    directions = parse_directions(scrape.instructions().split('\n'))
    ingredients = parse_ingredients(scrape.ingredients())

    if not ingredients:
        return abort(404)

    time = scrape.total_time()
    if not time:
        return abort(404)

    servings = int(scrape.yields().split(' ')[0] or '1')

    try:
        rating = float(scrape.ratings())
    except NotImplementedError:
        rating = 4.0
    rating = 3.0 if not 1 <= rating <= 5 else rating
    rating = 4.75 if rating == 5.0 else rating

    return jsonify({
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
            'image_src': urljoin(url, scraped_image),
            'servings': servings,
            'time': time,
            'rating': rating,
        },
    })
