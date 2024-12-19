from datetime import UTC, datetime, timedelta
from os import getenv
import ssl
from time import sleep, time
from urllib.parse import urljoin

from cacheout import Cache
from flask import Flask, request
from tld import get_tld
import requests
from requests.adapters import HTTPAdapter
from requests.exceptions import ConnectionError, HTTPError, ReadTimeout
from requests.utils import default_user_agent as requests_user_agent
from robotexclusionrulesparser import RobotExclusionRulesParser

from recipe_scrapers.__version__ import __version__ as rs_version
from recipe_scrapers._utils import get_yields
from recipe_scrapers import (
    StaticValueException,
    WebsiteNotImplementedError,
    scrape_html,
)

HEADERS_DEFAULT = {
    "User-Agent": (
        "Mozilla/5.0 ("
        "compatible; "
        "Linux x86_64; "
        f"{requests_user_agent()}; "
        "RecipeRadar/0.1; "
        "+https://www.reciperadar.com"
        ")"
    )
}
HEADERS_NOCACHE = {"Cache-Control": "no-cache"}

NUTRITION_SCHEMA_FIELDS = {
    "carbohydrates": "carbohydrateContent",
    "energy": "calories",
    "fat": "fatContent",
    "fibre": "fiberContent",
    "protein": "proteinContent",
}


class ProxyCacheHTTPAdapter(HTTPAdapter):
    def _get_tls_context(self):
        context = ssl.create_default_context(cafile="/etc/ssl/k8s/proxy-cert/ca.crt")
        context.verify_flags &= ~ssl.VERIFY_X509_STRICT
        while True:
            yield context

    def build_connection_pool_key_attributes(self, *args, **kwargs):
        params = super().build_connection_pool_key_attributes(*args, **kwargs)
        _, context_params = params
        context_params["ssl_context"] = next(self._get_tls_context())
        return params


microservice_client = requests.Session()
proxy_cache_client = requests.Session()
proxy_cache_client.proxies.update(
    {
        "http": "http://proxy:3128",
        "https": "http://proxy:3128",
    }
)
proxy_cache_client.mount("https://", ProxyCacheHTTPAdapter())
web_client = requests.Session()


app = Flask(__name__)
image_version = getenv("IMAGE_VERSION")


def parse_descriptions(service, language_code, descriptions):
    entities = microservice_client.post(
        url=f"http://{service}",
        data={
            "language_code": language_code,
            "descriptions[]": descriptions,
        },
        proxies={},
    ).json()
    return [{**{"index": index}, **entity} for index, entity in enumerate(entities)]


domain_backoffs = {}
domain_robot_parsers = Cache(ttl=60 * 60, timer=time)  # 1hr cache expiry


def get_domain(url):
    url_info = get_tld(url, as_object=True, search_private=False)
    return url_info.fld


def get_robot_parser(url):
    domain = get_domain(url)
    if domain not in domain_robot_parsers:
        robot_parser = RobotExclusionRulesParser()
        robots_txt = web_client.get(urljoin(url, "/robots.txt"))
        robot_parser.parse(robots_txt.content)
        domain_robot_parsers.set(domain, robot_parser)
    return domain_robot_parsers.get(domain)


def get_domain_configuration(domain):
    response = microservice_client.get(
        url=f"http://backend-service/domains/{domain}",
        proxies={},
    )
    response.raise_for_status()
    return response.json()


def can_crawl(domain_config):
    if domain_config.get("crawl_enabled") is False:
        return False
    return True


def can_fetch(url):
    robot_parser = get_robot_parser(url)
    user_agent = HEADERS_DEFAULT.get("User-Agent", "*")
    return robot_parser.is_allowed(user_agent, url)


def can_cache(domain_config):
    if domain_config.get("cache_enabled") is False:
        return False
    return True


@app.route("/resolve", methods=["POST"])
def resolve():
    url = request.form.get("url")
    if not url:
        return {
            "error": {
                "message": "url parameter is required",
            }
        }, 400

    if not can_fetch(url):
        return {
            "error": {
                "message": f"crawling {url} disallowed by robots.txt",
            }
        }, 403

    domain = get_domain(url)
    try:
        domain_config = get_domain_configuration(domain)
    except Exception:
        return {
            "error": {
                "message": f"unable to retrieve {url} domain configuration",
            }
        }, 500

    if not can_crawl(domain_config):
        return {
            "error": {
                "message": f"url resolution of {url} disallowed by configuration",
            }
        }, 403

    cacheable = can_cache(domain_config)
    domain_http_client = proxy_cache_client if cacheable else web_client
    headers = HEADERS_DEFAULT if cacheable else {**HEADERS_DEFAULT, **HEADERS_NOCACHE}

    response = domain_http_client.get(url, headers=headers, timeout=5)
    if not response.ok:
        return {
            "error": {
                "message": f"received non-success status code from {url}",
            }
        }, 400

    # Attempt to identify a canonical URL from the response
    canonical_url = None
    try:
        scrape = scrape_html(
            html=response.text,
            org_url=response.url,
            online=False,
            supported_only=True,
        )
        canonical_url = scrape.canonical_url()
    except WebsiteNotImplementedError:
        pass

    return {
        "metadata": {
            "service_version": image_version,
            "recipe_scrapers_version": rs_version,
        },
        "url": {"resolves_to": canonical_url or response.url},
    }


@app.route("/crawl", methods=["POST"])
def crawl():
    url = request.form.get("url")
    if not url:
        return {
            "error": {
                "message": "url parameter is required",
            }
        }, 400

    if not can_fetch(url):
        return {
            "error": {
                "message": f"crawling {url} disallowed by robots.txt",
            }
        }, 403

    domain = get_domain(url)
    try:
        domain_config = get_domain_configuration(domain)
    except Exception:
        return {
            "error": {
                "message": f"unable to retrieve {url} domain configuration",
            }
        }, 500

    if not can_crawl(domain_config):
        return {
            "error": {
                "message": f"crawling {url} disallowed by configuration",
            }
        }, 403

    if domain in domain_backoffs:
        start = domain_backoffs[domain]["timestamp"]
        duration = domain_backoffs[domain]["duration"]

        if datetime.now(tz=UTC) < (start + duration):
            print(f"* Backing off for {domain}")
            sleep(duration.seconds)
            return {
                "error": {
                    "message": f"backing off for {domain}",
                }
            }, 429

    cacheable = can_cache(domain_config)
    domain_http_client = proxy_cache_client if cacheable else web_client
    headers = HEADERS_DEFAULT if cacheable else {**HEADERS_DEFAULT, **HEADERS_NOCACHE}

    try:
        response = domain_http_client.get(url, headers=headers, timeout=5)
        response.raise_for_status()
        scrape = scrape_html(response.text, response.url)
    except HTTPError:
        return {
            "error": {
                "message": f"received non-success status code from {url}",
            }
        }, response.status_code
    except (ConnectionError, ReadTimeout):
        duration = timedelta(seconds=1)
        if domain in domain_backoffs:
            duration += domain_backoffs[domain]["duration"]
        domain_backoffs[domain] = {
            "timestamp": datetime.now(tz=UTC),
            "duration": duration,
        }
        print(f"* Setting backoff on {domain} for {duration.seconds} seconds")
        sleep(duration.seconds)
        return {
            "error": {
                "message": f"timeout; adding backoff for {domain}",
            }
        }, 429
    except WebsiteNotImplementedError:
        return {
            "error": {
                "message": "website is not implemented",
            }
        }, 501

    try:
        author = scrape.author()
    except StaticValueException as static:
        author = static.return_value
    except NotImplementedError:
        author = None
    if isinstance(author, list):
        author = ", ".join(author)

    try:
        language_code = scrape.language()
    except StaticValueException as static:
        language_code = static.return_value

    # Naive filtering for ingredient lines that describe ingredient sub-groups
    #   Example: 'For the sauce:'
    ingredients = [
        ingredient
        for ingredient in scrape.ingredients()
        if not (ingredient[:4].lower() == "for " and ingredient.endswith(":"))
    ]
    try:
        ingredients = parse_descriptions(
            service="ingredient-parser-service",
            language_code=language_code,
            descriptions=ingredients,
        )
    except Exception:
        return {
            "error": {"message": f"ingredient parsing failed for: {ingredients}"}
        }, 400

    if not ingredients:
        return {
            "error": {
                "message": "could not find recipe ingredient",
            }
        }, 404

    instructions = scrape.instructions()
    directions = parse_descriptions(
        service="direction-parser-service",
        language_code=language_code,
        descriptions=(
            instructions if isinstance(instructions, list) else instructions.split("\n")
        ),
    )

    time = scrape.total_time()
    if not time:
        return {
            "error": {
                "message": "could not find recipe timing info",
            }
        }, 404

    servings = 1
    yields = scrape.yields()
    if yields:
        if not isinstance(yields, str):
            yields = str(yields)
        if not yields[0].isnumeric():
            yields = get_yields(yields)
        tokens = yields.split()
        try:
            servings = int(tokens[0])
            if servings == 0:
                raise ValueError
        except Exception:
            return {
                "error": {
                    "message": f"servings parsing failed for: {yields}",
                }
            }, 400

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
        service="quantity-parser-service",
        language_code=language_code,
        descriptions=nutrients.values(),
    )
    nutrition = {}
    for idx, field in enumerate(nutrients):
        quantity = quantities[idx]
        nutrition[f"{field}"] = quantity["magnitude"]
        nutrition[f"{field}_units"] = quantity["units"]
    nutrition = nutrition or None

    try:
        rating = float(scrape.ratings())
    except Exception:
        rating = 4.0
    rating = 3.0 if not 1 <= rating <= 5 else rating
    rating = 4.75 if rating == 5.0 else rating

    return {
        "metadata": {
            "service_version": image_version,
            "recipe_scrapers_version": rs_version,
        },
        "recipe": {
            "title": scrape.title(),
            "src": url,
            "domain": domain,
            "ingredients": ingredients,
            "directions": directions,
            "author": author,
            "nutrition": nutrition,
            "servings": servings,
            "time": time,
            "rating": rating,
            "language_code": language_code,
        },
    }
