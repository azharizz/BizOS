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


@pytest.fixture(autouse=True)
def full_scale(monkeypatch):
    monkeypatch.setattr(actions.config, "PAYPAL_DEMO_SCALE", 1.0)  # the real .env may run the Sandbox demo at a smaller scale


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


# ---- the cash gate sees money held in unsettled payouts, and a refusal is explained
def money_handler(available="4998.75", item_status="UNCLAIMED"):
    def handler(request: httpx.Request):
        p = request.url.path
        if p == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "T", "expires_in": 3600})
        if p == "/v1/reporting/balances":
            return httpx.Response(200, json={"as_of_time": "2026-11-08T03:59:00Z", "balances": [
                {"currency": "USD", "available_balance": {"value": available}, "withheld_balance": {"value": "0.00"}}]})
        if p.startswith("/v1/payments/payouts/"):
            return httpx.Response(200, json={"items": [{"transaction_status": item_status, "payout_item": {"amount": {"value": "1000.00"}},
                                                        "payout_item_fee": {"value": "20.00"}}]})
        if p == "/v1/payments/payouts" and request.method == "POST":
            return httpx.Response(422, json={"name": "INSUFFICIENT_FUNDS", "message": "Sender does not have sufficient funds. Please add funds and retry.",
                                             "debug_id": "d1"})
        return httpx.Response(404, json={"message": "no"})
    return handler


def test_net_balance_subtracts_money_held_in_payouts_we_sent(tmp_path, monkeypatch):
    audit = tmp_path / "audit.jsonl"
    audit.write_text(json.dumps({"at": actions.datetime.now(actions.timezone.utc).isoformat(), "kind": "payout", "outcome": "executed",
                                 "result": {"reference": "B1", "status": "PENDING"}}) + "\n")
    monkeypatch.setattr(actions.config, "AUDIT_PATH", audit)
    pp = actions.PayPal("i", "s", "https://api-m.sandbox.paypal.com", transport=httpx.MockTransport(money_handler()))
    nb = asyncio.run(actions.net_balance(pp))
    assert nb["listed"] == 4998.75 and nb["held"] == 1020.0 and nb["available"] == 3978.75


def test_a_settled_payout_holds_nothing(tmp_path, monkeypatch):
    audit = tmp_path / "audit.jsonl"
    audit.write_text(json.dumps({"at": actions.datetime.now(actions.timezone.utc).isoformat(), "kind": "payout", "outcome": "executed",
                                 "result": {"reference": "B1"}}) + "\n")
    monkeypatch.setattr(actions.config, "AUDIT_PATH", audit)
    pp = actions.PayPal("i", "s", "https://api-m.sandbox.paypal.com", transport=httpx.MockTransport(money_handler(item_status="SUCCESS")))
    assert asyncio.run(actions.net_balance(pp))["held"] == 0


def test_demo_scale_shrinks_what_is_sent_and_grows_the_plan_cash(tmp_path, monkeypatch):
    monkeypatch.setattr(actions.config, "AUDIT_PATH", tmp_path / "none.jsonl")
    monkeypatch.setattr(actions.config, "PAYPAL_DEMO_SCALE", 0.1)
    pp = actions.PayPal("i", "s", "https://api-m.sandbox.paypal.com", transport=httpx.MockTransport(money_handler(available="434.00")))
    nb = asyncio.run(actions.net_balance(pp))
    assert nb["available"] == 4340.0 and nb["sandbox_available"] == 434.0 and nb["scale"] == 0.1


def test_insufficient_funds_is_explained_not_dumped(tmp_path):
    pp = actions.PayPal("i", "s", "https://api-m.sandbox.paypal.com", transport=httpx.MockTransport(money_handler()))
    spec = {"id": "p", "amount": 5000.0, "currency": "USD", "email": "a@b.c", "source": "PO", "kind": "payout"}
    with pytest.raises(actions.PayPalError) as e:
        asyncio.run(pp.payout(spec, "k"))
    assert "does not have enough available money" in str(e.value) and "PAYPAL_SANDBOX_RECEIVER" in str(e.value)


def test_demo_scale_changes_the_amount_actually_sent(monkeypatch):
    monkeypatch.setattr(actions.config, "PAYPAL_DEMO_SCALE", 0.1)
    seen = {}

    def handler(request: httpx.Request):
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "T", "expires_in": 3600})
        seen["body"] = json.loads(request.content)
        return httpx.Response(201, json={"batch_header": {"batch_status": "PENDING", "payout_batch_id": "B9"}})
    pp = actions.PayPal("i", "s", "https://api-m.sandbox.paypal.com", transport=httpx.MockTransport(handler))
    out = asyncio.run(pp.payout({"id": "p", "amount": 3293.76, "currency": "USD", "email": "a@b.c", "source": "PO"}, "k"))
    assert seen["body"]["items"][0]["amount"]["value"] == "329.38" and out["reference"] == "B9"


def test_payouts_sent_before_the_balance_snapshot_are_not_subtracted_twice(tmp_path, monkeypatch):
    audit = tmp_path / "audit.jsonl"
    old = "2026-11-08T03:00:00+00:00"  # before as_of_time 03:59 in money_handler
    audit.write_text(json.dumps({"at": old, "kind": "payout", "outcome": "executed", "result": {"reference": "OLD"}}) + "\n")
    monkeypatch.setattr(actions.config, "AUDIT_PATH", audit)
    pp = actions.PayPal("i", "s", "https://api-m.sandbox.paypal.com", transport=httpx.MockTransport(money_handler()))
    nb = asyncio.run(actions.net_balance(pp))
    assert nb["held"] == 0 and nb["available"] == 4998.75
