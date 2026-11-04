"""Action Engine: approved operations through PayPal Sandbox.

Safety rules live in decorators so every write path gets them:
    @audited            every attempt is logged with who approved it and the evidence
    @requires_approval  a person must approve, with the key issued by the server-side preview
    @idempotent         one key executes once; repeats return the first result
Action kinds are built by `make_action(kind)` (factory).

The general PayPal tool is one list of approved endpoints (`CATALOG`), each with a risk tier:
    read   the agent calls it directly (PayPal.read)
    act    a change (create a payment link, send an invoice): proposed, then a person approves it
    money  moves money (refund, capture, payout): proposed, then a person approves it
Card, vault and identity endpoints are never on the list, so no prompt can reach them.
"""
import copy
import functools
import hashlib
import json
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx

from . import config


class ApprovalRequired(Exception):
    pass


class PayPalError(RuntimeError):
    """PayPal said no. `status` < 500 means the request itself was wrong (shown to the user as is)."""

    def __init__(self, message: str, status: int):
        super().__init__(message)
        self.status = status


def _check(r: httpx.Response, api: str):
    """Turn PayPal's permission errors into the fix, and keep its debug_id for support tickets."""
    if r.status_code in (401, 403):
        raise PermissionError(f"PayPal {api} is not enabled for this app (HTTP {r.status_code}). "
                              f"Enable it under Apps & Credentials > your app > Features at developer.paypal.com.")
    if r.is_error:
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        why = "; ".join(f"{d.get('field', '')} {d.get('issue', '')} {d.get('description', '')}".strip() for d in body.get("details") or [])
        raise PayPalError(f"PayPal {api} error {r.status_code}: {body.get('message') or r.text[:200]}"
                          f"{f' ({why})' if why else ''} (debug_id {body.get('debug_id')})", r.status_code)


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


    # ---- the general tool: any endpoint on the approved list
    async def call(self, endpoint: str, params: dict | None = None, query: dict | None = None, body: dict | None = None,
                   key: str | None = None) -> dict:
        e = CATALOG[endpoint]
        headers = await self._headers(key or "read")
        if e.method == "GET":
            headers.pop("PayPal-Request-Id")
        r = await self.http.request(e.method, fill(e.path, params or {}), params={**e.defaults(), **(query or {})},
                                    json=body if e.method != "GET" else None, headers=headers)
        _check(r, endpoint)
        return r.json() if r.content and r.headers.get("content-type", "").startswith("application/json") else {}

    async def read(self, endpoint: str, params: dict | None = None, query: dict | None = None, body: dict | None = None) -> dict:
        if endpoint not in CATALOG:
            raise KeyError(f"unknown PayPal endpoint '{endpoint}'. Reads: {sorted(k for k, e in CATALOG.items() if e.tier == 'read')}")
        if CATALOG[endpoint].tier != "read":
            raise PermissionError(f"{endpoint} changes something at PayPal: it needs approval. Propose it instead (paypal_propose).")
        return await self.call(endpoint, params, query, body)

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


# ---- the approved PayPal endpoints
def _last_days(days: int = 30) -> dict:
    end = datetime.now(timezone.utc).replace(microsecond=0)
    return {"start_date": (end - timedelta(days=days)).isoformat(), "end_date": end.isoformat(), "fields": "all", "page_size": 100}


@dataclass(frozen=True)
class Endpoint:
    method: str
    path: str
    tier: str  # read | act | money
    about: str
    follow: tuple[str, str] | None = None  # (read endpoint, its id param): where to check the result's live status
    defaults: object = dict  # default query for reads

E = Endpoint
CATALOG: dict[str, Endpoint] = {
    # reads
    "transactions_search": E("GET", "/v1/reporting/transactions", "read", "Transactions in a date range (max 31 days); query start_date, end_date (ISO)", defaults=_last_days),
    "balances": E("GET", "/v1/reporting/balances", "read", "Account balances by currency"),
    "invoices_list": E("GET", "/v2/invoicing/invoices", "read", "Invoices (query page, page_size, total_required)"),
    "invoice_get": E("GET", "/v2/invoicing/invoices/{invoice_id}", "read", "One invoice with status and payments"),
    "invoices_search": E("POST", "/v2/invoicing/search-invoices", "read", "Search invoices; body e.g. {status:[UNPAID]}"),
    "disputes_list": E("GET", "/v1/customer/disputes", "read", "Disputes (query dispute_state, page_size)"),
    "dispute_get": E("GET", "/v1/customer/disputes/{dispute_id}", "read", "One dispute with reason, amount and messages"),
    "payout_get": E("GET", "/v1/payments/payouts/{payout_batch_id}", "read", "A payout batch and its item status"),
    "order_get": E("GET", "/v2/checkout/orders/{order_id}", "read", "A checkout order"),
    "capture_get": E("GET", "/v2/payments/captures/{capture_id}", "read", "A captured payment"),
    "refund_get": E("GET", "/v2/payments/refunds/{refund_id}", "read", "A refund"),
    "products_list": E("GET", "/v1/catalogs/products", "read", "Catalog products"),
    "product_get": E("GET", "/v1/catalogs/products/{product_id}", "read", "One catalog product"),
    "plans_list": E("GET", "/v1/billing/plans", "read", "Subscription plans"),
    "subscription_get": E("GET", "/v1/billing/subscriptions/{subscription_id}", "read", "One subscription"),
    "payment_links_list": E("GET", "/v1/checkout/payment-resources", "read", "Payment links"),
    "payment_link_get": E("GET", "/v1/checkout/payment-resources/{id}", "read", "One payment link and its status"),
    "webhooks_list": E("GET", "/v1/notifications/webhooks", "read", "Registered webhooks"),
    # changes (a person approves)
    "payment_link_create": E("POST", "/v1/checkout/payment-resources", "act", "Shareable payment link for a product; body line_items[{name, unit_amount{currency_code, value}}]", ("payment_link_get", "id")),
    "payment_link_update": E("PUT", "/v1/checkout/payment-resources/{id}", "act", "Replace a payment link (full body)", ("payment_link_get", "id")),
    "payment_link_delete": E("DELETE", "/v1/checkout/payment-resources/{id}", "act", "Delete a payment link (permanent)"),
    "product_create": E("POST", "/v1/catalogs/products", "act", "Catalog product; body {name, type: PHYSICAL|DIGITAL|SERVICE, description}", ("product_get", "product_id")),
    "invoice_create": E("POST", "/v2/invoicing/invoices", "act", "Draft invoice; body {detail{currency_code}, primary_recipients, items}", ("invoice_get", "invoice_id")),
    "invoice_send": E("POST", "/v2/invoicing/invoices/{invoice_id}/send", "act", "Send a draft invoice to the payer", ("invoice_get", "invoice_id")),
    "invoice_remind": E("POST", "/v2/invoicing/invoices/{invoice_id}/remind", "act", "Remind the payer of an unpaid invoice", ("invoice_get", "invoice_id")),
    "invoice_cancel": E("POST", "/v2/invoicing/invoices/{invoice_id}/cancel", "act", "Cancel a sent invoice", ("invoice_get", "invoice_id")),
    "invoice_record_payment": E("POST", "/v2/invoicing/invoices/{invoice_id}/payments", "act", "Record a payment made outside PayPal; body {method, amount}", ("invoice_get", "invoice_id")),
    "order_create": E("POST", "/v2/checkout/orders", "act", "One-off checkout (approve link); body {intent: CAPTURE, purchase_units[{amount}]}", ("order_get", "order_id")),
    "plan_create": E("POST", "/v1/billing/plans", "act", "Subscription plan for a product"),
    "subscription_cancel": E("POST", "/v1/billing/subscriptions/{subscription_id}/cancel", "act", "Cancel a subscription; body {reason}", ("subscription_get", "subscription_id")),
    "dispute_send_message": E("POST", "/v1/customer/disputes/{dispute_id}/send-message", "act", "Reply to the buyer in a dispute; body {message}", ("dispute_get", "dispute_id")),
    # money
    "capture_refund": E("POST", "/v2/payments/captures/{capture_id}/refund", "money", "Refund a captured payment (all, or body {amount{value, currency_code}})", ("refund_get", "refund_id")),
    "order_capture": E("POST", "/v2/checkout/orders/{order_id}/capture", "money", "Capture an approved order", ("order_get", "order_id")),
    "payout_create": E("POST", "/v1/payments/payouts", "money", "Send money by email; body {sender_batch_header, items}", ("payout_get", "payout_batch_id")),
    "dispute_accept_claim": E("POST", "/v1/customer/disputes/{dispute_id}/accept-claim", "money", "Accept a dispute claim (refunds the buyer); body {note}", ("dispute_get", "dispute_id")),
}
PARAM = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
LINK_ITEM = {"name", "description", "unit_amount", "product_id", "taxes", "shipping", "discounts", "handling",
             "collect_shipping_address", "customer_notes", "variants", "adjustable_quantity"}


def fill(path: str, params: dict) -> str:
    """Put ids into the path. An id is letters, digits, - and _ only, so it can't reach another endpoint."""
    def one(m):
        v = str(params.get(m.group(1), ""))
        if not PARAM.match(v):
            raise ValueError(f"invalid {m.group(1)} '{v[:30]}'")
        return v
    return re.sub(r"\{(\w+)\}", one, path)


def _amount(body: dict) -> float:
    """The money in a request, for the approval card: the first amount value found."""
    for k, v in (body.items() if isinstance(body, dict) else enumerate(body if isinstance(body, list) else [])):
        if k in ("value",) and isinstance(v, str) and re.fullmatch(r"\d+(\.\d+)?", v):
            return float(v)
        if isinstance(v, (dict, list)) and (found := _amount(v)):
            return found
    return 0.0


def propose(endpoint: str, params: dict, body: dict, label: str, why: str, aid: str) -> dict:
    """A PayPal change the agent wants: becomes an action card a person must approve (never run by the agent)."""
    e = CATALOG.get(endpoint)
    if not e:
        raise KeyError(f"unknown PayPal endpoint '{endpoint}'")
    if e.tier == "read":
        raise PermissionError(f"{endpoint} is a read: call paypal_read instead")
    if not isinstance(body, dict) or not isinstance(params, dict):
        raise ValueError("params and body must be JSON objects")
    fill(e.path, params)  # validates ids now, not at approval time
    body = copy.deepcopy(body)
    if endpoint == "payment_link_create":
        if not body.get("line_items"):
            raise ValueError("a payment link needs line_items: [{name, unit_amount: {currency_code, value}}]")
        # Only fields PayPal accepts: models like to add quantity or a top-level description (PayPal: 422).
        about = body.get("description")
        items = [{k: v for k, v in i.items() if k in LINK_ITEM} for i in body["line_items"] if isinstance(i, dict)]
        if about and items and not items[0].get("description"):
            items[0]["description"] = str(about)[:127]
        body = {"integration_mode": "LINK", "type": "BUY_NOW", "reusable": "MULTIPLE", "return_url": config.PAYPAL_RETURN_URL,
                **{k: v for k, v in body.items() if k in ("integration_mode", "type", "reusable", "return_url")}, "line_items": items}
    currency = next(iter(re.findall(r'"currency(?:_code)?": "([A-Z]{3})"', json.dumps(body))), "USD")
    return {"id": aid, "kind": "paypal", "endpoint": endpoint, "params": params, "body": body, "tier": e.tier,
            "label": label[:120], "why": why[:300], "amount": _amount(body), "currency": currency,
            "recipient": "PayPal", "source": e.about.split(";")[0], "request": f"{e.method} {fill(e.path, params)}"}


def _result(body: dict) -> dict:
    links = {l.get("rel"): l.get("href") for l in body.get("links", []) if isinstance(l, dict)}
    return {"status": body.get("status") or "DONE", "reference": body.get("id"),
            "link": links.get("payment_link") or links.get("approve") or links.get("payer-action")}


# ---- action kinds (factory)
async def _payout(paypal, spec, key):
    return await paypal.payout(spec, key) if paypal else {"status": "PREVIEW_ONLY", "reference": None}


async def _remind(paypal, spec, key):
    return await paypal.remind(spec, key) if paypal else {"status": "PREVIEW_ONLY", "reference": None}


async def _draft(_paypal, _spec, key):
    return {"status": "DRAFTED", "reference": f"DRAFT-{key[:8].upper()}"}


async def _paypal(paypal, spec, key):
    if not paypal:
        return {"status": "PREVIEW_ONLY", "reference": None}
    return _result(await paypal.call(spec["endpoint"], spec["params"], body=spec["body"], key=key))


ACTIONS = {"payout": _payout, "invoice_reminder": _remind, "draft": _draft, "paypal": _paypal}


def make_action(kind: str):
    return ACTIONS[kind]


# ---- safety decorators
def audited(fn):
    @functools.wraps(fn)
    async def wrap(self, ws_id, spec, key, approved_by):
        entry = {"at": datetime.now(timezone.utc).isoformat(), "workspace_id": ws_id, "action_id": spec["id"], "kind": spec["kind"],
                 "approved_by": approved_by, "idempotency_key": key,
                 "evidence": {k: spec.get(k) for k in ("label", "amount", "currency", "recipient", "source", "why", "request", "body")}}
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
        raw = json.dumps([ws_id, spec["id"], spec["kind"], spec["amount"], spec["recipient"], spec.get("email"),
                          spec.get("endpoint"), spec.get("params"), spec.get("body")], sort_keys=True)
        return hashlib.sha256(raw.encode()).hexdigest()[:32]

    def preview(self, ws_id: str, spec: dict) -> dict:
        mode = "draft" if spec["kind"] == "draft" else "sandbox" if self.paypal else "preview-only"
        return {**{k: spec.get(k) for k in ("id", "kind", "label", "amount", "currency", "recipient", "email", "source", "why",
                                             "endpoint", "tier", "request", "body")},
                "mode": mode, "idempotency_key": self.key(ws_id, spec)}

    async def status(self, spec: dict, result: dict) -> dict | None:
        """Live status of what an approved PayPal action created (a payment link, an invoice, a refund...)."""
        e = CATALOG.get(spec.get("endpoint", ""))
        if not self.paypal or not e or not e.follow or not result.get("reference"):
            return None
        endpoint, param = e.follow
        params = {**spec.get("params", {}), param: result["reference"]}
        body = await self.paypal.read(endpoint, params)
        head = body.get("batch_header") or body
        return {"status": head.get("status") or head.get("batch_status") or "UNKNOWN", "reference": result["reference"]}

    @audited
    @requires_approval
    @idempotent
    async def execute(self, ws_id: str, spec: dict, key: str, approved_by: str) -> dict:
        return await make_action(spec["kind"])(self.paypal, spec, key)

    def log(self) -> list[dict]:
        if not self.audit_path.exists():
            return []
        return [json.loads(line) for line in self.audit_path.read_text().splitlines()]
