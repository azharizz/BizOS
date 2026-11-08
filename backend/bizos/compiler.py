"""Workspace Compiler: one evolving AG Studio canvas per workspace, designed freely.

The agent (or a person in Edit layout) places any AG Studio widget, any size, on any page, with any format options,
plus BizOS's own widgets: the plan graph, Mermaid diagrams, an ideas map, the written summary and PayPal action
cards. Widget kinds are built by a factory (`WIDGETS`); a kind maps the agent's simple spec (x, y, series...) onto
the AG Studio data mapping. Without a model, `compose_default` lays out a flow's suggested widgets.
AG Studio field ids are `source.field`.
"""
import html
import copy
import json
import re

COLUMNS = 12
WIDTH = {"quarter": 3, "third": 4, "half": 6, "two-thirds": 8, "full": 12}
HEIGHT = {"short": 8, "medium": 11, "tall": 15}
MONEY = re.compile(r"amount|revenue|cost|price|spend|paid|profit|inflow|saving|discount_given|extra_usd|difference|outstanding|lost_|salary|budget")
TONE = {"bad": "#D23F4A", "good": "#1F7A55"}
KPI_FORMAT = {"$": "currencyFormat"}
DIAGRAMS = ("flowchart", "graph", "sequenceDiagram", "gantt", "mindmap", "timeline", "stateDiagram", "stateDiagram-v2",
            "erDiagram", "journey", "classDiagram", "pie", "quadrantChart", "gitGraph", "block-beta", "sankey-beta", "xychart-beta")
HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
FONT = re.compile(r"^[A-Za-z0-9 ,'-]{1,60}$")


def _format(name: str, value) -> str:
    if isinstance(value, bool) or isinstance(value, str) or value is None:
        return "textFormat"
    if MONEY.search(name):
        return "currencyFormat"
    return "integerFormat" if isinstance(value, int) else "decimalFormat"


def make_source(sid: str, rows: list[dict], fmt: dict | None = None) -> dict:
    sample = {k: next((r[k] for r in rows if r.get(k) is not None), None) for k in rows[0]}
    return {"id": sid, "name": sid.replace("_", " ").title(), "data": rows,
            "fields": [{"id": k, "name": k.replace("_", " ").replace(" pct", " %").capitalize(),
                        "format": (fmt or {}).get(k) or _format(k, v)} for k, v in sample.items()]}


# ---------------- widget factory: spec -> AG Studio widget state
def _ref(source: dict, fid: str, aggregation: str | None = None) -> dict:
    if source is None:
        raise KeyError("this widget needs a data source")
    if fid not in {f["id"] for f in source["fields"]}:
        raise KeyError(f"{source['id']} has no field '{fid}'. Fields: {[f['id'] for f in source['fields']]}")
    ref = {"id": f"{source['id']}.{fid}"}
    return {**ref, "aggregation": aggregation} if aggregation else ref


def _need(spec: dict, key: str, what: str):
    if not spec.get(key):
        raise KeyError(f"{spec['kind']} needs {key} ({what})")
    return spec[key]


def _cartesian(kind: str, legend: bool = True):
    def build(spec: dict, source: dict) -> dict:
        agg = spec.get("agg") or "sum"
        mapping = {"categoryKey": [_ref(source, _need(spec, "x", "the category or date field"))],
                   "valueKey": [_ref(source, y, agg) for y in _need(spec, "y", "the value fields")]}
        if legend and spec.get("series"):
            mapping["legendKey"] = [_ref(source, spec["series"])]
        return {"type": kind, "dataMapping": mapping}
    return build


def _parts(kind: str):  # one category, one value: donut, pie, funnel, pyramid
    def build(spec: dict, source: dict) -> dict:
        return {"type": kind, "dataMapping": {"categoryKey": [_ref(source, _need(spec, "x", "the category field"))],
                                              "valueKey": [_ref(source, _need(spec, "y", "the value field")[0], spec.get("agg") or "sum")]}}
    return build


def _hierarchy(kind: str):  # treemap, sunburst: x plus deeper `levels`
    def build(spec: dict, source: dict) -> dict:
        levels = [_need(spec, "x", "the top-level category")] + list(spec.get("levels") or [])
        return {"type": kind, "dataMapping": {"categoryKey": [_ref(source, f) for f in levels],
                                              "valueKey": [_ref(source, _need(spec, "y", "the size field")[0], spec.get("agg") or "sum")]}}
    return build


def _points(kind: str, sized: bool):  # scatter, bubble: one point per `group` value
    def build(spec: dict, source: dict) -> dict:
        agg = spec.get("agg") or "sum"
        mapping = {"categoryKey": [_ref(source, _need(spec, "x", "the x-axis number field"), agg)],
                   "valueKey": [_ref(source, _need(spec, "y", "the y-axis number field")[0], agg)],
                   "groupByKey": [_ref(source, _need(spec, "group", "the field that names each point"))]}
        if sized:
            mapping["sizeKey"] = [_ref(source, _need(spec, "size", "the number field that sizes each bubble"), agg)]
        if spec.get("series"):
            mapping["legendKey"] = [_ref(source, spec["series"])]
        return {"type": kind, "dataMapping": mapping}
    return build


def _combo(kind: str):
    def build(spec: dict, source: dict) -> dict:
        agg = spec.get("agg") or "sum"
        return {"type": kind, "dataMapping": {
            "categoryKey": [_ref(source, _need(spec, "x", "the category field"))],
            "valueKey": [_ref(source, y, agg) for y in _need(spec, "y", "the column fields")],
            "secondaryValueKey": [_ref(source, y, agg) for y in _need(spec, "y2", "the line fields")]}}
    return build


def _grid(spec: dict, source: dict) -> dict:
    cols = spec.get("cols") or [f["id"] for f in source["fields"]]
    return {"type": "grid", "dataMapping": {"cols": [_ref(source, c) for c in cols]}, "format": {"style": {"columnAutoSize": True}}}


def _pivot(spec: dict, source: dict) -> dict:
    agg = spec.get("agg") or "sum"
    return {"type": "pivot-grid", "dataMapping": {"rows": [_ref(source, f) for f in _need(spec, "rows", "row fields")],
                                                  "columns": [_ref(source, f) for f in spec.get("columns") or []],
                                                  "values": [_ref(source, f, agg) for f in _need(spec, "values", "value fields")]}}


def _value(spec: dict, source: dict) -> dict:
    style = {"textScaling": {"enabled": True}, "verticalAlign": "center"}
    if spec.get("tone") in TONE:
        style["color"] = TONE[spec["tone"]]
    mapping = {"value": [_ref(source, _need(spec, "value", "the number to show"), spec.get("agg") or "sum")]}
    if spec.get("x"):  # a sparkline under the number
        mapping["sparklineX"] = [_ref(source, spec["x"])]
    return {"type": "value", "dataMapping": mapping, "format": {"style": style}}


def _single(kind: str, aggregate: bool):  # gauges (a number), filters (a field to filter by)
    def build(spec: dict, source: dict) -> dict:
        field = _need(spec, "value", "the field")
        return {"type": kind, "dataMapping": {"value": [_ref(source, field, (spec.get("agg") or "sum") if aggregate else None)]}}
    return build


def _note(spec: dict, _source) -> dict:
    return {"type": "text", "dataMapping": {}, "format": {"style": {
        "text": spec.get("text") or spec["title"], "verticalAlign": "center", "typography": {"fontSize": 18, "fontWeight": 650}}}}




def _image(spec: dict, _source) -> dict:
    src = _need(spec, "src", "the image URL")
    if not re.match(r"^(https?://|data:image/(png|jpeg|gif|webp);base64,)", src):
        raise ValueError("an image needs an http(s) URL")
    return {"type": "image", "dataMapping": {}, "format": {"style": {"src": src[:2000], "fit": spec.get("fit") or "contain"}}}


def _custom(kind: str, build_content):
    """A BizOS widget. Its content is kept in the workspace by widget id (ws["content"]), not in the AG format:
    AG Studio drops format keys it doesn't know, and a layout saved from Edit layout must not erase it."""
    def build(spec: dict, _source) -> dict:
        return {"type": kind, "dataMapping": {}, "_content": build_content(spec)}
    return build


def _diagram_style(spec: dict) -> dict:
    text = _need(spec, "source_text", "Mermaid diagram text").strip()
    if text.split(None, 1)[0] not in DIAGRAMS:
        raise ValueError(f"start with a Mermaid diagram type: one of {list(DIAGRAMS)}")
    return {"source": text[:20000]}


def _ideas_style(spec: dict) -> dict:
    ideas = spec.get("ideas") or []
    if not 1 <= len(ideas) <= 8 or not all(isinstance(i, dict) and i.get("label") for i in ideas):
        raise ValueError("ideas needs 1-8 ideas, each {label, effort, risk, ask}")
    keep = [{"label": str(i["label"])[:80], "effort": str(i.get("effort", ""))[:20], "risk": str(i.get("risk", ""))[:20],
             "ask": str(i.get("ask") or i["label"])[:300]} for i in ideas]
    return {"center": str(spec.get("center") or spec["title"])[:120], "ideas": keep}


CARTESIAN = {"bar": "bar-chart-grouped", "stacked-bar": "bar-chart-stacked", "bar-100": "bar-chart-stacked-100",
             "column": "column-chart-grouped", "stacked-column": "column-chart-stacked", "column-100": "column-chart-stacked-100",
             "line": "line-chart", "area": "area-chart", "stacked-area": "area-chart-stacked", "area-100": "area-chart-stacked-100"}
RADIAL = {"radar-line": "radar-line-chart", "radar-area": "radar-area-chart", "radial-bar": "radial-bar-chart",
          "radial-column": "radial-column-chart", "nightingale": "nightingale-chart"}
PARTS = {"donut": "donut-chart", "pie": "pie-chart", "funnel": "funnel-chart", "cone-funnel": "cone-funnel-chart", "pyramid": "pyramid-chart"}
WIDGETS = {
    "kpi": _value, **{k: _cartesian(v) for k, v in CARTESIAN.items()}, **{k: _cartesian(v, legend=False) for k, v in RADIAL.items()},
    **{k: _parts(v) for k, v in PARTS.items()}, "treemap": _hierarchy("treemap-chart"), "sunburst": _hierarchy("sunburst-chart"),
    "scatter": _points("scatter-chart", sized=False), "bubble": _points("bubble-chart", sized=True),
    "combo": _combo("combo-chart-grouped-column-line"), "stacked-combo": _combo("combo-chart-stacked-column-line"),
    "grid": _grid, "pivot": _pivot, "gauge": _single("radial-gauge", True), "linear-gauge": _single("linear-gauge", True),
    "list-filter": _single("list-filter", False), "date-filter": _single("date-filter", False), "button-filter": _single("button-filter", False),
    "note": _note, "image": _image,
    "text": _custom("bizos-text", lambda s: {"text": _need(s, "text", "the text (Markdown)")[:20000]}),
    # BizOS's own widgets (desktop/src/renderer/src/workspace/widgets.tsx)
    "plan": _custom("bizos-plan", lambda s: {}), "summary": _custom("bizos-summary", lambda s: {}),
    "diagram": _custom("bizos-diagram", _diagram_style), "ideas": _custom("bizos-ideas", _ideas_style),
    "action": _custom("bizos-action", lambda s: {"actionId": str(_need(s, "action_id", "the PayPal action id"))[:40]}),
}
KINDS = sorted(WIDGETS)
SOURCELESS = {"note", "text", "image", "plan", "summary", "diagram", "ideas", "action"}
SIZE = {"kpi": (3, 5), "note": (12, 3), "text": (6, 6), "grid": (12, 14), "pivot": (12, 14), "image": (4, 8),
        "gauge": (3, 8), "linear-gauge": (4, 5), "list-filter": (3, 3), "date-filter": (3, 3), "button-filter": (6, 3),
        "plan": (12, 13), "diagram": (12, 14), "ideas": (12, 14), "summary": (4, 12), "action": (4, 14)}


def _merge(base: dict, patch: dict) -> dict:
    for k, v in patch.items():
        base[k] = _merge(base.get(k) if isinstance(base.get(k), dict) else {}, v) if isinstance(v, dict) else v
    return base


def _checked_format(fmt) -> dict:
    if not isinstance(fmt, dict):
        raise ValueError("format must be an object of AG Studio format options")
    if len(json.dumps(fmt)) > 6000:
        raise ValueError("format is too large")
    return copy.deepcopy(fmt)


def make_widget(spec: dict, source: dict | None) -> dict:
    widget = WIDGETS[spec["kind"]](spec, source)
    if spec.get("title") and spec["kind"] != "note":
        widget.setdefault("format", {})["title"] = {"text": spec["title"], "enabled": True}
    if spec.get("format"):
        _merge(widget.setdefault("format", {}), _checked_format(spec["format"]))
    return widget


def _box(size, default: int, named: dict, lo: int, hi: int) -> int:
    if isinstance(size, int) and not isinstance(size, bool):
        return max(lo, min(hi, size))
    return named.get(size or "", default)


# ---------------- the canvas
def new_page(pid: str) -> dict:
    return {"id": pid, "widgets": {}, "widgetLayout": {}, "layout": {"columns": COLUMNS, "rowHeight": 24}}


def new_workspace(ws_id: str) -> dict:
    return {"id": ws_id, "title": "", "headline": "", "narrative": "", "complete": False, "actions": [], "risks": [],
            "runs": [], "seq": 0, "data": {"sources": []}, "state": {"pages": [new_page("canvas")], "selectedPageId": "canvas"},
            "pages": [{"id": "canvas", "title": "Overview"}], "theme": {}, "plan": None, "content": {}, "agent_version": 0}


def widget_count(ws: dict) -> int:
    return sum(len(p.get("widgets", {})) for p in ws["state"]["pages"])


class Canvas:
    def __init__(self, ws: dict, page: str | None = None):
        self.ws = ws
        ws.setdefault("pages", [{"id": p["id"], "title": "Overview" if i == 0 else f"Page {i + 1}"} for i, p in enumerate(ws["state"]["pages"])])
        ws.setdefault("theme", {})
        ws.setdefault("plan", None)
        ws.setdefault("content", {})
        self.use_page(page or ws["state"].get("selectedPageId") or ws["state"]["pages"][0]["id"])

    def _bump(self):
        self.ws["agent_version"] += 1

    # ---- pages (AG Studio keeps pages; BizOS names them and shows the tabs)
    def use_page(self, pid: str):
        page = next((p for p in self.ws["state"]["pages"] if p["id"] == pid), None)
        if not page:
            raise KeyError(f"no page '{pid}'. pages: {[p['id'] for p in self.ws['state']['pages']]}")
        self.page = page
        self.page.setdefault("widgets", {})
        self.page.setdefault("widgetLayout", {})
        self.floor = self.bottom()  # this run's widgets go below what was already there

    def add_page(self, title: str) -> str:
        self.ws["seq"] += 1
        pid = f"p{self.ws['seq']}"
        self.ws["state"]["pages"].append(new_page(pid))
        self.ws["pages"].append({"id": pid, "title": html.unescape(title).strip()[:40] or f"Page {len(self.ws['pages']) + 1}"})
        self.ws["state"]["selectedPageId"] = pid
        self.use_page(pid)
        self._bump()
        return pid

    def set_theme(self, theme: dict):
        """Colours and fonts for this workspace (AG Studio theme params on the desktop)."""
        clean = {}
        for k, v in theme.items():
            if k in ("accent", "background", "canvas", "widget", "border", "text"):
                if not isinstance(v, str) or not HEX.match(v):
                    raise ValueError(f"{k} must be a colour like #4DFFB2")
                clean[k] = v
            elif k == "palette":
                if not isinstance(v, list) or not 1 <= len(v) <= 8 or not all(isinstance(c, str) and HEX.match(c) for c in v):
                    raise ValueError("palette must be 1-8 colours like #4DFFB2")
                clean[k] = v
            elif k == "font":
                if not isinstance(v, str) or not FONT.match(v):
                    raise ValueError("font must be a font family name")
                clean[k] = v
            elif k == "radius":
                clean[k] = max(0, min(28, int(v)))
        self.ws["theme"] = {**self.ws.get("theme", {}), **clean}
        self._bump()

    # ---- data
    def source(self, sid: str) -> dict | None:
        return next((s for s in self.ws["data"]["sources"] if s["id"] == sid), None)

    def put_source(self, sid: str, rows: list[dict], fmt: dict | None = None):
        if not rows:
            return
        self.ws["data"]["sources"] = [s for s in self.ws["data"]["sources"] if s["id"] != sid] + [make_source(sid, rows, fmt)]
        self._bump()

    # ---- layout
    def bottom(self) -> int:
        return max((b["yTrack"] + b["ySpan"] for b in self.page["widgetLayout"].values()), default=0)

    def place(self, w: int, h: int) -> dict:
        """First free w x h box at or below this run's floor, left to right, top to bottom."""
        taken = {(x, y) for b in self.page["widgetLayout"].values()
                 for x in range(b["xTrack"], b["xTrack"] + b["xSpan"]) for y in range(b["yTrack"], b["yTrack"] + b["ySpan"])}
        y = self.floor
        while True:
            for x in range(COLUMNS - w + 1):
                if all((i, j) not in taken for i in range(x, x + w) for j in range(y, y + h)):
                    return {"xTrack": x, "yTrack": y, "xSpan": w, "ySpan": h}
            y += 1

    def _find(self, wid: str) -> dict:
        page = next((p for p in self.ws["state"]["pages"] if wid in p.get("widgets", {})), None)
        if not page:
            raise KeyError(f"no widget {wid}")
        return page

    def add(self, spec: dict, replace: str | None = None) -> str:
        kind = spec["kind"]
        if kind not in WIDGETS:
            raise KeyError(f"unknown widget kind '{kind}'. Use one of {KINDS}")
        source = None
        if kind not in SOURCELESS:
            source = self.source(spec.get("source") or "")
            if not source:
                raise KeyError(f"unknown source '{spec.get('source')}'. Sources: {[s['id'] for s in self.ws['data']['sources']]}")
        widget = make_widget(spec, source)
        content = widget.pop("_content", None)
        dw, dh = SIZE.get(kind, (6, HEIGHT["medium"]))
        w = _box(spec.get("width"), dw, WIDTH, 1, COLUMNS) if kind != "kpi" or spec.get("width") else dw
        h = _box(spec.get("height"), dh, HEIGHT, 2, 40) if kind not in ("kpi", "note") else dh
        if replace and replace in self.page["widgets"]:
            box = self.page["widgetLayout"].pop(replace)
            del self.page["widgets"][replace]
            self.ws["content"].pop(replace, None)
        else:
            box = self.place(w, h)
        self.ws["seq"] += 1
        wid = f"w{self.ws['seq']}"
        self.page["widgets"][wid] = widget
        self.page["widgetLayout"][wid] = box
        if content:
            self.ws["content"][wid] = content
        self._bump()
        return wid

    def configure(self, wid: str, fmt, title: str | None = None):
        """Change any AG Studio format option of a widget (colours, labels, axes, legend...), deep-merged."""
        widget = self._find(wid)["widgets"][wid]
        _merge(widget.setdefault("format", {}), _checked_format(fmt))
        if title:
            widget["format"]["title"] = {"text": html.unescape(title)[:120], "enabled": True}
        self._bump()

    def move(self, wid: str, x: int, y: int, width: int, height: int):
        """Put a widget exactly here (12-column grid, rows of 24px)."""
        page = self._find(wid)
        width = max(1, min(COLUMNS, width))
        page["widgetLayout"][wid] = {"xTrack": max(0, min(COLUMNS - width, x)), "yTrack": max(0, y), "xSpan": width, "ySpan": max(2, min(40, height))}
        self._bump()

    def add_kpi(self, label: str, value: float, unit: str = "", tone: str = "neutral", width: str = "quarter") -> str:
        sid = "kpi_" + re.sub(r"\W+", "_", label.lower()).strip("_")[:40]
        shown = round(value, 1) if unit in ("%", "x", "d") else value  # keep 1.08% from rounding to "1%"
        whole = unit == "" and float(shown).is_integer()
        self.put_source(sid, [{"value": int(shown) if whole else shown}], {"value": KPI_FORMAT.get(unit, "integerFormat" if whole else "decimalFormat")})
        suffix = {"x": " (×)", "d": " (days)", "%": " (%)"}.get(unit, "")
        return self.add({"kind": "kpi", "source": sid, "value": "value", "title": label + suffix, "tone": tone, "width": width},
                        replace=next((k for k, v in self.page["widgets"].items()
                                      if v["dataMapping"].get("value", [{}])[0].get("id", "").startswith(sid + ".")), None))

    def remove(self, wid: str):
        page = self._find(wid)
        del page["widgets"][wid]
        del page["widgetLayout"][wid]
        self.ws["content"].pop(wid, None)
        current = self.page
        self.page = page
        self.compact()
        self.page = current
        self._bump()

    def compact(self):
        """Vertical gravity, like any grid layout: every widget slides up into free space, keeping its column."""
        placed: list[dict] = []
        for wid, b in sorted(self.page["widgetLayout"].items(), key=lambda kv: (kv[1]["yTrack"], kv[1]["xTrack"])):
            def clear(y):
                return all(b["xTrack"] + b["xSpan"] <= p["xTrack"] or p["xTrack"] + p["xSpan"] <= b["xTrack"]
                           or y + b["ySpan"] <= p["yTrack"] or p["yTrack"] + p["ySpan"] <= y for p in placed)
            y = 0
            while not clear(y):
                y += 1
            b["yTrack"] = y
            placed.append(b)
        self.floor = min(self.floor, self.bottom())

    def summary(self) -> dict:
        def describe(w):
            refs = [r["id"] for v in w["dataMapping"].values() for r in v]
            return {"kind": w["type"], "title": (w.get("format", {}).get("title") or {}).get("text"), "fields": refs[:6]}
        return {"pages": [{"id": p["id"], "title": p["title"]} for p in self.ws["pages"]], "current_page": self.page["id"],
                "theme": self.ws.get("theme", {}),
                "widgets": {k: {**describe(w), "page": p["id"], "box": p["widgetLayout"][k]}
                            for p in self.ws["state"]["pages"] for k, w in p.get("widgets", {}).items()},
                "sources": {s["id"]: [f["id"] for f in s["fields"]] for s in self.ws["data"]["sources"] if not s["id"].startswith("kpi_")},
                "actions": [{"id": a["id"], "label": a["label"]} for a in self.ws["actions"]]}


def has_chart(canvas: Canvas) -> bool:
    return any(w["type"] not in ("value", "text") for p in canvas.ws["state"]["pages"] for w in p.get("widgets", {}).values())


def compose_default(canvas: Canvas, findings, kpis: bool = True) -> None:
    """Fallback layout when the agent didn't design one: KPI row, charts two per row, one table last."""
    n = len(findings.kpis) if kpis else 0
    width = "quarter" if n % 4 == 0 or n > 4 else {1: "full", 2: "half", 3: "third"}.get(n, "third")
    for k in findings.kpis[:n]:
        canvas.add_kpi(k["label"], k["value"], k["unit"], k["tone"], width)
    kinds = {"bar": "bar", "column": "column", "line": "line"}
    grids = [w for w in findings.widgets if w["type"] == "grid"][:1]
    for w in [w for w in findings.widgets if w["type"] != "grid"] + grids:
        spec = {"kind": kinds.get(w["type"], w["type"]), "source": w["source"], "title": w["title"],
                "x": w.get("x"), "y": w.get("y", []), "series": w.get("series"), "cols": w.get("cols")}
        try:
            canvas.add(spec)
        except (KeyError, ValueError):
            continue


LINEAGE_TITLE = "Where the data came from"


RESEARCH_TITLE = "Supplier sites BizOS read in Chrome"


def _has_widget(canvas: Canvas, title: str) -> bool:
    return any((w.get("format", {}).get("title") or {}).get("text") == title
               for p in canvas.ws["state"]["pages"] for w in p.get("widgets", {}).values())


def ensure_lineage(canvas: Canvas, findings) -> None:
    """A flow that can say where its numbers came from gets that as a diagram in the workspace (once), and a flow that read
    several sites gets the table of what it found there."""
    if "research_log" in findings.tables and not _has_widget(canvas, RESEARCH_TITLE):
        try:
            canvas.add({"kind": "grid", "source": "research_log", "title": RESEARCH_TITLE,
                        "cols": ["site", "country", "unit_price", "moq", "lead_days", "terms", "status"]})
        except (KeyError, ValueError):
            pass
    if not getattr(findings, "diagram", ""):
        return
    for p in canvas.ws["state"]["pages"]:
        if any((w.get("format", {}).get("title") or {}).get("text") == LINEAGE_TITLE for w in p.get("widgets", {}).values()):
            return
    try:
        canvas.add({"kind": "diagram", "title": LINEAGE_TITLE, "source_text": findings.diagram})
    except (KeyError, ValueError):
        pass


def register(canvas: Canvas, findings, pinned: dict) -> None:
    """Make a run's evidence available as sources and record its actions and risks."""
    for sid, rows in findings.tables.items():
        canvas.put_source(sid, rows)
    for sid, pin in pinned.items():
        canvas.put_source(sid, pin["rows"])
    ws = canvas.ws
    known = {a["id"] for a in ws["actions"]}
    ws["actions"] += [a for a in findings.actions if a["id"] not in known]
    ws["risks"] += [r for r in findings.risks if r not in ws["risks"]]
    ws["title"] = ws["title"] or findings.title
    ws["headline"] = findings.headline or ws["headline"]
