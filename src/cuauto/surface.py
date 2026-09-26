from __future__ import annotations

import hashlib
import os
import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, cast

from .models import ActionType, Condition, Locator, Observation, Step
from .policy import PolicyEngine
from .redaction import redact


class SurfaceError(RuntimeError):
    category = "surface_error"


class MissingControl(SurfaceError):
    category = "missing_control"


class AmbiguousControl(SurfaceError):
    category = "ambiguous_control"


class SurfaceTimeout(SurfaceError):
    category = "transient_timeout"


class ApplicationError(SurfaceError):
    category = "application_error"


class SurfaceAdapter(ABC):
    @property
    @abstractmethod
    def session_id(self) -> str: ...

    @abstractmethod
    def observe(self) -> Observation: ...

    @abstractmethod
    def act(self, step: Step, value: str | None = None) -> str | None: ...

    @abstractmethod
    def check(self, condition: Condition) -> bool: ...

    @abstractmethod
    def wait(self, condition: Condition, timeout_ms: int) -> None: ...

    @abstractmethod
    def capture(self, path: Path, *, screenshot: bool) -> tuple[str, ...]: ...

    @abstractmethod
    def expose_live_session(self) -> str: ...

    @abstractmethod
    def close(self) -> None: ...


class PlaywrightSurface(SurfaceAdapter):
    """Browser surface; the Page object remains alive across human handoff."""

    def __init__(self, policy: PolicyEngine, *, headless: bool = True):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError("install Playwright and Chromium first") from exc
        import secrets

        self._policy = policy
        self._pw = sync_playwright().start()
        local_lib = (
            Path(__file__).resolve().parents[2]
            / "vendor"
            / "runtime-libs"
            / "usr"
            / "lib"
            / "x86_64-linux-gnu"
        )
        browser_env: dict[str, str | float | bool] = dict(os.environ)
        if local_lib.is_dir():
            existing = str(browser_env.get("LD_LIBRARY_PATH", ""))
            browser_env["LD_LIBRARY_PATH"] = f"{local_lib}:{existing}".rstrip(":")
        self._browser = self._pw.chromium.launch(headless=headless, env=browser_env)
        self._context = self._browser.new_context()
        self._page = self._context.new_page()
        self._session_id = secrets.token_urlsafe(24)
        self._page.on("framenavigated", self._validate_frame)

    @property
    def session_id(self) -> str:
        return self._session_id

    def _validate_frame(self, frame: Any) -> None:
        if frame == self._page.main_frame and frame.url != "about:blank":
            self._policy.check_url(frame.url)

    def _locator(self, candidates: tuple[Locator, ...]) -> Any:
        for candidate in candidates:
            if candidate.strategy == "role":
                found = self._page.get_by_role(
                    cast(Any, candidate.role), name=candidate.value, exact=True
                )
            elif candidate.strategy == "label":
                found = self._page.get_by_label(candidate.value, exact=True)
            elif candidate.strategy == "text":
                base = self._page.locator(candidate.scope) if candidate.scope else self._page
                found = base.get_by_text(candidate.value, exact=True)
            elif candidate.strategy == "attribute":
                found = self._page.locator(f'[{candidate.attribute}="{candidate.value}"]')
            elif candidate.strategy == "relative":
                found = self._page.locator(candidate.value)
            elif candidate.strategy == "row_value":
                base = self._page.locator(candidate.scope) if candidate.scope else self._page
                found = (
                    base.get_by_role("row")
                    .filter(has_text=candidate.value)
                    .get_by_role("cell")
                    .last
                )
            else:
                continue
            count = found.count()
            if count == 1:
                return found
            if count > 1:
                raise AmbiguousControl(f"locator {candidate.strategy} matched {count} controls")
        raise MissingControl("no locator candidate matched exactly one control")

    def observe(self) -> Observation:
        text = self._page.locator("body").inner_text(timeout=3_000)[:8_000]
        controls = self._page.locator("input,button,a,select,textarea").evaluate_all(
            """els => els.slice(0,100).map(e => ({tag:e.tagName.toLowerCase(),
            role:e.getAttribute('role')||'', name:e.getAttribute('aria-label')||
            e.innerText||e.labels?.[0]?.innerText||e.getAttribute('name')||'',
            type:e.getAttribute('type')||''}))"""
        )
        clean = redact(
            {"url": self._page.url, "title": self._page.title(), "text": text, "controls": controls}
        )
        fingerprint = hashlib.sha256(str(clean).encode()).hexdigest()
        return Observation(**clean, fingerprint=fingerprint)

    def act(self, step: Step, value: str | None = None) -> str | None:
        try:
            if step.action == ActionType.NAVIGATE:
                assert step.destination
                destination = self._policy.check_url(step.destination)
                response = self._page.goto(
                    destination, wait_until="domcontentloaded", timeout=step.timeout_ms
                )
                if response and response.status >= 500:
                    raise ApplicationError(f"application returned HTTP {response.status}")
            elif step.action == ActionType.FILL:
                self._locator(step.locators).fill(value or "", timeout=step.timeout_ms)
            elif step.action == ActionType.CLICK:
                self._locator(step.locators).click(timeout=step.timeout_ms)
            elif step.action == ActionType.EXTRACT:
                text = cast(str, self._locator(step.locators).inner_text(timeout=step.timeout_ms))
                return text.strip()
            elif step.action == ActionType.DISMISS_DIALOG:
                self._page.once("dialog", lambda dialog: dialog.dismiss())
            elif step.action == ActionType.WAIT and step.wait:
                self.wait(step.wait, step.timeout_ms)
            return None
        except Exception as exc:
            if exc.__class__.__name__ == "TimeoutError":
                raise SurfaceTimeout(str(exc)) from exc
            raise

    def check(self, condition: Condition) -> bool:
        if condition.kind == "url_matches":
            return re.search(condition.value, self._page.url) is not None
        if condition.kind == "text_present":
            return condition.value in self._page.locator("body").inner_text(timeout=2_000)
        if condition.kind == "visible":
            try:
                return bool(self._locator(condition.locators).is_visible())
            except MissingControl:
                return False
        if condition.kind == "dialog_absent":
            return True
        return False

    def wait(self, condition: Condition, timeout_ms: int) -> None:
        if condition.kind == "text_present":
            self._page.get_by_text(condition.value, exact=False).first.wait_for(
                state="visible", timeout=timeout_ms
            )
        elif condition.kind == "visible":
            self._locator(condition.locators).wait_for(state="visible", timeout=timeout_ms)
        elif condition.kind == "url_matches":
            self._page.wait_for_url(re.compile(condition.value), timeout=timeout_ms)
        elif not self.check(condition):
            raise SurfaceTimeout("condition not met")

    def capture(self, path: Path, *, screenshot: bool) -> tuple[str, ...]:
        path.mkdir(parents=True, exist_ok=True)
        stem = re.sub(r"[^a-zA-Z0-9_-]", "_", self.session_id)[:64]
        dom = path / f"{stem}-dom.txt"
        dom.write_text(str(redact(self._page.locator("body").inner_text())), encoding="utf-8")
        refs = [str(dom)]
        if screenshot:
            shot = path / f"{stem}-screenshot.png"
            self._page.screenshot(path=shot, full_page=True)
            refs.append(str(shot))
        return tuple(refs)

    def expose_live_session(self) -> str:
        return "The existing headful browser window is now under human control."

    def close(self) -> None:
        self._context.close()
        self._browser.close()
        self._pw.stop()
