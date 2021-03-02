from datetime import datetime, timedelta
from socket import gethostname
from time import sleep
from urllib.parse import urljoin
from urllib.robotparser import RobotFileParser

from flask import Flask, request
import kubernetes
from tld import get_tld
import requests
from requests.exceptions import ConnectionError, ReadTimeout

from recipe_scrapers.__version__ import __version__ as rs_version
from recipe_scrapers._abstract import HEADERS
from recipe_scrapers._utils import get_yields
from recipe_scrapers import (
    scrape_me as scrape_recipe,
    WebsiteNotImplementedError,
)

NUTRITION_SCHEMA_FIELDS = {
     'carbohydrates': 'carbohydrateContent',
     'energy': 'calories',
     'fat': 'fatContent',
     'fibre': 'fiberContent',
     'protein': 'proteinContent',
}


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


def parse_descriptions(service, descriptions):
    entities = requests.post(
        url=f'http://{service}',
        data={'descriptions[]': descriptions},
        proxies={}
    ).json()
    return [
        {**{'index': index}, **entity}
        for index, entity in enumerate(entities)
    ]


domain_backoffs = {}
domain_robot_parsers = {}


def get_domain(url):
    url_info = get_tld(url, as_object=True, search_private=False)
    return url_info.fld


def get_robot_parser(url):
    domain = get_domain(url)
    if domain not in domain_robot_parsers:
        robot_parser = RobotFileParser(urljoin(url, '/robots.txt'))
        robot_parser.read()
        domain_robot_parsers[domain] = robot_parser
    return domain_robot_parsers[domain]


def can_fetch(url):
    robot_parser = get_robot_parser(url)
    user_agent = HEADERS.get('User-Agent', '*')
    return robot_parser.can_fetch(user_agent, url)


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

    if not can_fetch(url):
        return {'error': {
            'message': f'crawling {url} disallowed by robots.txt',
        }}, 403

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

    if not can_fetch(url):
        return {'error': {
            'message': f'crawling {url} disallowed by robots.txt',
        }}, 403

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
    if isinstance(author, list):
        author = ', '.join(author)

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

    directions = parse_descriptions(
        service='direction-parser-service',
        descriptions=scrape.instructions().split('\n')
    )
    ingredients = scrape.ingredients()
    try:
        ingredients = parse_descriptions(
            service='ingredient-parser-service',
            descriptions=ingredients
        )
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
        if not yields[0].isnumeric():
            yields = get_yields(yields)
        tokens = yields.split()
        try:
            servings = int(tokens[0])
            if servings == 0:
                raise ValueError
        except Exception:
            return {'error': {
                'message': f'servings parsing failed for: {yields}',
            }}, 400

    try:
        nutrients = scrape.nutrients()
    except NotImplementedError:
        nutrients = {}
    nutrients = {
        field: nutrients[source]
        for field, source in NUTRITION_SCHEMA_FIELDS.items()
        if source in nutrients
    }
    quantities = parse_descriptions(
        service='quantity-parser-service',
        descriptions=nutrients.values(),
    )
    nutrition = {}
    for idx, field in enumerate(nutrients):
        quantity = quantities[idx]
        nutrition[f'{field}'] = quantity['magnitude']
        nutrition[f'{field}_units'] = quantity['units']
    nutrition = nutrition or None

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
            'nutrition': nutrition,
            'servings': servings,
            'time': time,
            'rating': rating,
        },
    }
