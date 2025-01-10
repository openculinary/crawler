from time import time
from urllib.parse import urljoin

from cacheout import Cache
import requests
from robotexclusionrulesparser import RobotExclusionRulesParser, _Ruleset

from web.domains import get_domain
from web.web_clients import HEADERS_DEFAULT

web_client = requests.Session()


domain_robot_parsers = Cache(ttl=60 * 60, timer=time)  # 1hr cache expiry


# Workaround: recognize robots.txt rulesets containining solely a crawl-delay.
class _PatchedRuleset(_Ruleset):
    _is_not_empty = _Ruleset.is_not_empty

    def is_not_empty(self):
        return _PatchedRuleset._is_not_empty(self) or self.crawl_delay is not None


_Ruleset.is_not_empty = _PatchedRuleset.is_not_empty


def get_robot_parser(url):
    domain = get_domain(url)
    if domain not in domain_robot_parsers:
        robot_parser = RobotExclusionRulesParser()
        robots_txt = web_client.get(urljoin(url, "/robots.txt"))
        robot_parser.parse(robots_txt.content)
        domain_robot_parsers.set(domain, robot_parser)
    return domain_robot_parsers.get(domain)


def can_fetch(url):
    robot_parser = get_robot_parser(url)
    user_agent = HEADERS_DEFAULT.get("User-Agent", "*")
    return robot_parser.is_allowed(user_agent, url)


def crawl_delay(url):
    robot_parser = get_robot_parser(url)
    user_agent = HEADERS_DEFAULT.get("User-Agent", "*")
    return max(1, robot_parser.get_crawl_delay(user_agent) or 0)
