from web.app import get_domain


def test_request(client):
    client.post('/')


def test_get_domain():
    domain = get_domain('https://recipe.subdomain.example.com/recipe/123')

    assert domain == 'example.com'
