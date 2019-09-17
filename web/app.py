from datetime import datetime, timedelta
from flask import Flask, abort, jsonify, request
import tldextract
from time import sleep
from urllib.parse import urljoin

import requests
from requests.exceptions import ConnectionError, ReadTimeout
def request_patch(self, *args, **kwargs):
    kwargs['proxies'] = {
        'http': 'http://localhost:3128',
        'https': 'http://localhost:3128',
    }
    kwargs['timeout'] = kwargs.pop('timeout', 5)
    kwargs['verify'] = '/etc/squid/certificates/ca.crt'
    return self.request_orig(*args, **kwargs)
setattr(requests.sessions.Session, 'request_orig', requests.sessions.Session.request)
requests.sessions.Session.request = request_patch


from recipe_scrapers import (
    SCRAPERS,
    scrape_me as scrape_recipe,
    WebsiteNotImplementedError,
)

app = Flask(__name__)


def parse_ingredients(ingredients):
    url = 'http://localhost:5000'
    qs = {'ingredients[]': ingredients}
    response = requests.get(url=url, params=qs).json()
    return list(response.values())


domain_backoffs = {}



@app.route('/', methods=['POST'])
def root():
    url = request.form.get('url')
    if not url:
        return abort(400)

    url_info = tldextract.extract(url)
    domain = f'{url_info.domain}.{url_info.suffix}'

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
        scraped_image = scrape.image()
    except NotImplementedError:
        return abort(501)

    if not scraped_image:
        return abort(404)

    ingredients = parse_ingredients(scrape.ingredients())
    if not ingredients:
        return abort(404)

    time = scrape.total_time()
    if not time:
        return abort(404)

    directions = [
        {'description': d.strip()}
        for d in scrape.instructions().split('\n')
    ]
    servings = int(scrape.yields().split(' ')[0] or '1')

    return jsonify({
        'title': scrape.title(),
        'src': url,
        'domain': domain,
        'ingredients': ingredients,
        'directions': directions,
        'image': urljoin(url, scraped_image),
        'servings': servings,
        'time': time,
    })
