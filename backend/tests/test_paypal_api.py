"""The general PayPal tool: one list of approved endpoints. Reads run freely; every write becomes a proposed
action that only a person can execute (press-and-hold), with the same approval, idempotency and audit rules."""
import asyncio
import json

import httpx
import pytest

from bizos import actions


class Fake:
    def __init__(self):
        self.calls: list[httpx.Request] = []

    def __call__(self, request: httpx.Request):
        self.calls.append(request)
        path = request.url.path
        if path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "T", "expires_in": 3600})
        if path == "/v1/checkout/payment-resources" and request.method == "POST":
            return httpx.Response(201, json={"id": "PLB-1", "status": "ACTIVE", "links": [
                {"rel": "self", "href": "https://api-m.sandbox.paypal.com/v1/checkout/payment-resources/PLB-1"},
                {"rel": "payment_link", "href": "https://www.sandbox.paypal.com/ncp/payment/PLB-1"}]})
        if path == "/v1/checkout/payment-resources/PLB-1":
            return httpx.Response(200, json={"id": "PLB-1", "status": "ACTIVE"})
        if path == "/v1/reporting/balances":
            return httpx.Response(200, json={"balances": [{"currency": "USD", "total_balance": {"value": "120.00"}}]})
        if path == "/v2/payments/captures/CAP1/refund":
            return httpx.Response(201, json={"id": "REF1", "status": "COMPLETED"})
        return httpx.Response(404, json={"message": "not found"})


@pytest.fixture
def pp():
    fake = Fake()
    return actions.PayPal("id", "secret", "https://api-m.sandbox.paypal.com", transport=httpx.MockTransport(fake)), fake


def test_catalog_has_tiers_and_never_card_or_vault_endpoints():
    tiers = {e.tier for e in actions.CATALOG.values()}
    assert tiers == {"read", "act", "money"}
    assert actions.CATALOG["capture_refund"].tier == "money" and actions.CATALOG["payment_link_create"].tier == "act"
    assert not any("vault" in e.path or "payment-tokens" in e.path for e in actions.CATALOG.values())


async def test_reads_run_and_writes_are_refused_on_the_read_path(pp):
    client, fake = pp
    body = await client.read("balances")
    assert body["balances"][0]["currency"] == "USD"
    with pytest.raises(PermissionError, match="needs approval"):
        await client.read("payment_link_create")
    with pytest.raises(KeyError, match="unknown PayPal endpoint"):
        await client.read("vault_tokens")


@pytest.mark.parametrize("bad", ["../oauth2/token", "a/b", "x?y=1", "", "a" * 80])
async def test_path_parameters_cannot_escape_the_endpoint(pp, bad):
    client, _ = pp
    with pytest.raises(ValueError, match="invalid"):
        await client.read("payment_link_get", {"id": bad})


def test_proposals_fill_payment_link_defaults_and_validate():
    spec = actions.propose("payment_link_create", {}, {"line_items": [{"name": "Cold Brew 1L", "unit_amount": {"currency_code": "USD", "value": "8.40"}}]},
                           label="Payment link: Cold Brew 1L", why="New product launch", aid="pp-1")
    assert spec["kind"] == "paypal" and spec["tier"] == "act" and spec["amount"] == 8.4
    assert spec["body"]["integration_mode"] == "LINK" and spec["body"]["reusable"] == "MULTIPLE" and spec["body"]["return_url"]
    with pytest.raises(PermissionError, match="read"):
        actions.propose("balances", {}, {}, label="x", why="", aid="pp-2")
    with pytest.raises(ValueError, match="line_items"):
        actions.propose("payment_link_create", {}, {}, label="x", why="", aid="pp-3")


async def test_a_proposed_payment_link_needs_approval_then_runs_once(pp, tmp_path):
    client, fake = pp
    engine = actions.ActionEngine(client, tmp_path / "audit.jsonl")
    spec = actions.propose("payment_link_create", {}, {"line_items": [{"name": "Cold Brew 1L", "unit_amount": {"currency_code": "USD", "value": "8.40"}}]},
                           label="Payment link", why="launch", aid="pp-1")
    prev = engine.preview("w1", spec)
    assert prev["mode"] == "sandbox" and prev["request"] == "POST /v1/checkout/payment-resources"
    with pytest.raises(actions.ApprovalRequired):
        await engine.execute("w1", spec, prev["idempotency_key"], "")
    r1 = await engine.execute("w1", spec, prev["idempotency_key"], "Azhar")
    r2 = await engine.execute("w1", spec, prev["idempotency_key"], "Azhar")
    assert r1 == r2 and r1["reference"] == "PLB-1" and r1["link"].endswith("/PLB-1") and r1["status"] == "ACTIVE"
    posts = [c for c in fake.calls if c.method == "POST" and c.url.path == "/v1/checkout/payment-resources"]
    assert len(posts) == 1 and posts[0].headers["PayPal-Request-Id"] == prev["idempotency_key"]
    assert json.loads(posts[0].content)["line_items"][0]["name"] == "Cold Brew 1L"
    log = engine.log()
    assert [e["outcome"] for e in log] == ["refused", "executed", "replayed"] and log[1]["kind"] == "paypal"
    status = await engine.status(spec, r1)
    assert status == {"status": "ACTIVE", "reference": "PLB-1"}


async def test_money_endpoints_are_real_refunds(pp, tmp_path):
    client, fake = pp
    engine = actions.ActionEngine(client, tmp_path / "audit.jsonl")
    spec = actions.propose("capture_refund", {"capture_id": "CAP1"}, {"amount": {"value": "12.00", "currency_code": "USD"}},
                           label="Refund duplicate", why="charged twice", aid="pp-9")
    assert spec["tier"] == "money" and spec["amount"] == 12.0
    prev = engine.preview("w1", spec)
    assert prev["request"] == "POST /v2/payments/captures/CAP1/refund"
    r = await engine.execute("w1", spec, prev["idempotency_key"], "me")
    assert r == {"status": "COMPLETED", "reference": "REF1", "link": None}


def test_a_different_body_is_a_different_approval():
    a = actions.propose("payment_link_create", {}, {"line_items": [{"name": "A", "unit_amount": {"currency_code": "USD", "value": "1.00"}}]}, label="x", why="", aid="pp-1")
    b = {**a, "body": {**a["body"], "line_items": [{"name": "A", "unit_amount": {"currency_code": "USD", "value": "100.00"}}]}}
    assert actions.ActionEngine.key("w", a) != actions.ActionEngine.key("w", b)


def test_payment_link_body_keeps_only_fields_paypal_accepts():
    # Seen live: the model added quantity and a top-level description -> PayPal 422 "failed business validation".
    spec = actions.propose("payment_link_create", {}, {"description": "Cold Brew 1L", "line_items": [
        {"name": "Cold Brew 1L", "quantity": 1, "unit_amount": {"currency_code": "USD", "value": "8.40"}}]},
        label="x", why="", aid="pp-1")
    assert set(spec["body"]) == {"integration_mode", "type", "reusable", "return_url", "line_items"}
    assert spec["body"]["line_items"] == [{"name": "Cold Brew 1L", "description": "Cold Brew 1L",
                                           "unit_amount": {"currency_code": "USD", "value": "8.40"}}]


def test_paypal_validation_errors_say_why():
    def answer(request):
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "T", "expires_in": 3600})
        return httpx.Response(422, json={"name": "UNPROCESSABLE_ENTITY", "message": "failed business validation", "debug_id": "d1",
                                         "details": [{"field": "/line_items/0/quantity", "issue": "UNKNOWN_FIELD"}]})
    client = actions.PayPal("id", "s", "https://api-m.sandbox.paypal.com", transport=httpx.MockTransport(answer))
    with pytest.raises(actions.PayPalError) as e:
        asyncio.run(client.read("balances"))
    assert e.value.status == 422 and "/line_items/0/quantity UNKNOWN_FIELD" in str(e.value)
