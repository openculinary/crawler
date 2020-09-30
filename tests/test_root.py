import pytest
import responses
from unittest.mock import patch

from web.app import app, get_domain


@pytest.fixture
def origin_url():
    return 'https://recipe.subdomain.example.com/recipe/123'


@pytest.fixture
def content_url(origin_url):
    return origin_url.replace('subdomain', 'migrated')


def test_get_domain(origin_url):
    domain = get_domain(origin_url)

    assert domain == 'example.com'


@patch('web.app.determine_image_version')
def test_url_resolution_validation(image_version, client):
    image_version.return_value = 'test_version'
    response = client.post('/crawl', data={})

    assert response.status_code == 400


@responses.activate
@patch('web.app.determine_image_version')
def test_origin_url_resolution(image_version, client, origin_url, content_url):
    image_version.return_value = 'test_version'
    redir_headers = {'Location': content_url}
    responses.add(responses.GET, origin_url, status=301, headers=redir_headers)
    responses.add(responses.GET, content_url, status=200)

    response = client.post('/resolve', data={'url': origin_url})
    metadata = response.json.get('metadata')
    service_version = metadata.get('service_version')

    recipe_url = response.json['url']['resolves_to']

    assert service_version == 'test_version'
    assert recipe_url == content_url


@pytest.fixture
def scrape_result():
    class ScrapeResult(object):

        def title(self):
            return 'test'

        def image(self):
            return 'test.png'

        def instructions(self):
            return 'test'

        def total_time(self):
            return 60

        def ingredients(self):
            return ['test']

        def ratings(self):
            return 5

        def yields(self):
            return '1'

    return ScrapeResult()


@patch('web.app.parse_ingredients')
@patch('web.app.parse_directions')
@patch('web.app.scrape_recipe')
@patch('web.app.determine_image_version')
def test_crawl_response(image_version, scrape_recipe, parse_directions,
                        parse_ingredients, client, content_url, scrape_result):
    # HACK: Ensure that app initialization methods (re)run during this test
    app._got_first_request = False

    image_version.return_value = 'test_version'
    scrape_recipe.return_value = scrape_result
    parse_directions.return_value = ['test direction']
    parse_ingredients.return_value = ['test ingredient']

    response = client.post('/crawl', data={'url': content_url})
    metadata = response.json.get('metadata', {})
    service_version = metadata.get('service_version')
    rs_version = metadata.get('recipe_scrapers_version')

    assert response.status_code == 200
    assert service_version == 'test_version'
    assert rs_version == '9.2.4'
