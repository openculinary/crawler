import requests

microservice_client = requests.Session()


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
