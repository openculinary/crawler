import pytest
import responses
from unittest.mock import patch

from web.app import get_domain


@pytest.fixture
def origin_url():
    return 'https://recipe.subdomain.example.com/recipe/123'


@pytest.fixture
def content_url(origin_url):
    return origin_url.replace('subdomain', 'migrated')


def test_get_domain(origin_url):
    domain = get_domain(origin_url)

    assert domain == 'example.com'


@responses.activate
@patch('web.app.determine_image_version')
def test_origin_url_resolution(image_version, client, origin_url, content_url):
    redir_headers = {'Location': content_url}
    responses.add(responses.GET, origin_url, status=301, headers=redir_headers)
    responses.add(responses.GET, content_url, status=200)

    response = client.post('/resolve', data={'url': origin_url})
    recipe_url = response.json['resolves_to']

    assert recipe_url == content_url
