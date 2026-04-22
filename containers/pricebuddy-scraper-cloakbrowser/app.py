#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from datetime import datetime, timezone
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from cloakbrowser import launch_async
from flask import Flask, jsonify, request

app = Flask(__name__)
logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

DEFAULT_SLEEP_MS = 2000
DEFAULT_TIMEOUT_MS = 30000
DEFAULT_WAIT_UNTIL = "networkidle"
SUPPORTED_WAIT_UNTIL = {"commit", "domcontentloaded", "load", "networkidle"}
TRUTHY = {"1", "true", "yes", "on"}
DEVICE_CONTEXTS = {
    "desktop chrome": {
        "viewport": {"width": 1280, "height": 720},
        "screen": {"width": 1280, "height": 720},
    },
}


def parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in TRUTHY


def parse_int(value: str | None, default: int) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def normalize_wait_until(value: str | None) -> str:
    if not value:
        return DEFAULT_WAIT_UNTIL
    normalized = value.strip().lower()
    return normalized if normalized in SUPPORTED_WAIT_UNTIL else DEFAULT_WAIT_UNTIL


def parse_extra_headers(raw_value: str | None) -> dict[str, str]:
    if not raw_value:
        return {}

    headers: dict[str, str] = {}
    current: str | None = None

    for segment in raw_value.split(';'):
        part = segment.strip()
        if not part:
            continue
        if ':' in part:
            if current is not None:
                key, value = current.split(':', 1)
                headers[key.strip()] = value.strip()
            current = part
        elif current is not None:
            current = f"{current}; {part}"

    if current is not None and ':' in current:
        key, value = current.split(':', 1)
        headers[key.strip()] = value.strip()

    return headers


def get_device_context(device_name: str | None) -> dict[str, object]:
    if not device_name:
        return {}
    return DEVICE_CONTEXTS.get(device_name.strip().lower(), {})


def collect_meta(soup: BeautifulSoup) -> dict[str, str]:
    meta: dict[str, str] = {}
    for tag in soup.find_all('meta'):
        key = tag.get('name') or tag.get('property') or tag.get('itemprop')
        value = tag.get('content')
        if key and value and key not in meta:
            meta[key] = value.strip()
    return meta


def normalize_text(value: str) -> str:
    return '\n'.join(line.strip() for line in value.splitlines() if line.strip())


def build_article_payload(
    *,
    final_url: str,
    rendered_html: str,
    page_title: str,
    include_full_content: bool,
    query: dict[str, list[str]],
) -> dict[str, object]:
    soup = BeautifulSoup(rendered_html, 'html.parser')
    html_tag = soup.find('html')
    body = soup.find('body')
    meta = collect_meta(soup)

    source = body if body else soup
    text_content = normalize_text(source.get_text('\n', strip=True))
    excerpt = meta.get('description') or meta.get('og:description') or text_content[:280] or None

    content_html = body.decode_contents() if body else rendered_html
    content = f'<article>{content_html}</article>' if content_html else '<article></article>'

    effective_title = (
        page_title
        or meta.get('og:title')
        or (soup.title.get_text(strip=True) if soup.title else None)
        or final_url
    )

    published_time = (
        meta.get('article:published_time')
        or meta.get('og:article:published_time')
        or meta.get('pubdate')
        or meta.get('datePublished')
    )
    byline = meta.get('author') or meta.get('article:author')
    parsed = urlparse(final_url)

    return {
        'title': effective_title,
        'byline': byline,
        'dir': html_tag.get('dir') if html_tag else None,
        'lang': html_tag.get('lang') if html_tag else None,
        'content': content,
        'textContent': text_content,
        'length': len(text_content),
        'excerpt': excerpt,
        'siteName': meta.get('og:site_name') or parsed.netloc,
        'publishedTime': published_time,
        'id': hashlib.sha1(final_url.encode('utf-8')).hexdigest(),
        'url': final_url,
        'domain': parsed.netloc,
        'date': datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
        'resultUri': None,
        'query': query,
        'meta': meta,
        'fullContent': rendered_html if include_full_content else '',
    }


async def render_page(
    *,
    url: str,
    timeout_ms: int,
    wait_until: str,
    sleep_ms: int,
    headers: dict[str, str],
    device: str | None,
) -> tuple[str, str, str]:
    browser = None
    context = None
    page = None

    try:
        browser = await launch_async(
            headless=True,
            stealth_args=True,
            humanize=True,
        )

        context_kwargs: dict[str, object] = {
            'ignore_https_errors': True,
        }
        context_kwargs.update(get_device_context(device))
        if headers:
            context_kwargs['extra_http_headers'] = headers

        context = await browser.new_context(**context_kwargs)
        page = await context.new_page()
        page.set_default_timeout(timeout_ms)
        await page.goto(url, wait_until=wait_until, timeout=timeout_ms)
        if sleep_ms > 0:
            await page.wait_for_timeout(sleep_ms)
        rendered_html = await page.content()
        final_url = page.url
        page_title = await page.title()
        return final_url, rendered_html, page_title
    finally:
        if page is not None:
            await page.close()
        if context is not None:
            await context.close()
        if browser is not None:
            await browser.close()


async def run_browser_healthcheck() -> None:
    browser = None
    context = None
    page = None

    try:
        browser = await launch_async(
            headless=True,
            stealth_args=True,
            humanize=True,
        )
        context = await browser.new_context(ignore_https_errors=True)
        page = await context.new_page()
        await page.goto('about:blank', wait_until='load', timeout=5000)
    finally:
        if page is not None:
            await page.close()
        if context is not None:
            await context.close()
        if browser is not None:
            await browser.close()


@app.get('/')
def root():
    return jsonify({
        'service': 'pricebuddy-scraper',
        'status': 'ok',
        'routes': ['/health', '/api/article'],
    })


@app.get('/health')
def health():
    try:
        asyncio.run(run_browser_healthcheck())
    except Exception as exc:  # pragma: no cover - exercised in container smoke tests
        logger.exception('PriceBuddy scraper healthcheck failed')
        return jsonify({
            'service': 'pricebuddy-scraper',
            'status': 'unhealthy',
            'detail': str(exc),
        }), 503

    return jsonify({
        'service': 'pricebuddy-scraper',
        'status': 'healthy',
        'browser': os.environ.get('CLOAKBROWSER_BINARY_PATH', '/opt/cloakbrowser/chrome'),
    })


@app.get('/api/article')
def get_article():
    url = request.args.get('url')
    if not url:
        return jsonify({
            'detail': [
                {
                    'type': 'missing_parameter',
                    'msg': 'Missing required parameter: url',
                }
            ]
        }), 400

    timeout_ms = parse_int(request.args.get('timeout'), DEFAULT_TIMEOUT_MS)
    sleep_ms = parse_int(request.args.get('sleep'), DEFAULT_SLEEP_MS)
    wait_until = normalize_wait_until(request.args.get('wait-until'))
    full_content = parse_bool(request.args.get('full-content'), default=False)
    headers = parse_extra_headers(request.args.get('extra-http-headers'))
    device = request.args.get('device')
    query = {key: request.args.getlist(key) for key in request.args.keys()}

    try:
        final_url, rendered_html, page_title = asyncio.run(
            render_page(
                url=url,
                timeout_ms=timeout_ms,
                wait_until=wait_until,
                sleep_ms=sleep_ms,
                headers=headers,
                device=device,
            )
        )
        payload = build_article_payload(
            final_url=final_url,
            rendered_html=rendered_html,
            page_title=page_title,
            include_full_content=full_content,
            query=query,
        )
        return jsonify(payload), 200
    except Exception as exc:  # pragma: no cover - exercised in container smoke tests
        logger.exception('Failed to fetch URL %s', url)
        return jsonify({
            'detail': [
                {
                    'type': 'fetch_error',
                    'msg': f'Failed to fetch URL: {exc}',
                }
            ]
        }), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', '3000')))
