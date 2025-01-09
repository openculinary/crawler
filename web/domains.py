from tld import get_tld

from web.web_clients import microservice_client


def get_domain(url):
    url_info = get_tld(url, as_object=True, search_private=False)
    return url_info.fld


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
