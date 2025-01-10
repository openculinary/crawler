from urllib.parse import urlparse

from web.web_clients import microservice_client

domain_backoffs = {}


def get_domain(url):
    return urlparse(url).netloc


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


def can_cache(domain_config):
    if domain_config.get("cache_enabled") is False:
        return False
    return True
