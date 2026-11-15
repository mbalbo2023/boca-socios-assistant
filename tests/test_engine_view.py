"""Owner engine controls keep their form and private inspection boundaries."""

from __future__ import annotations

import copy
import json
import shutil
import subprocess
from collections.abc import Mapping
from html.parser import HTMLParser
from uuid import uuid4

import pytest

from boca_socios.panel.members import MemberView


class Page(HTMLParser):
    def __init__(self, body: bytes) -> None:
        super().__init__()
        self.elements: list[tuple[str, dict[str, str | None]]] = []
        self.forms: dict[str, list[tuple[str, dict[str, str | None]]]] = {}
        self.form: str | None = None
        self.text: dict[str, str] = {}
        self.open_elements: list[tuple[str, str | None]] = []
        self.feed(body.decode())

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        self.elements.append((tag, attributes))
        if tag not in {"input", "meta", "link", "br", "hr"}:
            self.open_elements.append((tag, attributes.get("id")))
        if tag == "form":
            assert attributes["method"] == "post"
            self.form = str(attributes["action"])
            assert self.form not in self.forms
            self.forms[self.form] = []
        elif self.form is not None:
            self.forms[self.form].append((tag, attributes))

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.open_elements) - 1, -1, -1):
            if self.open_elements[index][0] == tag:
                del self.open_elements[index:]
                break
        if tag == "form":
            self.form = None

    def handle_data(self, data: str) -> None:
        for _, identifier in self.open_elements:
            if identifier is not None:
                self.text[identifier] = self.text.get(identifier, "") + data

    def fields(self, action: str) -> dict[str, dict[str, str | None]]:
        return {
            str(attrs["name"]): attrs
            for tag, attrs in self.forms[action]
            if tag in {"input", "select"}
        }

    def button(self, action: str) -> dict[str, str | None]:
        return next(attrs for tag, attrs in self.forms[action] if tag == "button")


def render(
    *,
    snapshot: Mapping[str, object] | None = None,
    members: tuple[MemberView, ...] | None = None,
    site_url_ready: bool = True,
    csrf: str = "csrf-fixture",
    legacy_operation: str | None = None,
) -> tuple[Page, bytes, dict[str, str]]:
    from boca_socios.panel import engine_view

    operations = {
        f"{engine}:{action}": str(uuid4())
        for engine in ("queues_tokens", "browsers_members")
        for action in ("start", "stop")
    }
    if legacy_operation is not None:
        operations["legacy:stop"] = legacy_operation
    body = engine_view.page(
        snapshot or {"version": 1, "engines": []},
        csrf,
        operations,
        (MemberView(str(uuid4()), "Socio de prueba", "s•••@example.invalid", True),)
        if members is None
        else members,
        site_url_ready=site_url_ready,
    )
    return Page(body), body, operations


def test_start_forms_scope_member_and_counts_to_the_chosen_engine() -> None:
    page, _, operations = render()

    assert set(page.forms) == {
        "/control/motores/queues_tokens/iniciar",
        "/control/motores/queues_tokens/detener",
        "/control/motores/browsers_members/iniciar",
        "/control/motores/browsers_members/detener",
    }
    labels = {attrs.get("for") for tag, attrs in page.elements if tag == "label"}
    ids = [attrs["id"] for _, attrs in page.elements if "id" in attrs]
    assert len(ids) == len(set(ids))
    for engine in ("queues_tokens", "browsers_members"):
        fields = page.fields(f"/control/motores/{engine}/iniciar")
        expected = {"csrf", "operation_id", "chromium", "firefox", "webkit"}
        if engine == "browsers_members":
            expected.add("member_id")
            assert "required" in fields["member_id"]
            assert fields["member_id"]["id"] in labels
        assert set(fields) == expected
        assert fields["csrf"]["value"] == "csrf-fixture"
        assert fields["operation_id"]["value"] == operations[f"{engine}:start"]
        for browser, count in (("chromium", "15"), ("firefox", "5"), ("webkit", "5")):
            assert fields[browser]["value"] == count
            assert fields[browser]["type"] == "number"
            assert fields[browser]["min"] == "0"
            assert fields[browser]["max"] == "50"
            assert "required" in fields[browser]
            assert fields[browser]["id"] in labels


def test_each_stop_form_carries_its_own_activation_fence() -> None:
    activations = {"queues_tokens": str(uuid4()), "browsers_members": str(uuid4())}
    page, _, operations = render(
        snapshot={
            "version": 1,
            "engines": [
                {"engine": engine, "state": "RUNNING", "activation_id": activation, "generation": n}
                for n, (engine, activation) in enumerate(activations.items(), 1)
            ],
        },
        site_url_ready=False,
    )

    for n, (engine, activation) in enumerate(activations.items(), 1):
        action = f"/control/motores/{engine}/detener"
        fields = page.fields(action)
        assert set(fields) == {"csrf", "operation_id", "activation_id", "generation"}
        assert fields["operation_id"]["value"] == operations[f"{engine}:stop"]
        assert fields["activation_id"]["value"] == activation
        assert fields["generation"]["value"] == str(n)
        assert "disabled" not in page.button(action)


def test_current_member_comes_from_activation_without_preselecting_next_start() -> None:
    members = (
        MemberView(str(uuid4()), "Primer socio", "p•••@example.invalid", True),
        MemberView(str(uuid4()), "Segundo socio", "s•••@example.invalid", True),
    )
    page, _, _ = render(
        members=members,
        snapshot={
            "version": 1,
            "engines": [
                {
                    "engine": "browsers_members",
                    "state": "RUNNING",
                    "member_id": members[1].member_id,
                }
            ],
        },
    )

    assert page.text["browsers_members-current-member"] == "Segundo socio · s•••@example.invalid"
    selected = [attrs for tag, attrs in page.elements if tag == "option" and "selected" in attrs]
    assert len(selected) == 1 and selected[0]["value"] == ""


@pytest.mark.parametrize(
    ("state", "can_start", "disabled"), [("UNCERTAIN", True, False), ("STOPPED", False, True)]
)
def test_start_obeys_explicit_read_only_restart_readiness(state, can_start, disabled) -> None:
    activation = str(uuid4())
    snapshot = {
        "version": 1,
        "engines": [
            {
                "engine": "queues_tokens",
                "state": state,
                "can_start": can_start,
                "activation_id": activation,
                "generation": 3,
            }
        ],
    }
    original = copy.deepcopy(snapshot)
    page, _, _ = render(snapshot=snapshot)

    assert ("disabled" in page.button("/control/motores/queues_tokens/iniciar")) is disabled
    fields = page.fields("/control/motores/queues_tokens/detener")
    assert fields["activation_id"]["value"] == activation
    assert fields["generation"]["value"] == "3"
    assert snapshot == original


@pytest.mark.parametrize("site_url_ready", [False, True])
def test_missing_active_member_disables_only_the_applicable_start(site_url_ready: bool) -> None:
    revoked = MemberView(str(uuid4()), "Revocado", "r•••@example.invalid", False)
    page, _, _ = render(members=(revoked,), site_url_ready=site_url_ready)

    queue_button = page.button("/control/motores/queues_tokens/iniciar")
    assert ("disabled" not in queue_button) is site_url_ready
    assert "disabled" in page.button("/control/motores/browsers_members/iniciar")
    for engine in ("queues_tokens", "browsers_members"):
        assert "disabled" in page.button(f"/control/motores/{engine}/detener")
    assert all(
        attrs.get("value") != revoked.member_id for tag, attrs in page.elements if tag == "option"
    )


def test_member_and_snapshot_text_cannot_create_markup_or_expose_extra_secret_fields() -> None:
    attack = '"><img src=x onerror="bad()">'
    member = MemberView(str(uuid4()), attack, "m•••@example.invalid", True)
    page, body, _ = render(
        members=(member,),
        csrf=attack,
        snapshot={
            "version": 1,
            "engines": [
                {
                    "engine": "queues_tokens",
                    "state": "RUNNING",
                    "phase": attack,
                    "sessions": [{"session_id": str(uuid4()), "phase": attack}],
                    "token": "not-for-aggregate-display",
                }
            ],
        },
    )

    assert not any(tag == "img" for tag, _ in page.elements)
    assert all(not key.startswith("on") for _, attrs in page.elements for key in attrs)
    assert page.fields("/control/motores/queues_tokens/iniciar")["csrf"]["value"] == attack
    assert b"not-for-aggregate-display" not in body
    options = [attrs for tag, attrs in page.elements if tag == "option"]
    assert any(attrs.get("value") == member.member_id for attrs in options)
    assert any(attrs.get("value") == "" and "selected" in attrs for attrs in options)


def test_inspection_links_use_only_valid_private_session_identities() -> None:
    session_id = str(uuid4())
    page, body, _ = render(
        snapshot={
            "version": 1,
            "engines": [
                {
                    "engine": "queues_tokens",
                    "state": "RUNNING",
                    "sessions": [
                        {
                            "session_id": session_id,
                            "browser": "chromium",
                            "display_url": "https://queue.example.invalid/path?bearer=secret#pass",
                        },
                        {"session_id": "../../configuracion", "browser": "firefox"},
                    ],
                }
            ],
        },
    )

    links = [attrs["href"] for tag, attrs in page.elements if tag == "a"]
    assert f"/control/sesiones/{session_id}" in links
    assert not any(str(link).startswith("https:") or "../" in str(link) for link in links)
    assert b"bearer=secret" not in body
    assert b"#pass" not in body
    assert b"https://queue.example.invalid/path" in body


@pytest.mark.parametrize(
    ("state", "hidden", "disabled"),
    [
        ("REQUIRED", False, False),
        ("REQUESTED", False, False),
        ("CLAIMED", False, False),
        ("NONE", True, True),
    ],
)
def test_previous_worker_recovery_uses_only_existing_scoped_stop_form(state, hidden, disabled):
    operation = str(uuid4())
    snapshot = {"version": 1, "engines": [], "legacy_recovery_state": state}
    before = copy.deepcopy(snapshot)
    page, _, _ = render(snapshot=snapshot, csrf="owner-proof", legacy_operation=operation)

    attributes = next(
        attrs for tag, attrs in page.elements if attrs.get("id") == "legacy-worker-recovery"
    )
    assert ("hidden" in attributes) is hidden
    fields = page.fields("/control/bot/detener")
    assert set(fields) == {"csrf", "operation_id"}
    assert fields["csrf"]["value"] == "owner-proof"
    assert fields["operation_id"]["value"] == operation
    assert ("disabled" in page.button("/control/bot/detener")) is disabled
    assert len(page.forms) == 5
    assert snapshot == before


def test_old_fixture_without_legacy_operation_has_only_four_engine_forms():
    page, _, _ = render(snapshot={"version": 1, "engines": [], "legacy_recovery_state": "REQUIRED"})
    assert len(page.forms) == 4
    assert "/control/bot/detener" not in page.forms
    assert not any(attrs.get("id") == "legacy-worker-recovery" for _, attrs in page.elements)


def test_received_queue_size_and_service_estimate_are_present_without_computation():
    _, body, _ = render(
        snapshot={
            "version": 1,
            "engines": [
                {
                    "engine": "queues_tokens",
                    "state": "RUNNING",
                    "sessions": [
                        {
                            "session_id": str(uuid4()),
                            "queue_size": 2034,
                            "expected_service_time": "2030-01-01T13:45:00Z <dato recibido>",
                        }
                    ],
                }
            ],
        }
    )
    assert b'data-field="queue_size">2034</dd>' in body
    assert (
        b'data-field="expected_service_time">2030-01-01T13:45:00Z &lt;dato recibido&gt;</dd>'
        in body
    )


@pytest.mark.parametrize("present", [True, False])
def test_actual_poll_script_updates_optional_recovery_without_replacing_its_operation(present):
    from boca_socios.panel import engine_view

    node = shutil.which("node")
    assert node is not None
    harness = r"""
const vm = require('node:vm');
const input = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
const elements = new Map();
let snapshot;
function element(id) {
  if (id === 'legacy-worker-recovery' && !input.present) return null;
  if (!elements.has(id)) elements.set(id, {
    textContent: '', hidden: true, disabled: true, children: [],
    dataset: {ready: 'true'}, fields: new Map(),
    addEventListener(name, callback) { this[name] = callback; },
    get elements() { return {namedItem: name => {
      if (!this.fields.has(name)) this.fields.set(name, {value: 'original-' + name});
      return this.fields.get(name);
    }}; }
  });
  return elements.get(id);
}
const operation = element('legacy-worker-recovery-form').elements.namedItem('operation_id');
const context = {
  document: {hidden: true, getElementById: element, addEventListener() {}},
  setInterval() {}, URL,
  fetch: async () => ({ok: true, json: async () => snapshot})
};
vm.runInNewContext(input.script, context, {timeout: 1000});
(async () => {
  const results = [];
  for (const state of ['NONE', 'REQUIRED', 'REQUESTED', 'CLAIMED', 'NONE']) {
    snapshot = {version: 1, observed_at: '2020-01-01T12:00:00Z', context_limit: 50,
      engines: [], legacy_recovery_state: state};
    await element('engines-refresh').click();
    const section = element('legacy-worker-recovery');
    results.push(section ? {hidden: section.hidden,
      disabled: element('legacy-worker-recovery-button').disabled} : null);
  }
  process.stdout.write(JSON.stringify({results, operation: operation.value,
    status: element('engines-live').textContent}));
})().catch(() => {process.exitCode = 1;});
"""
    completed = subprocess.run(  # noqa: S603 - actual static UI script, fixed offline DOM only
        [node, "-e", harness],
        input=json.dumps({"script": engine_view._SCRIPT, "present": present}),
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    result = json.loads(completed.stdout)
    expected = [
        {"hidden": True, "disabled": True},
        {"hidden": False, "disabled": False},
        {"hidden": False, "disabled": False},
        {"hidden": False, "disabled": False},
        {"hidden": True, "disabled": True},
    ]
    assert result["results"] == (expected if present else [None] * 5)
    assert result["operation"] == "original-operation_id"
    assert "históricos" not in result["status"]
