from datetime import UTC, datetime, timedelta
from os import getenv
from time import sleep
from urllib.parse import urljoin

from flask import Flask, request
from tld import get_tld
import requests
from requests.exceptions import ConnectionError, HTTPError, ReadTimeout
from robotexclusionrulesparser import RobotExclusionRulesParser

from recipe_scrapers.__version__ import __version__ as rs_version
from recipe_scrapers._abstract import HEADERS
from recipe_scrapers._utils import get_yields
from recipe_scrapers import WebsiteNotImplementedError, scrape_html

NUTRITION_SCHEMA_FIELDS = {
    "carbohydrates": "carbohydrateContent",
    "energy": "calories",
    "fat": "fatContent",
    "fibre": "fiberContent",
    "protein": "proteinContent",
}


def request_patch(self, *args, **kwargs):
    kwargs["proxies"] = kwargs.pop(
        "proxies",
        {
            "http": "http://proxy:3128",
            "https": "http://proxy:3128",
        },
    )
    kwargs["timeout"] = kwargs.pop("timeout", 5)
    kwargs["verify"] = kwargs.pop("verify", "/etc/ssl/k8s/proxy-cert/ca.crt")
    return self.request_orig(*args, **kwargs)


setattr(requests.sessions.Session, "request_orig", requests.sessions.Session.request)
requests.sessions.Session.request = request_patch

app = Flask(__name__)
image_version = getenv("IMAGE_VERSION")


def parse_descriptions(service, language_code, descriptions):
    entities = requests.post(
        url=f"http://{service}",
        data={
            "language_code": language_code,
            "descriptions[]": descriptions,
        },
        proxies={},
    ).json()
    return [{**{"index": index}, **entity} for index, entity in enumerate(entities)]


domain_backoffs = {}
domain_robot_parsers = {}


def get_domain(url):
    url_info = get_tld(url, as_object=True, search_private=False)
    return url_info.fld


def get_robot_parser(url):
    domain = get_domain(url)
    if domain not in domain_robot_parsers:
        robot_parser = RobotExclusionRulesParser()
        robots_txt = requests.get(urljoin(url, "/robots.txt"))
        robot_parser.parse(robots_txt.content)
        domain_robot_parsers[domain] = robot_parser
    return domain_robot_parsers[domain]


def can_fetch(url):
    robot_parser = get_robot_parser(url)
    user_agent = HEADERS.get("User-Agent", "*")
    return robot_parser.is_allowed(user_agent, url)


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

    response = requests.get(url, headers=HEADERS)
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

    try:
        response = requests.get(url, headers=HEADERS)
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
    except NotImplementedError:
        author = None
    if isinstance(author, list):
        author = ", ".join(author)

    try:
        scraped_image = scrape.image() or super(type(scrape), scrape).image()
    except NotImplementedError:
        return {
            "error": {
                "message": "image retrieval is not implemented",
            }
        }, 501

    if not scraped_image:
        return {
            "error": {
                "message": "could not find recipe image",
            }
        }, 404

    language_code = scrape.language()

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
            "image_src": urljoin(url, scraped_image),
            "nutrition": nutrition,
            "servings": servings,
            "time": time,
            "rating": rating,
        },
    }
