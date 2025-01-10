from collections import OrderedDict

import pytest

from responses import matchers

from web.app import app


@pytest.fixture
def client():
    return app.test_client()


@pytest.fixture
def unproxied_matcher():
    return matchers.request_kwargs_matcher({"proxies": OrderedDict()})


@pytest.fixture
def cache_proxy_matcher():
    protocols = ("http", "https")
    proxies = OrderedDict([(protocol, "http://proxy:3128") for protocol in protocols])
    return matchers.request_kwargs_matcher({"proxies": proxies})
