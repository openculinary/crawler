import re
from urllib.parse import urljoin
from unittest.mock import patch

from dulwich import porcelain
import pytest
import responses
from requests import ReadTimeout
from responses import matchers
from recipe_scrapers import StaticValueException

from web.app import app, domain_backoffs, get_domain


@pytest.fixture
def origin_domain():
    return "example.test"


@pytest.fixture
def origin_url(origin_domain):
    return f"https://recipe.subdomain.{origin_domain}/recipe/123"


@pytest.fixture
def content_url(origin_url):
    return origin_url.replace("subdomain", "migrated")


@pytest.fixture
def permissive_robots_txt(origin_url, content_url):
    robots_txts = {
        urljoin(origin_url, "/robots.txt"),
        urljoin(content_url, "/robots.txt"),
    }
    for robots_txt in robots_txts:
        responses.get(robots_txt, body="User-agent: *\nAllow: *\n")


@pytest.fixture
def user_agent_matcher():
    expected_headers = {
        "User-Agent": re.compile(r".*\bRecipeRadar\b.*"),
    }
    return matchers.header_matcher(expected_headers)


@pytest.fixture
def nostore_matcher():
    expected_headers = {"Cache-Control": "no-store"}
    return matchers.header_matcher(expected_headers)


def test_get_domain(origin_url):
    domain = get_domain(origin_url)

    assert domain == "example.test"


def test_url_resolution_validation(client):
    response = client.post("/crawl", data={})

    assert response.status_code == 400


@responses.activate
def test_origin_url_resolution(
    client,
    user_agent_matcher,
    cache_proxy_matcher,
    permissive_robots_txt,
    origin_url,
    content_url,
):
    headers = {"Location": content_url}
    responses.get(
        "http://backend-service/domains/example.test",
        json={},
    )
    responses.get(
        origin_url,
        headers=headers,
        status=301,
        match=[user_agent_matcher, cache_proxy_matcher],
    )
    responses.get(
        content_url,
        status=200,
        match=[user_agent_matcher, cache_proxy_matcher],
    )

    response = client.post("/resolve", data={"url": origin_url})
    metadata = response.json.get("metadata")
    service_version = metadata.get("service_version")

    recipe_url = response.json["url"]["resolves_to"]

    # dulwich v0.20.50: porcelain.describe adds a single-character 'g' prefix
    dulwich_version = porcelain.describe(".", abbrev=None)
    assert dulwich_version.startswith("g")

    assert service_version.startswith(dulwich_version[1:])
    assert recipe_url == content_url


@responses.activate
def test_error_url_resolution(
    client,
    user_agent_matcher,
    cache_proxy_matcher,
    permissive_robots_txt,
    origin_url,
    content_url,
):
    responses.get(
        "http://backend-service/domains/example.test",
        json={},
    )
    responses.get(
        origin_url,
        status=404,
        match=[user_agent_matcher, cache_proxy_matcher],
    )

    response = client.post("/resolve", data={"url": origin_url})
    error = response.json.get("error")

    assert error is not None
    assert "url" not in response.json


@responses.activate
@pytest.mark.parametrize("endpoint", ["resolve", "crawl"])
def test_fetch_endpoints_timeout_backoff(
    client,
    permissive_robots_txt,
    origin_url,
    endpoint,
):
    responses.get(
        "http://backend-service/domains/example.test",
        json={},
    )
    responses.get(
        origin_url,
        body=ReadTimeout(),
    )

    response = client.post(f"/{endpoint}", data={"url": origin_url})
    error = response.json.get("error")

    assert error is not None
    assert "adding backoff" in error["message"]
    assert "url" not in response.json


@responses.activate
@pytest.mark.parametrize("endpoint", ["resolve", "crawl"])
@patch.dict(domain_backoffs, clear=True)
def test_fetch_endpoints_respect_server_backoff(
    client,
    origin_domain,
    permissive_robots_txt,
    origin_url,
    endpoint,
):
    assert len(domain_backoffs) == 0

    responses.get(
        "http://backend-service/domains/example.test",
        json={},
    )
    responses.get(
        origin_url,
        status=503,
        headers={"Retry-After": "3600"},
    )

    response = client.post(f"/{endpoint}", data={"url": origin_url})
    error = response.json.get("error")

    assert error is not None
    assert "url" not in response.json
    assert origin_domain in domain_backoffs


@responses.activate
@pytest.mark.parametrize("endpoint", ["resolve", "crawl"])
@patch.dict(domain_backoffs, clear=True)
@patch("web.web_clients.sleep")
def test_fetch_endpoints_respect_server_redirect_backoff(
    sleep,
    client,
    origin_domain,
    permissive_robots_txt,
    origin_url,
    content_url,
    endpoint,
):
    assert len(domain_backoffs) == 0

    responses.get(
        "http://backend-service/domains/example.test",
        json={},
    )
    responses.get(
        origin_url,
        status=302,
        headers={
            "Location": content_url,
            "Retry-After": "0.1",
        },
    )
    responses.get(
        content_url,
        status=200,
    )

    response = client.post(f"/{endpoint}", data={"url": origin_url})
    error = response.json.get("error")

    sleep.assert_called_once_with(1)  # 0.1 rounded up to 1
    assert error is None
    assert origin_domain not in domain_backoffs


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


@patch("requests.sessions.Session.get")
@patch("web.parsing.parse_descriptions")
@patch("web.parsing.scrape_html")
def test_crawl_response(
    scrape_html,
    parse_descriptions,
    get,
    client,
    permissive_robots_txt,
    content_url,
    scrape_result,
):
    # HACK: Ensure that app initialization methods (re)run during this test
    app._got_first_request = False

    scrape_html.return_value = scrape_result
    parse_descriptions.side_effect = [
        ["test ingredient"],
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
    dulwich_version = porcelain.describe(".", abbrev=None)
    assert dulwich_version.startswith("g")

    assert response.status_code == 200
    assert service_version.startswith(dulwich_version[1:])
    assert rs_version == "15.3.3"

    nutrition = response.json.get("recipe", {}).get("nutrition")
    assert nutrition is not None
    assert nutrition["energy"] == 83.68
    assert nutrition["energy_units"] == "J"

    author = response.json.get("recipe", {}).get("author")
    assert author == "test author"

    language = response.json.get("recipe", {}).get("language_code")
    assert language == "en"


@patch("web.parsing.scrape_html")
@patch("web.app.can_fetch")
def test_robots_txt_crawl_filtering(can_fetch, scrape_html, client, content_url):
    can_fetch.return_value = False

    response = client.post("/crawl", data={"url": content_url})

    assert response.status_code == 403
    assert not scrape_html.called


@patch("requests.sessions.Session.get")
@patch("web.app.can_fetch")
def test_robots_txt_resolution_filtering(can_fetch, get, client, content_url):
    can_fetch.return_value = False

    response = client.post("/resolve", data={"url": content_url})

    assert response.status_code == 403
    assert not get.called


@responses.activate
@patch("web.parsing.scrape_html")
def test_domain_config_unavailable_not_crawled(scrape_html, client, content_url):
    responses.get(
        "http://backend-service/domains/example.test",
        status=500,
    )

    client.post("/crawl", data={"url": content_url})

    assert not scrape_html.called


@responses.activate
@patch("web.parsing.scrape_html")
def test_http_crawl_disabled_not_crawled(scrape_html, client, content_url):
    responses.get(
        "http://backend-service/domains/example.test",
        json={"crawl_enabled": False},
    )

    client.post("/crawl", data={"url": content_url})

    assert not scrape_html.called


@responses.activate
@patch("web.parsing.scrape_html")
def test_http_cache_disabled_direct_access(
    scrape_html,
    client,
    unproxied_matcher,
    nostore_matcher,
    content_url,
):
    responses.get(
        "http://backend-service/domains/example.test",
        json={"cache_enabled": False},
    )
    responses.get(
        content_url,
        status=200,
        match=[unproxied_matcher, nostore_matcher],
    )

    client.post("/crawl", data={"url": content_url})

    assert scrape_html.called


@responses.activate
@patch("web.parsing.scrape_html")
def test_http_error_not_crawled(
    scrape_html,
    client,
    user_agent_matcher,
    cache_proxy_matcher,
    content_url,
):
    responses.get("http://backend-service/domains/example.test", json={})
    responses.get(
        content_url,
        status=404,
        match=[user_agent_matcher, cache_proxy_matcher],
    )

    response = client.post("/crawl", data={"url": content_url})

    assert response.status_code == 404
    assert not scrape_html.called
