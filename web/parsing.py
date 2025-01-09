from web.web_clients import microservice_client


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
