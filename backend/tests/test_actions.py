"""Money-movement safety rules: approval, idempotency, audit, server-side preview."""
import json

import httpx
import pytest

from bizos import actions


class FakePayPal:
    """httpx transport that records calls and answers like the sandbox."""

    def __init__(self):
        self.calls = []

    def __call__(self, request: httpx.Request):
        self.calls.append(request)
        path = request.url.path
        if path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "T", "expires_in": 3600})
        if path == "/v1/payments/payouts":
            return httpx.Response(201, json={"batch_header": {"payout_batch_id": "B1", "batch_status": "PENDING"}})
        if path == "/v2/invoicing/invoices":
            return httpx.Response(201, json={"href": "https://api-m.sandbox.paypal.com/v2/invoicing/invoices/INV2-X"})
        if path.endswith("/send"):
            return httpx.Response(200, json={"href": "https://www.sandbox.paypal.com/invoice/p/#INV2-X"})
        return httpx.Response(404)


@pytest.fixture
def engine(tmp_path):
    fake = FakePayPal()
    client = actions.PayPal("id", "secret", "https://api-m.sandbox.paypal.com", transport=httpx.MockTransport(fake))
    return actions.ActionEngine(client, tmp_path / "audit.jsonl"), fake


PAYOUT = {"id": "a1", "kind": "payout", "label": "Pay supplier", "amount": 1250.5, "currency": "USD",
          "recipient": "Cedar Industries 3", "email": "supplier3@bizos.example", "source": "PO #12"}


async def test_preview_shows_amount_recipient_source_and_key(engine):
    eng, _ = engine
    p = eng.preview("ws1", PAYOUT)
    assert p["amount"] == 1250.5 and p["recipient"] == "Cedar Industries 3" and p["source"] == "PO #12"
    assert p["idempotency_key"] == eng.preview("ws1", PAYOUT)["idempotency_key"]
    assert p["mode"] == "sandbox"


async def test_execute_without_approval_is_refused_and_audited(engine):
    eng, fake = engine
    key = eng.preview("ws1", PAYOUT)["idempotency_key"]
    with pytest.raises(actions.ApprovalRequired):
        await eng.execute("ws1", PAYOUT, key, approved_by="")
    assert not fake.calls
    log = [json.loads(line) for line in eng.audit_path.read_text().splitlines()]
    assert log[-1]["outcome"] == "refused"


async def test_payout_runs_once_per_idempotency_key(engine):
    eng, fake = engine
    key = eng.preview("ws1", PAYOUT)["idempotency_key"]
    first = await eng.execute("ws1", PAYOUT, key, approved_by="ceo@bizos")
    second = await eng.execute("ws1", PAYOUT, key, approved_by="ceo@bizos")
    assert first == second and first["status"] == "PENDING"
    payouts = [c for c in fake.calls if c.url.path == "/v1/payments/payouts"]
    assert len(payouts) == 1
    body = json.loads(payouts[0].content)
    assert body["sender_batch_header"]["sender_batch_id"] == key
    assert body["items"][0]["amount"] == {"value": "1250.50", "currency": "USD"}
    log = [json.loads(line) for line in eng.audit_path.read_text().splitlines()]
    assert [e["outcome"] for e in log] == ["executed", "replayed"]
    assert log[0]["approved_by"] == "ceo@bizos" and log[0]["evidence"]["source"] == "PO #12"


async def test_wrong_key_is_rejected(engine):
    eng, _ = engine
    with pytest.raises(actions.ApprovalRequired):
        await eng.execute("ws1", PAYOUT, "forged", approved_by="ceo@bizos")


async def test_invoice_reminder_creates_and_sends(engine):
    eng, fake = engine
    spec = {"id": "a2", "kind": "invoice_reminder", "label": "Remind", "amount": 99.0, "currency": "USD",
            "recipient": "Apex Foods 12", "email": "ap@customer12.example.com", "source": "Invoice #77"}
    key = eng.preview("ws1", spec)["idempotency_key"]
    res = await eng.execute("ws1", spec, key, approved_by="fin@bizos")
    assert res["status"] == "SENT"
    create = next(c for c in fake.calls if c.url.path == "/v2/invoicing/invoices")
    assert create.headers["PayPal-Request-Id"] == key


async def test_draft_actions_never_call_paypal(engine):
    eng, fake = engine
    spec = {"id": "a3", "kind": "draft", "label": "Draft price change", "amount": 0, "currency": "USD",
            "recipient": "Pricing team", "source": "price_gaps"}
    key = eng.preview("ws1", spec)["idempotency_key"]
    res = await eng.execute("ws1", spec, key, approved_by="ceo@bizos")
    assert res["status"] == "DRAFTED" and not fake.calls


def test_preview_only_without_credentials(tmp_path):
    eng = actions.ActionEngine(None, tmp_path / "a.jsonl")
    assert eng.preview("ws1", PAYOUT)["mode"] == "preview-only"


def test_unknown_action_kind():
    with pytest.raises(KeyError):
        actions.make_action("wire_to_cayman")
