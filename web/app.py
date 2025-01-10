from datetime import UTC, datetime, timedelta
from os import getenv
from time import sleep

from flask import Flask, request
from recipe_scrapers.__version__ import __version__ as rs_version
from requests.exceptions import ConnectionError, HTTPError, ReadTimeout

from web.domains import domain_backoffs, get_domain
from web.exceptions import (
    CanonicalURLNotFound,
    DomainConfigurationUnavailable,
    DomainCrawlProhibited,
)
from web.parsing import parse_retry_duration, scrape_recipe, scrape_canonical_url
from web.robots import can_fetch
from web.web_clients import select_client

app = Flask(__name__)
image_version = getenv("IMAGE_VERSION")


def _service_metadata():
    return {
        "service_version": image_version,
        "recipe_scrapers_version": rs_version,
    }


@app.route("/resolve", methods=["POST"])
def resolve():
    url = request.form.get("url")
    if not url:
        message = "url parameter is required"
        return {"error": {"message": message}}, 400

    if not can_fetch(url):
        message = f"crawling {url} disallowed by robots.txt"
        return {"error": {"message": message}}, 403

    domain = get_domain(url)
    try:
        domain_http_client, headers = select_client(domain)
    except DomainConfigurationUnavailable:
        message = f"unable to retrieve {url} domain configuration"
        return {"error": {"message": message}}, 500
    except DomainCrawlProhibited:
        message = f"url resolution of {url} disallowed by configuration"
        return {"error": {"message": message}}, 403

    if domain in domain_backoffs:
        start = domain_backoffs[domain]["timestamp"]
        duration = domain_backoffs[domain]["duration"]

        if datetime.now(tz=UTC) < (start + duration):
            print(f"* Backing off for {domain}")
            sleep(duration.seconds)
            message = f"backing off for {domain}"
            return {"error": {"message": message}}, 429

    retry_duration = 0
    try:
        response = domain_http_client.get(url, headers=headers, timeout=5)
        if not response.ok and "Retry-After" in response.headers:
            retry_duration = parse_retry_duration(
                from_moment=datetime.now(tz=UTC),
                retry_after=response.headers["Retry-After"],
            )
    except (ConnectionError, ReadTimeout):
        duration = timedelta(seconds=1)
        if domain in domain_backoffs:
            duration += domain_backoffs[domain]["duration"]
        domain_backoffs[domain] = {
            "timestamp": datetime.now(tz=UTC),
            "duration": duration,
        }
        print(f"* Setting backoff on {domain} for {duration.seconds} seconds")
        sleep(duration.seconds)
        message = f"timeout; adding backoff for {domain}"
        return {"error": {"message": message}}, 429
    finally:
        if retry_duration:
            existing_duration = domain_backoffs.get(domain, {}).get("duration") or 0
            domain_backoffs[domain] = {
                "timestamp": datetime.now(tz=UTC),
                "duration": max(existing_duration, retry_duration),
            }

    if not response.ok:
        message = f"received non-success status code from {url}"
        return {"error": {"message": message}}, 400

    # Attempt to identify a canonical URL from the response
    try:
        canonical_url = scrape_canonical_url(response)
    except CanonicalURLNotFound:
        canonical_url = None

    return {
        "metadata": _service_metadata(),
        "url": {"resolves_to": canonical_url or response.url},
    }


@app.route("/crawl", methods=["POST"])
def crawl():
    url = request.form.get("url")
    if not url:
        message = "url parameter is required"
        return {"error": {"message": message}}, 400

    if not can_fetch(url):
        message = f"crawling {url} disallowed by robots.txt"
        return {"error": {"message": message}}, 403

    domain = get_domain(url)
    try:
        domain_http_client, headers = select_client(domain)
    except DomainConfigurationUnavailable:
        message = f"unable to retrieve {url} domain configuration"
        return {"error": {"message": message}}, 500
    except DomainCrawlProhibited:
        message = f"crawling {url} disallowed by configuration"
        return {"error": {"message": message}}, 403

    if domain in domain_backoffs:
        start = domain_backoffs[domain]["timestamp"]
        duration = domain_backoffs[domain]["duration"]

        if datetime.now(tz=UTC) < (start + duration):
            print(f"* Backing off for {domain}")
            sleep(duration.seconds)
            message = f"backing off for {domain}"
            return {"error": {"message": message}}, 429

    retry_duration = 0
    try:
        response = domain_http_client.get(url, headers=headers, timeout=5)
        if not response.ok and "Retry-After" in response.headers:
            retry_duration = parse_retry_duration(
                from_moment=datetime.now(tz=UTC),
                retry_after=response.headers["Retry-After"],
            )
        response.raise_for_status()
    except HTTPError:
        message = f"received non-success status code from {url}"
        return {"error": {"message": message}}, response.status_code
    except (ConnectionError, ReadTimeout):
        duration = timedelta(seconds=1)
        if domain in domain_backoffs:
            duration += domain_backoffs[domain]["duration"]
        domain_backoffs[domain] = {
            "timestamp": datetime.now(tz=UTC),
            "duration": duration,
        }
        print(f"* Setting backoff on {domain} for {duration.seconds} seconds")
        sleep(duration.seconds)
        message = f"timeout; adding backoff for {domain}"
        return {"error": {"message": message}}, 429
    finally:
        if retry_duration:
            existing_duration = domain_backoffs.get(domain, {}).get("duration") or 0
            domain_backoffs[domain] = {
                "timestamp": datetime.now(tz=UTC),
                "duration": max(existing_duration, retry_duration),
            }

    return {
        "metadata": _service_metadata(),
        "recipe": scrape_recipe(url, domain, response),
    }
