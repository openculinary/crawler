from datetime import UTC, datetime, timedelta
from os import getenv
from time import sleep

from flask import Flask, request
from requests.exceptions import ConnectionError, HTTPError, ReadTimeout

from recipe_scrapers.__version__ import __version__ as rs_version
from recipe_scrapers._utils import get_yields
from recipe_scrapers import (
    StaticValueException,
    WebsiteNotImplementedError,
    scrape_html,
)

from web.domains import (
    get_domain,
    get_domain_configuration,
    can_cache,
    can_crawl,
)
from web.parsing import parse_descriptions
from web.robots import can_fetch, get_robot_parser  # NoQA
from web.web_clients import (
    HEADERS_DEFAULT,
    HEADERS_NOCACHE,
    proxy_cache_client,
    web_client,
)

NUTRITION_SCHEMA_FIELDS = {
    "carbohydrates": "carbohydrateContent",
    "energy": "calories",
    "fat": "fatContent",
    "fibre": "fiberContent",
    "protein": "proteinContent",
}


app = Flask(__name__)
domain_backoffs = {}
image_version = getenv("IMAGE_VERSION")


@app.route("/resolve", methods=["POST"])
def resolve():
    url = request.form.get("url")
    if not url:
        message = "url parameter is required"
        return {"error": {"message": message}}, 400

    if not can_fetch(url):
        message = f"crawling {url} disallowed by robots.txt"
        return {"error": {"message": message}}, 403

    domain = get_domain(url)
    try:
        domain_config = get_domain_configuration(domain)
    except Exception:
        message = f"unable to retrieve {url} domain configuration"
        return {"error": {"message": message}}, 500

    if not can_crawl(domain_config):
        message = f"url resolution of {url} disallowed by configuration"
        return {"error": {"message": message}}, 403

    cacheable = can_cache(domain_config)
    domain_http_client = proxy_cache_client if cacheable else web_client
    headers = HEADERS_DEFAULT if cacheable else {**HEADERS_DEFAULT, **HEADERS_NOCACHE}

    response = domain_http_client.get(url, headers=headers, timeout=5)
    if not response.ok:
        message = f"received non-success status code from {url}"
        return {"error": {"message": message}}, 400

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
        message = "url parameter is required"
        return {"error": {"message": message}}, 400

    if not can_fetch(url):
        message = f"crawling {url} disallowed by robots.txt"
        return {"error": {"message": message}}, 403

    domain = get_domain(url)
    try:
        domain_config = get_domain_configuration(domain)
    except Exception:
        message = f"unable to retrieve {url} domain configuration"
        return {"error": {"message": message}}, 500

    if not can_crawl(domain_config):
        message = f"crawling {url} disallowed by configuration"
        return {"error": {"message": message}}, 403

    if domain in domain_backoffs:
        start = domain_backoffs[domain]["timestamp"]
        duration = domain_backoffs[domain]["duration"]

        if datetime.now(tz=UTC) < (start + duration):
            print(f"* Backing off for {domain}")
            sleep(duration.seconds)
            message = f"backing off for {domain}"
            return {"error": {"message": message}}, 429

    cacheable = can_cache(domain_config)
    domain_http_client = proxy_cache_client if cacheable else web_client
    headers = HEADERS_DEFAULT if cacheable else {**HEADERS_DEFAULT, **HEADERS_NOCACHE}

    try:
        response = domain_http_client.get(url, headers=headers, timeout=5)
        response.raise_for_status()
        scrape = scrape_html(response.text, response.url)
    except HTTPError:
        message = f"received non-success status code from {url}"
        return {"error": {"message": message}}, response.status_code
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
        message = f"timeout; adding backoff for {domain}"
        return {"error": {"message": message}}, 429
    except WebsiteNotImplementedError:
        message = "website is not implemented"
        return {"error": {"message": message}}, 501

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
        message = f"ingredient parsing failed for: {ingredients}"
        return {"error": {"message": message}}, 400

    if not ingredients:
        message = "could not find recipe ingredient"
        return {"error": {"message": message}}, 404

    time = scrape.total_time()
    if not time:
        message = "could not find recipe timing info"
        return {"error": {"message": message}}, 404

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
            message = f"servings parsing failed for: {yields}"
            return {"error": {"message": message}}, 400

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
            "author": author,
            "nutrition": nutrition,
            "servings": servings,
            "time": time,
            "rating": rating,
            "language_code": language_code,
        },
    }
