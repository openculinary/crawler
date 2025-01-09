from unittest.mock import patch

import pytest

from tld import get_tld, get_tld_names, update_tld_names

from web.app import app


@pytest.fixture
def client():
    return app.test_client()


@pytest.fixture(autouse=True)
def patch_get_tld():
    with patch("web.robots.get_tld") as mock_get_tld:
        # Add private/reserved .test TLD
        for local_path, domain_trie in get_tld_names().items():
            domain_trie.add("test", private=True)
            update_tld_names(local_path, domain_trie)

        # Passthrough get_tld queries with private-TLD search enabled
        def get_tld_private_enabled(*args, **kwargs):
            kwargs["search_private"] = True
            return get_tld(*args, **kwargs)

        # Return the passthrough get_tld
        mock_get_tld.side_effect = get_tld_private_enabled
        yield mock_get_tld
