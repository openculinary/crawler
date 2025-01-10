import responses

from web.robots import get_robot_parser, can_fetch, crawl_delay, domain_robot_parsers


@responses.activate
def test_get_robot_parser(unproxied_matcher):
    responses.get("https://example.test/robots.txt", match=[unproxied_matcher])

    target_url = "https://example.test/foo/bar"
    robot_parser = get_robot_parser(target_url)

    assert robot_parser is not None
    assert robot_parser.is_allowed("*", target_url)


@responses.activate
def test_can_fetch():
    domain_robot_parsers.clear()  # TODO: implicit cache teardown
    responses.get(
        "https://example.test/robots.txt",
        body="\n".join(
            [
                "User-agent: RecipeRadar",
                "Disallow: /recipes/private/*",
                "Allow: /recipes/*",
                "Disallow: *",
            ]
        ),
    )

    statistics_allowed = can_fetch("https://example.test/statistics")
    public_recipe_allowed = can_fetch("https://example.test/recipes/example")
    private_recipe_allowed = can_fetch("https://example.test/recipes/private/other")

    assert statistics_allowed is False
    assert public_recipe_allowed is True
    assert private_recipe_allowed is False


@responses.activate
def test_get_crawl_delay():
    domain_robot_parsers.clear()  # TODO: implicit cache teardown
    responses.get(
        "https://example.test/robots.txt",
        body="\n".join(
            [
                "User-agent: reciperadar",
                "Crawl-delay: 5",
            ]
        ),
    )

    target_url = "https://example.test/foo/bar"
    delay = crawl_delay(target_url)

    assert delay == 5
