from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from math import ceil
from string import digits

from recipe_scrapers._utils import get_yields
from recipe_scrapers import (
    StaticValueException,
    WebsiteNotImplementedError,
    scrape_html,
)

from web.exceptions import CanonicalURLNotFound
from web.web_clients import microservice_client

NUTRITION_SCHEMA_FIELDS = {
    "carbohydrates": "carbohydrateContent",
    "energy": "calories",
    "fat": "fatContent",
    "fibre": "fiberContent",
    "protein": "proteinContent",
}


def parse_retry_duration(from_moment: datetime, retry_after: str) -> int:
    retry_after = retry_after.strip()
    if not retry_after:
        return 0

    if retry_after.startswith(tuple(digits)):
        try:
            return ceil(float(retry_after))
        except Exception:
            print(f"* Failed parsing {retry_after!r} as integer; delaying for 1min")
            return 60

    try:
        dt = parsedate_to_datetime(retry_after)
    except ValueError:
        print(f"* Failed to parse {retry_after!r} as HTTP Date; delaying for 1min")
        return 60

    if not dt.tzinfo:
        print(f"* Ambiguous/missing timezone parsed for {retry_after!r}; assuming UTC")
        dt = dt.replace(tzinfo=UTC)

    if dt < from_moment:
        print(f"* HTTP Date {retry_after!r} predates the moment; delaying for 1min")
        return 60

    return ceil((dt - from_moment).total_seconds())


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


def scrape_canonical_url(response):
    try:
        scrape = scrape_html(
            html=response.text,
            org_url=response.url,
            online=False,
            supported_only=True,
        )
        return scrape.canonical_url()
    except WebsiteNotImplementedError:
        raise CanonicalURLNotFound


def scrape_recipe(src, domain, response):
    try:
        scrape = scrape_html(
            html=response.text,
            org_url=response.url,
            online=False,
            supported_only=True,
        )
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
        "title": scrape.title(),
        "src": src,
        "domain": domain,
        "ingredients": ingredients,
        "author": author,
        "nutrition": nutrition,
        "servings": servings,
        "time": time,
        "rating": rating,
        "language_code": language_code,
    }
