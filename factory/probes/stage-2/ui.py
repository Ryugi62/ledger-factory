"""Headless-browser helpers (Playwright, async API). Probes that need a browser report SKIP when Playwright
or its Chromium is not installed:  pip install playwright && playwright install chromium"""
import asyncio
import json
import os
import re
import time
from urllib.parse import urlsplit

from kit import *

try:
    from playwright.async_api import async_playwright
    HAVE_PW = True
except Exception:  # noqa
    HAVE_PW = False

SHOTS = os.environ.get("PF_SHOTS", "/tmp/pocketful-stage2-shots")
WAIT = 8.0


def sel(tid):
    return '[data-testid="%s"]' % tid


def selp(prefix):
    return '[data-testid^="%s"]' % prefix


class Page:
    """A Playwright page plus a log of the requests/responses it made."""

    def __init__(self, page, base):
        self.p, self.base = page, base
        self.reqs, self.resps = [], []
        page.on("request", lambda r: self.reqs.append({"method": r.method, "path": urlsplit(r.url).path,
                                                       "url": r.url, "headers": dict(r.headers), "body": r.post_data}))

        async def on_resp(resp):
            try:
                body = await resp.text()
            except Exception:
                body = None
            self.resps.append({"method": resp.request.method, "path": urlsplit(resp.url).path, "status": resp.status, "body": body})
        page.on("response", lambda resp: asyncio.ensure_future(on_resp(resp)))

    # --- navigation
    async def goto(self, path):
        r = await self.p.goto(self.base + path, wait_until="load")
        await asyncio.sleep(0.15)
        return r

    # --- reading
    async def count(self, tid):
        return await self.p.locator(sel(tid)).count()

    async def present(self, tid):
        return (await self.count(tid)) > 0

    async def shown(self, tid):
        loc = self.p.locator(sel(tid))
        return (await loc.count()) > 0 and await loc.first.is_visible()

    async def text(self, tid):
        loc = self.p.locator(sel(tid))
        assert await loc.count() > 0, "no element with data-testid=%s" % tid
        return (await loc.first.text_content()) or ""

    async def attr(self, tid, name):
        loc = self.p.locator(sel(tid))
        assert await loc.count() > 0, "no element with data-testid=%s" % tid
        return await loc.first.get_attribute(name)

    async def value(self, tid):
        return await self.p.locator(sel(tid)).first.input_value()

    async def ids_with_prefix(self, prefix):
        """data-testid values starting with prefix, in DOM order."""
        return await self.p.evaluate(
            "(pre) => [...document.querySelectorAll('[data-testid^=\"'+pre+'\"]')].map(e => e.getAttribute('data-testid'))", prefix)

    # --- acting
    async def fill(self, tid, value):
        loc = self.p.locator(sel(tid)).first
        await loc.fill(value)

    async def click(self, tid, force=False):
        await self.p.locator(sel(tid)).first.click(force=force)

    async def select(self, tid, value):
        await self.p.locator(sel(tid)).first.select_option(value)

    # --- waiting
    async def wait(self, cond, what, timeout=WAIT):
        t0 = time.time()
        last = None
        while time.time() - t0 < timeout:
            try:
                last = await cond()
                if last:
                    return last
            except AssertionError as e:
                last = str(e)
            await asyncio.sleep(0.1)
        raise AssertionError("timed out waiting for %s (last: %r)" % (what, last))

    async def wait_text(self, tid, expected, timeout=WAIT):
        async def c():
            return (await self.present(tid)) and (await self.text(tid)).strip() == expected
        try:
            await self.wait(c, "%s text == %r" % (tid, expected), timeout)
        except AssertionError:
            got = (await self.text(tid)) if await self.present(tid) else "<absent>"
            raise AssertionError("data-testid=%s text is %r, expected %r" % (tid, got, expected))

    async def wait_present(self, tid, timeout=WAIT):
        await self.wait(lambda: self.shown(tid), "%s to be shown" % tid, timeout)

    async def wait_absent(self, tid, timeout=WAIT):
        async def c():
            return not await self.shown(tid)
        await self.wait(c, "%s to be absent/hidden" % tid, timeout)

    async def wait_attr(self, tid, name, expected, timeout=WAIT):
        async def c():
            return (await self.present(tid)) and (await self.attr(tid, name)) == expected
        try:
            await self.wait(c, "%s[%s]==%r" % (tid, name, expected), timeout)
        except AssertionError:
            got = (await self.attr(tid, name)) if await self.present(tid) else "<absent>"
            raise AssertionError("data-testid=%s %s is %r, expected %r" % (tid, name, got, expected))

    def posts(self, path):
        return [r for r in self.reqs if r["method"] == "POST" and r["path"] == path]

    async def shot(self, name):
        try:
            os.makedirs(SHOTS, exist_ok=True)
            await self.p.screenshot(path=os.path.join(SHOTS, name + ".png"), full_page=True)
        except Exception:
            pass


class Browser:
    async def __aenter__(self):
        self.pw = await async_playwright().start()
        self.browser = await self.pw.chromium.launch()
        return self

    async def __aexit__(self, *a):
        await self.browser.close()
        await self.pw.stop()

    async def page(self, width=1280, height=900, base=None):
        ctx = await self.browser.new_context(viewport={"width": width, "height": height}, locale="en-US")
        ctx.set_default_timeout(10000)
        return Page(await ctx.new_page(), base or lib.BASE)


async def ui_login(pg, email, password=PASSWORD, path=None):
    await pg.goto("/login")
    await pg.fill("login-email", email)
    await pg.fill("login-password", password)
    await pg.click("login-submit")
    await pg.wait_present("current-user")
    if path:
        await pg.goto(path)
        await pg.wait_present("current-user")


def ui_probe(*ids):
    """Register an async probe `async def f(b: Browser)`; it SKIPs when Playwright is unavailable."""
    def deco(fn):
        def run():
            if not HAVE_PW:
                return "skip"

            async def main():
                try:
                    async with Browser() as b:
                        await fn(b)
                except AssertionError:
                    raise
                except Exception as e:  # playwright launch problems etc.
                    if "Executable doesn't exist" in str(e) or "playwright install" in str(e):
                        return "skip"
                    raise
            return asyncio.run(main())
        run.__name__ = fn.__name__
        run.__module__ = fn.__module__
        return probe(*ids)(run)
    return deco


def fmt(minor, mu=2, cur="EUR"):
    if mu == 0:
        return "%d %s" % (minor, cur)
    return "%d.%0*d %s" % (minor // 10 ** mu, mu, minor % 10 ** mu, cur)
