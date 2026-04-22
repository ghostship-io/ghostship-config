import asyncio
import gc
import json
import os
import time
from urllib.parse import urlparse

from cloakbrowser import launch_async
from loguru import logger

from changedetectionio.browser_steps.browser_steps import steppable_browser_interface
from changedetectionio.content_fetchers import (
    FAVICON_FETCHER_JS,
    INSTOCK_DATA_JS,
    SCREENSHOT_MAX_HEIGHT_DEFAULT,
    XPATH_ELEMENT_JS,
    visualselector_xpath_selectors,
)
from changedetectionio.content_fetchers.base import Fetcher, manage_user_agent
from changedetectionio.content_fetchers.exceptions import (
    BrowserStepsStepException,
    EmptyReply,
    Non200ErrorCodeReceived,
    PageUnloadable,
    ScreenshotUnavailable,
)
from changedetectionio.content_fetchers.playwright import capture_full_page_async


class fetcher(Fetcher):
    fetcher_description = 'Embedded CloakBrowser/Javascript'

    playwright_proxy_settings_mappings = ['bypass', 'server', 'username', 'password']
    proxy = None

    supports_browser_steps = True
    supports_screenshots = True
    supports_xpath_element_data = True

    @classmethod
    def get_status_icon_data(cls):
        return {
            'filename': 'google-chrome-icon.png',
            'alt': 'Using embedded CloakBrowser',
            'title': 'Using embedded CloakBrowser',
        }

    def __init__(self, proxy_override=None, custom_browser_connection_url=None, **kwargs):
        super().__init__(**kwargs)
        self.browser_type = 'chromium'
        self.browser_connection_is_custom = bool(custom_browser_connection_url)
        self.browser_connection_url = custom_browser_connection_url

        proxy_args = {}
        for key in self.playwright_proxy_settings_mappings:
            value = os.getenv('playwright_proxy_' + key, False)
            if value:
                proxy_args[key] = value.strip('"')

        if proxy_args:
            self.proxy = proxy_args

        if proxy_override:
            self.proxy = proxy_override if isinstance(proxy_override, dict) else {'server': proxy_override}

        if self.proxy and self.proxy.get('server'):
            parsed = urlparse(self.proxy.get('server'))
            if parsed.username:
                self.proxy['username'] = parsed.username
                self.proxy['password'] = parsed.password

    @classmethod
    async def get_browsersteps_browser(cls, proxy=None, keepalive_ms=None):
        browser = await launch_async(
            headless=True,
            proxy=proxy,
            stealth_args=True,
            humanize=True,
        )
        return browser, None

    async def screenshot_step(self, step_n=''):
        super().screenshot_step(step_n=step_n)
        watch_uuid = getattr(self, 'watch_uuid', None)
        screenshot = await capture_full_page_async(
            page=self.page,
            screenshot_format=self.screenshot_format,
            watch_uuid=watch_uuid,
            lock_viewport_elements=self.lock_viewport_elements,
        )
        await self.page.request_gc()

        if self.browser_steps_screenshot_path is not None:
            destination = os.path.join(self.browser_steps_screenshot_path, f'step_{step_n}.jpeg')
            logger.debug(f'Saving step screenshot to {destination}')
            with open(destination, 'wb') as handle:
                handle.write(screenshot)
            del screenshot
            gc.collect()

    async def save_step_html(self, step_n):
        super().save_step_html(step_n=step_n)
        content = await self.page.content()
        await self.page.request_gc()

        destination = os.path.join(self.browser_steps_screenshot_path, f'step_{step_n}.html')
        logger.debug(f'Saving step HTML to {destination}')
        with open(destination, 'w', encoding='utf-8') as handle:
            handle.write(content)
        del content
        gc.collect()

    async def run(
        self,
        fetch_favicon=True,
        current_include_filters=None,
        empty_pages_are_a_change=False,
        ignore_status_codes=False,
        is_binary=False,
        request_body=None,
        request_headers=None,
        request_method=None,
        screenshot_format=None,
        timeout=None,
        url=None,
        watch_uuid=None,
    ):
        import playwright._impl._errors

        self.delete_browser_steps_screenshots()
        self.watch_uuid = watch_uuid
        browser = None
        context = None
        response = None

        try:
            browser = await launch_async(
                headless=True,
                proxy=self.proxy,
                stealth_args=True,
                humanize=True,
            )

            context = await browser.new_context(
                accept_downloads=False,
                bypass_csp=True,
                extra_http_headers=request_headers,
                ignore_https_errors=True,
                service_workers=os.getenv('PLAYWRIGHT_SERVICE_WORKERS', 'allow'),
                user_agent=manage_user_agent(headers=request_headers or {}),
            )

            self.page = await context.new_page()
            self.page.on(
                'console',
                lambda msg: logger.debug(
                    f'Playwright console: Watch URL: {url} {msg.type}: {msg.text} {msg.args}'
                ),
            )

            browsersteps_interface = steppable_browser_interface(start_url=url)
            browsersteps_interface.page = self.page
            response = await browsersteps_interface.action_goto_url(value=url)

            if response is None:
                raise EmptyReply(url=url, status_code=None)

            try:
                self.headers = await response.all_headers()
            except TypeError:
                self.headers = response.all_headers()

            try:
                if self.webdriver_js_execute_code:
                    await browsersteps_interface.action_execute_js(
                        value=self.webdriver_js_execute_code,
                        selector=None,
                    )
            except playwright._impl._errors.TimeoutError:
                pass
            except Exception as exc:
                logger.debug(f'Content Fetcher > Other exception when executing custom JS code {exc}')
                raise PageUnloadable(url=url, status_code=None, message=str(exc))

            extra_wait = int(os.getenv('WEBDRIVER_DELAY_BEFORE_CONTENT_READY', 5)) + self.render_extract_delay
            await self.page.wait_for_timeout(extra_wait * 1000)

            try:
                self.status_code = response.status
            except Exception as exc:
                logger.critical('Response from the browser/CloakBrowser did not have a status_code! Response follows.')
                logger.critical(response)
                raise PageUnloadable(url=url, status_code=None, message=str(exc))

            if fetch_favicon:
                try:
                    self.favicon_blob = await self.page.evaluate(FAVICON_FETCHER_JS)
                    await self.page.request_gc()
                except Exception as exc:
                    logger.error(f'Error fetching FavIcon info {exc}, continuing.')

            if self.status_code != 200 and not ignore_status_codes:
                screenshot = await capture_full_page_async(
                    self.page,
                    screenshot_format=self.screenshot_format,
                    watch_uuid=watch_uuid,
                    lock_viewport_elements=self.lock_viewport_elements,
                )
                raise Non200ErrorCodeReceived(url=url, status_code=self.status_code, screenshot=screenshot)

            content = await self.page.content()
            if not empty_pages_are_a_change and len(content.strip()) == 0:
                logger.debug('Content Fetcher > Content was empty, empty_pages_are_a_change = False')
                raise EmptyReply(url=url, status_code=response.status)

            try:
                if self.browser_steps:
                    try:
                        await self.iterate_browser_steps(start_url=url)
                    except BrowserStepsStepException:
                        raise
                    await self.page.wait_for_timeout(extra_wait * 1000)

                now = time.time()
                if current_include_filters is not None:
                    await self.page.evaluate(f"var include_filters={json.dumps(current_include_filters)}")
                else:
                    await self.page.evaluate("var include_filters=''")
                await self.page.request_gc()

                max_total_height = int(os.getenv('SCREENSHOT_MAX_HEIGHT', SCREENSHOT_MAX_HEIGHT_DEFAULT))
                self.xpath_data = await self.page.evaluate(
                    XPATH_ELEMENT_JS,
                    {
                        'visualselector_xpath_selectors': visualselector_xpath_selectors,
                        'max_height': max_total_height,
                    },
                )
                await self.page.request_gc()

                self.instock_data = await self.page.evaluate(INSTOCK_DATA_JS)
                await self.page.request_gc()

                self.content = await self.page.content()
                await self.page.request_gc()
                logger.debug(f'Scrape xPath element data in browser done in {time.time() - now:.2f}s')

                self.screenshot = await capture_full_page_async(
                    page=self.page,
                    screenshot_format=self.screenshot_format,
                    watch_uuid=watch_uuid,
                    lock_viewport_elements=self.lock_viewport_elements,
                )
                await self.page.request_gc()
                gc.collect()

            except ScreenshotUnavailable:
                raise

        finally:
            try:
                if getattr(self, 'page', None):
                    await self.page.request_gc()
                    await asyncio.wait_for(self.page.close(), timeout=5.0)
                    logger.debug(f'Successfully closed page for {url}')
            except asyncio.TimeoutError:
                logger.warning(f'Timed out closing page for {url} (5s)')
            except Exception as exc:
                logger.warning(f'Error closing page for {url}: {exc}')
            finally:
                self.page = None

            try:
                if context:
                    await asyncio.wait_for(context.close(), timeout=5.0)
                    logger.debug(f'Successfully closed context for {url}')
            except asyncio.TimeoutError:
                logger.warning(f'Timed out closing context for {url} (5s)')
            except Exception as exc:
                logger.warning(f'Error closing context for {url}: {exc}')

            try:
                if browser:
                    await asyncio.wait_for(browser.close(), timeout=5.0)
                    logger.debug(f'Successfully closed embedded browser for {url}')
            except asyncio.TimeoutError:
                logger.warning(f'Timed out closing embedded browser for {url} (5s)')
            except Exception as exc:
                logger.warning(f'Error closing embedded browser for {url}: {exc}')

            gc.collect()
