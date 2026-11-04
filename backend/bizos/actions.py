"""Action Engine: approved operations through PayPal Sandbox.

Safety rules live in decorators so every write path gets them:
    @audited            every attempt is logged with who approved it and the evidence
    @requires_approval  a person must approve, with the key issued by the server-side preview
    @idempotent         one key executes once; repeats return the first result
Action kinds are built by `make_action(kind)` (factory).
"""
import functools
import hashlib
import json
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx


class ApprovalRequired(Exception):
    pass


def _check(r: httpx.Response, api: str):
    """Turn PayPal's permission errors into the fix, and keep its debug_id for support tickets."""
    if r.status_code in (401, 403):
        raise PermissionError(f"PayPal {api} is not enabled for this app (HTTP {r.status_code}). "
                              f"Enable it under Apps & Credentials > your app > Features at developer.paypal.com.")
    if r.is_error:
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        raise RuntimeError(f"PayPal {api} error {r.status_code}: {body.get('message') or r.text[:200]} (debug_id {body.get('debug_id')})")


class PayPal:
    def __init__(self, client_id: str, secret: str, base_url: str, transport: httpx.AsyncBaseTransport | None = None):
        self._auth = (client_id, secret)
        self.http = httpx.AsyncClient(base_url=base_url, transport=transport, timeout=20)
        self._token, self._expires = "", 0.0

    async def _headers(self, request_id: str) -> dict:
        if time.time() >= self._expires:
            r = await self.http.post("/v1/oauth2/token", data={"grant_type": "client_credentials"}, auth=self._auth)
            r.raise_for_status()
            body = r.json()
            self._token, self._expires = body["access_token"], time.time() + body["expires_in"] - 60
        return {"Authorization": f"Bearer {self._token}", "PayPal-Request-Id": request_id}

    async def payout(self, spec: dict, key: str) -> dict:
        body = {"sender_batch_header": {"sender_batch_id": key, "email_subject": f"Payment from BizOS: {spec['source']}"},
                "items": [{"recipient_type": "EMAIL", "receiver": spec["email"], "sender_item_id": spec["id"], "note": spec["source"],
                           "amount": {"value": f"{spec['amount']:.2f}", "currency": spec["currency"]}}]}
        r = await self.http.post("/v1/payments/payouts", json=body, headers=await self._headers(key))
        _check(r, "Payouts")
        head = r.json()["batch_header"]
        return {"status": head["batch_status"], "reference": head["payout_batch_id"]}

    async def remind(self, spec: dict, key: str) -> dict:
        body = {"detail": {"currency_code": spec["currency"], "invoice_number": f"BZ-{key[:16]}", "note": spec["source"],
                           "payment_term": {"due_date": (date.today() + timedelta(days=7)).isoformat()}},
                "primary_recipients": [{"billing_info": {"email_address": spec["email"], "business_name": spec["recipient"]}}],
                "items": [{"name": spec["source"], "quantity": "1",
                           "unit_amount": {"currency_code": spec["currency"], "value": f"{spec['amount']:.2f}"}}]}
        r = await self.http.post("/v2/invoicing/invoices", json=body, headers=await self._headers(key))
        _check(r, "Invoicing")
        inv_id = r.json()["href"].rsplit("/", 1)[-1]
        s = await self.http.post(f"/v2/invoicing/invoices/{inv_id}/send", json={"send_to_invoicer": False},
                                 headers=await self._headers(f"{key}-send"))
        _check(s, "Invoicing")
        return {"status": "SENT", "reference": inv_id, "link": s.json().get("href")}


    # ---- read-only (agent tools)
    async def _get(self, path: str, **params) -> dict:
        r = await self.http.get(path, params=params, headers={"Authorization": (await self._headers("read"))["Authorization"]})
        _check(r, {"/v1/reporting/transactions": "Transaction Search"}.get(path, path))
        return r.json()

    async def transactions(self, days: int) -> list[dict]:
        """Transaction Search: max 31-day window per request."""
        end = datetime.now(timezone.utc).replace(microsecond=0)
        body = await self._get("/v1/reporting/transactions", start_date=(end - timedelta(days=min(days, 31))).isoformat(),
                               end_date=end.isoformat(), fields="transaction_info", page_size=100)
        return [{"id": t["transaction_info"].get("transaction_id"), "status": t["transaction_info"].get("transaction_status"),
                 "amount": t["transaction_info"].get("transaction_amount", {}).get("value"),
                 "date": t["transaction_info"].get("transaction_initiation_date")} for t in body.get("transaction_details", [])]

    async def disputes(self) -> list[dict]:
        body = await self._get("/v1/customer/disputes", page_size=20)
        return [{"id": d.get("dispute_id"), "reason": d.get("reason"), "status": d.get("status"),
                 "amount": (d.get("dispute_amount") or {}).get("value")} for d in body.get("items", [])]

    async def payout_status(self, batch_id: str) -> dict:
        body = await self._get(f"/v1/payments/payouts/{batch_id}")
        items = body.get("items") or [{}]
        return {"batch": body["batch_header"]["batch_status"], "item": items[0].get("transaction_status"),
                "errors": (items[0].get("errors") or {}).get("message")}


# ---- action kinds (factory)
async def _payout(paypal, spec, key):
    return await paypal.payout(spec, key) if paypal else {"status": "PREVIEW_ONLY", "reference": None}


async def _remind(paypal, spec, key):
    return await paypal.remind(spec, key) if paypal else {"status": "PREVIEW_ONLY", "reference": None}


async def _draft(_paypal, _spec, key):
    return {"status": "DRAFTED", "reference": f"DRAFT-{key[:8].upper()}"}


ACTIONS = {"payout": _payout, "invoice_reminder": _remind, "draft": _draft}


def make_action(kind: str):
    return ACTIONS[kind]


# ---- safety decorators
def audited(fn):
    @functools.wraps(fn)
    async def wrap(self, ws_id, spec, key, approved_by):
        entry = {"at": datetime.now(timezone.utc).isoformat(), "workspace_id": ws_id, "action_id": spec["id"], "kind": spec["kind"],
                 "approved_by": approved_by, "idempotency_key": key,
                 "evidence": {k: spec.get(k) for k in ("label", "amount", "currency", "recipient", "source", "why")}}
        replay = key in self.results
        try:
            result = await fn(self, ws_id, spec, key, approved_by)
            entry["outcome"] = "replayed" if replay else "previewed-only" if result["status"] == "PREVIEW_ONLY" else "executed"
            entry["result"] = result
            return result
        except ApprovalRequired as e:
            entry["outcome"], entry["error"] = "refused", str(e)
            raise
        except Exception as e:
            entry["outcome"], entry["error"] = "failed", str(e)[:500]
            raise
        finally:
            with self.audit_path.open("a") as f:
                f.write(json.dumps(entry) + "\n")
    return wrap


def requires_approval(fn):
    @functools.wraps(fn)
    async def wrap(self, ws_id, spec, key, approved_by):
        if not approved_by.strip():
            raise ApprovalRequired("a person must approve this action")
        if key != self.key(ws_id, spec):
            raise ApprovalRequired("approval key does not match the previewed action")
        return await fn(self, ws_id, spec, key, approved_by)
    return wrap


def idempotent(fn):
    @functools.wraps(fn)
    async def wrap(self, ws_id, spec, key, approved_by):
        # ponytail: in-memory; PayPal also dedupes on sender_batch_id / PayPal-Request-Id across restarts
        if key not in self.results:
            self.results[key] = await fn(self, ws_id, spec, key, approved_by)
        return self.results[key]
    return wrap


class ActionEngine:
    def __init__(self, paypal: PayPal | None, audit_path: Path):
        self.paypal, self.audit_path, self.results = paypal, Path(audit_path), {}

    @staticmethod
    def key(ws_id: str, spec: dict) -> str:
        raw = json.dumps([ws_id, spec["id"], spec["kind"], spec["amount"], spec["recipient"], spec.get("email")])
        return hashlib.sha256(raw.encode()).hexdigest()[:32]

    def preview(self, ws_id: str, spec: dict) -> dict:
        mode = "draft" if spec["kind"] == "draft" else "sandbox" if self.paypal else "preview-only"
        return {**{k: spec.get(k) for k in ("id", "kind", "label", "amount", "currency", "recipient", "email", "source", "why")},
                "mode": mode, "idempotency_key": self.key(ws_id, spec)}

    @audited
    @requires_approval
    @idempotent
    async def execute(self, ws_id: str, spec: dict, key: str, approved_by: str) -> dict:
        return await make_action(spec["kind"])(self.paypal, spec, key)

    def log(self) -> list[dict]:
        if not self.audit_path.exists():
            return []
        return [json.loads(line) for line in self.audit_path.read_text().splitlines()]
