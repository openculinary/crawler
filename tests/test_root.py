import re

from dulwich import porcelain
import pytest
import responses
from recipe_scrapers import StaticValueException
from responses import matchers
from unittest.mock import patch

from web.app import app, get_domain, get_robot_parser


@pytest.fixture
def origin_url():
    return "https://recipe.subdomain.example.com/recipe/123"


@pytest.fixture
def content_url(origin_url):
    return origin_url.replace("subdomain", "migrated")


@pytest.fixture
def user_agent_matcher():
    expected_headers = {
        "User-Agent": re.compile(r".*\bRecipeRadar\b.*"),
    }
    return matchers.header_matcher(expected_headers)


def test_get_domain(origin_url):
    domain = get_domain(origin_url)

    assert domain == "example.com"


def test_url_resolution_validation(client):
    response = client.post("/crawl", data={})

    assert response.status_code == 400


@responses.activate
@patch("web.app.can_fetch")
def test_origin_url_resolution(
    can_fetch,
    client,
    user_agent_matcher,
    origin_url,
    content_url,
):
    can_fetch.return_value = True
    headers = {"Location": content_url}
    responses.get(origin_url, match=[user_agent_matcher], status=301, headers=headers)
    responses.get(content_url, match=[user_agent_matcher], status=200)

    response = client.post("/resolve", data={"url": origin_url})
    metadata = response.json.get("metadata")
    service_version = metadata.get("service_version")

    recipe_url = response.json["url"]["resolves_to"]

    # dulwich v0.20.50: porcelain.describe adds a single-character 'g' prefix
    dulwich_version = porcelain.describe(".")
    assert dulwich_version.startswith("g")

    assert service_version == dulwich_version[1:]
    assert recipe_url == content_url


@responses.activate
@patch("web.app.can_fetch")
def test_error_url_resolution(
    can_fetch,
    client,
    user_agent_matcher,
    origin_url,
    content_url,
):
    can_fetch.return_value = True
    responses.get(origin_url, match=[user_agent_matcher], status=404)

    response = client.post("/resolve", data={"url": origin_url})
    error = response.json.get("error")

    assert error is not None
    assert "url" not in response.json


@pytest.fixture
def scrape_result():
    class ScrapeResult:
        def title(self):
            return "test"

        def author(self):
            raise StaticValueException(return_value="test author")

        def image(self):
            return "test.png"

        def instructions(self):
            return "test"

        def instructions_list(self):
            return ["test"]

        def total_time(self):
            return 60

        def ingredients(self):
            return ["test"]

        def nutrients(self):
            return {
                "calories": "20 cal",
                "carbohydrateContent": "5 g",
                "fatContent": "1 g",
                "fiberContent": "1 g",
                "proteinContent": "2 g",
            }

        def ratings(self):
            return 5

        def yields(self):
            return "Makes 2"

        def language(self):
            raise StaticValueException(return_value="en")

    return ScrapeResult()


@patch("requests.get")
@patch("web.app.parse_descriptions")
@patch("web.app.scrape_html")
@patch("web.app.can_fetch")
def test_crawl_response(
    can_fetch,
    scrape_html,
    parse_descriptions,
    get,
    client,
    content_url,
    scrape_result,
):
    # HACK: Ensure that app initialization methods (re)run during this test
    app._got_first_request = False

    can_fetch.return_value = True
    scrape_html.return_value = scrape_result
    parse_descriptions.side_effect = [
        ["test ingredient"],
        ["test direction"],
        [
            {"magnitude": 5, "units": "g"},
            {"magnitude": 83.68, "units": "J"},
            {"magnitude": 1, "units": "g"},
            {"magnitude": 1, "units": "g"},
            {"magnitude": 2, "units": "g"},
        ],
    ]

    response = client.post("/crawl", data={"url": content_url})
    metadata = response.json.get("metadata", {})
    service_version = metadata.get("service_version")
    rs_version = metadata.get("recipe_scrapers_version")

    # dulwich v0.20.50: porcelain.describe adds a single-character 'g' prefix
    dulwich_version = porcelain.describe(".")
    assert dulwich_version.startswith("g")

    assert response.status_code == 200
    assert service_version == dulwich_version[1:]
    assert rs_version == "15.2.1"

    nutrition = response.json.get("recipe", {}).get("nutrition")
    assert nutrition is not None
    assert nutrition["energy"] == 83.68
    assert nutrition["energy_units"] == "J"

    author = response.json.get("recipe", {}).get("author")
    assert author == "test author"

    language = response.json.get("recipe", {}).get("language_code")
    assert language == "en"


@patch("web.app.scrape_html")
@patch("web.app.can_fetch")
def test_robots_txt_crawl_filtering(can_fetch, scrape_html, client, content_url):
    can_fetch.return_value = False

    response = client.post("/crawl", data={"url": content_url})

    assert response.status_code == 403
    assert not scrape_html.called


@patch("requests.get")
@patch("web.app.can_fetch")
def test_robots_txt_resolution_filtering(can_fetch, get, client, content_url):
    can_fetch.return_value = False

    response = client.post("/resolve", data={"url": content_url})

    assert response.status_code == 403
    assert not get.called


@responses.activate
def test_get_robot_parser():
    responses.get("https://example.com/robots.txt")

    target_url = "https://example.com/foo/bar"
    robot_parser = get_robot_parser(target_url)

    assert robot_parser is not None
    assert robot_parser.is_allowed("*", target_url)


@responses.activate
@patch("web.app.scrape_html")
def test_http_error_not_crawled(scrape_html, client, user_agent_matcher, content_url):
    responses.get(content_url, match=[user_agent_matcher], status=404)

    response = client.post("/crawl", data={"url": content_url})

    assert response.status_code == 404
    assert not scrape_html.called
