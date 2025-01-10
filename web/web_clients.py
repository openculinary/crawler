from datetime import UTC, datetime
import ssl
from time import sleep

import requests
from requests.adapters import HTTPAdapter
from requests.utils import default_user_agent as requests_user_agent


HEADERS_DEFAULT = {
    "User-Agent": (
        "Mozilla/5.0 ("
        "compatible; "
        "Linux x86_64; "
        f"{requests_user_agent()}; "
        "RecipeRadar/0.1; "
        "+https://www.reciperadar.com"
        ")"
    )
}
HEADERS_NOCACHE = {"Cache-Control": "no-store"}


class ProxyCacheHTTPAdapter(HTTPAdapter):
    def _get_tls_context(self):
        context = ssl.create_default_context(cafile="/etc/ssl/k8s/proxy-cert/ca.crt")
        context.verify_flags &= ~ssl.VERIFY_X509_STRICT
        while True:
            yield context

    def build_connection_pool_key_attributes(self, *args, **kwargs):
        params = super().build_connection_pool_key_attributes(*args, **kwargs)
        _, context_params = params
        context_params["ssl_context"] = next(self._get_tls_context())
        return params


class DelayableRedirectSession(requests.Session):

    def resolve_redirects(self, response, *args, **kwargs):
        from web.parsing import parse_retry_duration

        if "Retry-After" in response.headers:
            duration = parse_retry_duration(
                from_moment=datetime.now(tz=UTC),
                retry_after=response.headers["Retry-After"],
            )
            sleep(duration)
        yield from super().resolve_redirects(response, *args, **kwargs)


microservice_client = requests.Session()
proxy_cache_client = DelayableRedirectSession()
proxy_cache_client.proxies.update(
    {
        "http": "http://proxy:3128",
        "https": "http://proxy:3128",
    }
)
proxy_cache_client.mount("https://", ProxyCacheHTTPAdapter())
web_client = DelayableRedirectSession()


def select_client(domain):
    from web.domains import can_cache, get_domain_configuration

    domain_config = get_domain_configuration(domain)
    cacheable = can_cache(domain_config)
    domain_http_client = proxy_cache_client if cacheable else web_client
    headers = HEADERS_DEFAULT if cacheable else {**HEADERS_DEFAULT, **HEADERS_NOCACHE}
    return domain_http_client, headers
