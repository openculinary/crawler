from time import time
from urllib.parse import urljoin

from cacheout import Cache
from tld import get_tld
import requests
from robotexclusionrulesparser import RobotExclusionRulesParser

from web.web_clients import HEADERS_DEFAULT

web_client = requests.Session()


domain_robot_parsers = Cache(ttl=60 * 60, timer=time)  # 1hr cache expiry


def get_domain(url):
    url_info = get_tld(url, as_object=True, search_private=False)
    return url_info.fld


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
