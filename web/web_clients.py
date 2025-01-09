import ssl

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


proxy_cache_client = requests.Session()
proxy_cache_client.proxies.update(
    {
        "http": "http://proxy:3128",
        "https": "http://proxy:3128",
    }
)
proxy_cache_client.mount("https://", ProxyCacheHTTPAdapter())
web_client = requests.Session()
