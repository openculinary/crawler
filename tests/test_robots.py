import responses

from web.app import get_robot_parser


@responses.activate
def test_get_robot_parser(unproxied_matcher):
    responses.get("https://example.test/robots.txt", match=[unproxied_matcher])

    target_url = "https://example.test/foo/bar"
    robot_parser = get_robot_parser(target_url)

    assert robot_parser is not None
    assert robot_parser.is_allowed("*", target_url)
