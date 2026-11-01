"""The optional one-shot browser runner cannot escape local synthetic work."""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

import pytest

from boca_socios.browser.contracts import SimulationOutcome
from boca_socios.browser.on_demand import (
    OnDemandSyntheticBrowser,
    WorkerBoundaryError,
    validate_worker_boundary,
)
from boca_socios.browser.synthetic import STEPS, SYNTHETIC_HTML, SyntheticFlowError
from boca_socios.domain.policy import TicketIntent
from boca_socios.integration.beta import BetaCoordinator, CommandState
from boca_socios.notify.sqlite_outbox import SqliteNotificationOutbox
from boca_socios.storage.database import Database


class LocalLocator:
    def __init__(self, page: LocalPage, action: str | None = None) -> None:
        self.page = page
        self.action = action

    async def inner_text(self, *, timeout: float) -> str:
        assert timeout == 5_000
        return self.page.stage

    async def click(self, *, timeout: float) -> None:
        assert timeout == 5_000
        step = next((item for item in STEPS if item.before == self.page.stage), None)
        if step is None or step.action != self.action:
            raise SyntheticFlowError("unexpected synthetic action")
        self.page.stage = step.after
        self.page.actions.append(step.action)


class LocalPage:
    def __init__(self, *, stop_after_content: asyncio.Event | None = None) -> None:
        self.stage = "new"
        self.actions: list[str] = []
        self.opened = asyncio.Event()
        self.closed = False
        self.stop_after_content = stop_after_content

    async def set_content(self, html: str, *, wait_until: str, timeout: float) -> None:
        assert html == SYNTHETIC_HTML
        assert wait_until == "load" and timeout == 5_000
        self.stage = "prequeue"
        self.opened.set()
        if self.stop_after_content is not None:
            await self.stop_after_content.wait()

    def locator(self, selector: str) -> LocalLocator:
        assert selector == "#stage"
        return LocalLocator(self)

    def get_by_role(self, role: str, *, name: str) -> LocalLocator:
        assert role == "button"
        return LocalLocator(self, name)


def test_optional_worker_is_inert_until_called_and_closes_page() -> None:
    page = LocalPage()
    opened = 0

    @asynccontextmanager
    async def pages() -> AsyncIterator[LocalPage]:
        nonlocal opened
        opened += 1
        try:
            yield page
        finally:
            page.closed = True

    browser = OnDemandSyntheticBrowser(pages, boundary_check=lambda: None)
    assert opened == 0
    assert (
        asyncio.run(browser.simulate_general_reservation())
        is SimulationOutcome.RESERVED_IN_SIMULATOR
    )
    assert opened == 1 and page.closed
    assert page.actions == [step.action for step in STEPS]


def test_concurrent_command_is_refused_without_starting_second_page() -> None:
    async def exercise() -> None:
        release = asyncio.Event()
        page = LocalPage(stop_after_content=release)
        opened = 0

        @asynccontextmanager
        async def pages() -> AsyncIterator[LocalPage]:
            nonlocal opened
            opened += 1
            try:
                yield page
            finally:
                page.closed = True

        browser = OnDemandSyntheticBrowser(pages, boundary_check=lambda: None)
        active = asyncio.create_task(browser.simulate_general_reservation())
        await page.opened.wait()
        with pytest.raises(WorkerBoundaryError, match="busy"):
            await browser.simulate_general_reservation()
        assert opened == 1
        release.set()
        assert await active is SimulationOutcome.RESERVED_IN_SIMULATOR
        assert page.closed

    asyncio.run(exercise())


def test_cancellation_and_timeout_close_the_page_and_never_claim_success() -> None:
    async def exercise() -> None:
        release = asyncio.Event()
        page = LocalPage(stop_after_content=release)

        @asynccontextmanager
        async def pages() -> AsyncIterator[LocalPage]:
            try:
                yield page
            finally:
                page.closed = True

        browser = OnDemandSyntheticBrowser(pages, boundary_check=lambda: None, timeout_seconds=0.04)
        with pytest.raises(TimeoutError):
            await browser.simulate_general_reservation()
        assert page.closed and not page.actions
        await browser.close()
        with pytest.raises(WorkerBoundaryError, match="closed"):
            await browser.simulate_general_reservation()

    asyncio.run(exercise())


def test_boundary_check_fails_before_page_creation() -> None:
    opened = 0

    @asynccontextmanager
    async def pages() -> AsyncIterator[LocalPage]:
        nonlocal opened
        opened += 1
        yield LocalPage()

    def reject() -> None:
        raise WorkerBoundaryError("worker_identity")

    browser = OnDemandSyntheticBrowser(pages, boundary_check=reject)
    with pytest.raises(WorkerBoundaryError, match="worker_identity"):
        asyncio.run(browser.simulate_general_reservation())
    assert opened == 0


def test_coordinator_runs_one_lazy_dom_and_restart_reuses_durable_result(tmp_path: Path) -> None:
    async def exercise() -> None:
        pages_opened: list[LocalPage] = []

        @asynccontextmanager
        async def pages() -> AsyncIterator[LocalPage]:
            page = LocalPage()
            pages_opened.append(page)
            try:
                yield page
            finally:
                page.closed = True

        db = Database(tmp_path / "synthetic.sqlite")
        outbox = SqliteNotificationOutbox(db)
        browser = OnDemandSyntheticBrowser(pages, boundary_check=lambda: None)
        coordinator = BetaCoordinator(database=db, outbox=outbox, browser=browser)
        coordinator.prepare_storage()
        db.create_member("fixture-member", "member@example.invalid", "synthetic")
        db.create_event("fixture-event", "Fixture event")
        intent = TicketIntent("fixture-member", "fixture-event")
        command_id = str(uuid4())
        assert pages_opened == []

        await coordinator.begin(command_id, intent)
        await coordinator.wait_idle()
        snapshot = coordinator.status(command_id, member_id=intent.member_id)
        assert snapshot is not None and snapshot.state is CommandState.COMPLETED
        assert snapshot.external_confirmation == "not_observed"
        assert len(pages_opened) == 1 and pages_opened[0].closed
        with sqlite3.connect(db.path) as conn:
            assert conn.execute("SELECT quantity, status FROM ticket_requests").fetchall() == [
                (1, "planned")
            ]
            assert conn.execute("SELECT COUNT(*) FROM notification_outbox").fetchone() == (1,)

        await coordinator.close()
        restarted = BetaCoordinator(database=db, outbox=outbox, browser=browser)
        await restarted.recover()
        duplicate = await restarted.begin(str(uuid4()), intent)
        await restarted.wait_idle()
        assert duplicate.command_id == command_id
        assert duplicate.state is CommandState.COMPLETED
        assert len(pages_opened) == 1
        await restarted.close()
        await browser.close()

    asyncio.run(exercise())


def test_active_stop_cancels_page_and_cannot_rearm_one_ticket(tmp_path: Path) -> None:
    async def exercise() -> None:
        release = asyncio.Event()
        page = LocalPage(stop_after_content=release)
        opened = 0

        @asynccontextmanager
        async def pages() -> AsyncIterator[LocalPage]:
            nonlocal opened
            opened += 1
            try:
                yield page
            finally:
                page.closed = True

        db = Database(tmp_path / "stop.sqlite")
        outbox = SqliteNotificationOutbox(db)
        browser = OnDemandSyntheticBrowser(pages, boundary_check=lambda: None)
        coordinator = BetaCoordinator(database=db, outbox=outbox, browser=browser)
        coordinator.prepare_storage()
        db.create_member("fixture-member", "member@example.invalid", "synthetic")
        db.create_event("fixture-event", "Fixture event")
        intent = TicketIntent("fixture-member", "fixture-event")
        command_id = str(uuid4())
        await coordinator.begin(command_id, intent)
        await page.opened.wait()
        await coordinator.stop(command_id, member_id=intent.member_id)
        await coordinator.wait_idle()
        snapshot = coordinator.status(command_id, member_id=intent.member_id)
        assert snapshot is not None and snapshot.state is CommandState.STOPPED
        assert opened == 1 and page.closed and page.actions == []
        alias = await coordinator.begin(str(uuid4()), intent)
        await coordinator.wait_idle()
        assert alias.command_id == command_id and opened == 1
        await coordinator.close()
        await browser.close()

    asyncio.run(exercise())


def test_uncooperative_page_teardown_is_bounded_and_fences_late_success() -> None:
    async def exercise() -> None:
        release = asyncio.Event()
        page = LocalPage(stop_after_content=release)

        async def stubborn_content(html: str, *, wait_until: str, timeout: float) -> None:
            try:
                await LocalPage.set_content(page, html, wait_until=wait_until, timeout=timeout)
            except asyncio.CancelledError:
                await release.wait()

        page.set_content = stubborn_content  # type: ignore[method-assign]

        @asynccontextmanager
        async def pages() -> AsyncIterator[LocalPage]:
            try:
                yield page
            finally:
                page.closed = True

        browser = OnDemandSyntheticBrowser(
            pages,
            boundary_check=lambda: None,
            teardown_seconds=0.02,
        )
        active = asyncio.create_task(browser.simulate_general_reservation())
        await page.opened.wait()
        with pytest.raises(WorkerBoundaryError, match="teardown_unverified"):
            await browser.close()
        assert not active.done()
        release.set()
        with pytest.raises(WorkerBoundaryError, match="worker_closed"):
            await active
        assert page.closed

    asyncio.run(exercise())


def test_close_during_stubborn_context_exit_never_returns_late_success() -> None:
    async def exercise() -> None:
        teardown_started = asyncio.Event()
        release = asyncio.Event()

        @asynccontextmanager
        async def pages() -> AsyncIterator[LocalPage]:
            try:
                yield LocalPage()
            finally:
                teardown_started.set()
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    # Simulate a browser library swallowing cancellation while
                    # it completes its own cleanup after the host gave up.
                    await release.wait()

        browser = OnDemandSyntheticBrowser(
            pages, boundary_check=lambda: None, teardown_seconds=0.02
        )
        active = asyncio.create_task(browser.simulate_general_reservation())
        await teardown_started.wait()
        with pytest.raises(WorkerBoundaryError, match="teardown_unverified"):
            await browser.close()
        assert not active.done()
        release.set()
        with pytest.raises(WorkerBoundaryError, match="worker_closed"):
            await active

    asyncio.run(exercise())


def test_timeout_swallowed_during_context_exit_never_returns_late_success() -> None:
    async def exercise() -> None:
        teardown_started = asyncio.Event()
        cancellation_swallowed = asyncio.Event()
        release = asyncio.Event()

        @asynccontextmanager
        async def pages() -> AsyncIterator[LocalPage]:
            try:
                yield LocalPage()
            finally:
                teardown_started.set()
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    cancellation_swallowed.set()
                    await release.wait()

        browser = OnDemandSyntheticBrowser(pages, boundary_check=lambda: None, timeout_seconds=0.02)
        active = asyncio.create_task(browser.simulate_general_reservation())
        await teardown_started.wait()
        await asyncio.wait_for(cancellation_swallowed.wait(), timeout=1)
        release.set()
        with pytest.raises(TimeoutError, match="deadline expired"):
            await active

    asyncio.run(exercise())


def test_external_stop_swallowed_during_teardown_does_not_claim_success() -> None:
    async def exercise() -> None:
        teardown_started = asyncio.Event()
        cancellation_swallowed = asyncio.Event()
        release = asyncio.Event()

        @asynccontextmanager
        async def pages() -> AsyncIterator[LocalPage]:
            try:
                yield LocalPage()
            finally:
                teardown_started.set()
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    cancellation_swallowed.set()
                    await release.wait()

        browser = OnDemandSyntheticBrowser(pages, boundary_check=lambda: None)
        active = asyncio.create_task(browser.simulate_general_reservation())
        await teardown_started.wait()
        active.cancel()
        await asyncio.wait_for(cancellation_swallowed.wait(), timeout=1)
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await active

    asyncio.run(exercise())


def test_invalid_budget_refuses_unbounded_one_shot(tmp_path: Path) -> None:
    (tmp_path / "memory.max").write_text("805306368\n")
    (tmp_path / "pids.max").write_text("128\n")
    (tmp_path / "cpu.max").write_text("100000 100000\n")
    validate_worker_boundary(root=tmp_path, uid=10002, gid=10002)
    for name, bad in (
        ("memory.max", "max\n"),
        ("pids.max", "129\n"),
        ("cpu.max", "200000 100000\n"),
    ):
        original = (tmp_path / name).read_text()
        (tmp_path / name).write_text(bad)
        with pytest.raises(WorkerBoundaryError):
            validate_worker_boundary(root=tmp_path, uid=10002, gid=10002)
        (tmp_path / name).write_text(original)
    with pytest.raises(WorkerBoundaryError, match="worker_identity"):
        validate_worker_boundary(root=tmp_path, uid=10001, gid=10001)


@pytest.mark.parametrize("timeout", [0, -1, 31, True, float("inf")])
def test_unbounded_deadline_is_rejected(timeout: float) -> None:
    with pytest.raises(ValueError, match="timeout"):
        OnDemandSyntheticBrowser(lambda: None, boundary_check=lambda: None, timeout_seconds=timeout)  # type: ignore[arg-type]


@pytest.mark.parametrize("teardown", [0, -1, 6, True, float("nan")])
def test_unbounded_teardown_is_rejected(teardown: float) -> None:
    with pytest.raises(ValueError, match="teardown"):
        OnDemandSyntheticBrowser(lambda: None, teardown_seconds=teardown)  # type: ignore[arg-type]
