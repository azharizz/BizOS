"""Workspace Compiler: one evolving AG Studio canvas per workspace.

The agent designs the dashboard through `Canvas` (KPI value tiles, the chart type that fits the data, sizes on a
12-column grid, at most one table). Follow-up runs edit the same canvas. Widget kinds are built by a factory
(`WIDGETS`). Without a model, `compose_default` lays out a flow's suggested widgets the same way.
AG Studio field ids are `source.field`.
"""
import re

COLUMNS = 12
WIDTH = {"quarter": 3, "third": 4, "half": 6, "two-thirds": 8, "full": 12}
HEIGHT = {"short": 8, "medium": 11, "tall": 15}
MONEY = re.compile(r"amount|revenue|cost|price|spend|paid|profit|inflow|saving|discount_given|extra_usd|difference|outstanding|lost_|salary|budget")
TONE = {"bad": "#D23F4A", "good": "#1F7A55"}
KPI_FORMAT = {"$": "currencyFormat"}


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
    if fid not in {f["id"] for f in source["fields"]}:
        raise KeyError(f"{source['id']} has no field '{fid}'. Fields: {[f['id'] for f in source['fields']]}")
    ref = {"id": f"{source['id']}.{fid}"}
    return {**ref, "aggregation": aggregation} if aggregation else ref


def _cartesian(kind: str):
    def build(spec: dict, source: dict) -> dict:
        agg = spec.get("agg") or "sum"
        mapping = {"categoryKey": [_ref(source, spec["x"])], "valueKey": [_ref(source, y, agg) for y in spec["y"]]}
        if spec.get("series"):
            mapping["legendKey"] = [_ref(source, spec["series"])]
        return {"type": kind, "dataMapping": mapping}
    return build


def _parts(kind: str):  # one category, one value: donut, pie, treemap, funnel
    def build(spec: dict, source: dict) -> dict:
        return {"type": kind, "dataMapping": {"categoryKey": [_ref(source, spec["x"])],
                                              "valueKey": [_ref(source, spec["y"][0], spec.get("agg") or "sum")]}}
    return build


def _combo(spec: dict, source: dict) -> dict:
    agg = spec.get("agg") or "sum"
    return {"type": "combo-chart-grouped-column-line", "dataMapping": {
        "categoryKey": [_ref(source, spec["x"])], "valueKey": [_ref(source, y, agg) for y in spec["y"]],
        "secondaryValueKey": [_ref(source, y, agg) for y in spec["y2"]]}}


def _grid(spec: dict, source: dict) -> dict:
    cols = spec.get("cols") or [f["id"] for f in source["fields"]]
    return {"type": "grid", "dataMapping": {"cols": [_ref(source, c) for c in cols]}, "format": {"style": {"columnAutoSize": True}}}


def _value(spec: dict, source: dict) -> dict:
    style = {"textScaling": {"enabled": True}, "verticalAlign": "center"}
    if spec.get("tone") in TONE:
        style["color"] = TONE[spec["tone"]]
    return {"type": "value", "dataMapping": {"value": [_ref(source, spec["value"], spec.get("agg") or "sum")]}, "format": {"style": style}}


def _note(spec: dict, _source) -> dict:
    return {"type": "text", "dataMapping": {}, "format": {"style": {
        "text": spec["text"], "verticalAlign": "center", "typography": {"fontSize": 18, "fontWeight": 650}}}}


WIDGETS = {
    "kpi": _value, "bar": _cartesian("bar-chart-grouped"), "column": _cartesian("column-chart-grouped"),
    "stacked-column": _cartesian("column-chart-stacked"), "line": _cartesian("line-chart"), "area": _cartesian("area-chart"),
    "donut": _parts("donut-chart"), "pie": _parts("pie-chart"), "treemap": _parts("treemap-chart"),
    "funnel": _parts("funnel-chart"), "combo": _combo, "grid": _grid, "note": _note,
}
KINDS = sorted(WIDGETS)


def make_widget(spec: dict, source: dict | None) -> dict:
    widget = WIDGETS[spec["kind"]](spec, source)
    if spec.get("title") and spec["kind"] != "note":
        widget.setdefault("format", {})["title"] = {"text": spec["title"], "enabled": True}
    return widget


# ---------------- the canvas
def new_workspace(ws_id: str) -> dict:
    page = {"id": "canvas", "widgets": {}, "widgetLayout": {}, "layout": {"columns": COLUMNS, "rowHeight": 24}}
    return {"id": ws_id, "title": "", "headline": "", "narrative": "", "complete": False, "actions": [], "risks": [],
            "runs": [], "seq": 0, "data": {"sources": []}, "state": {"pages": [page], "selectedPageId": "canvas"}, "agent_version": 0}


class Canvas:
    def __init__(self, ws: dict):
        self.ws = ws
        self.page = ws["state"]["pages"][0]
        self.floor = self.bottom()  # this run's widgets go below what was already there

    def _bump(self):
        self.ws["agent_version"] += 1

    def source(self, sid: str) -> dict | None:
        return next((s for s in self.ws["data"]["sources"] if s["id"] == sid), None)

    def put_source(self, sid: str, rows: list[dict], fmt: dict | None = None):
        if not rows:
            return
        self.ws["data"]["sources"] = [s for s in self.ws["data"]["sources"] if s["id"] != sid] + [make_source(sid, rows, fmt)]
        self._bump()

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

    def add(self, spec: dict, replace: str | None = None) -> str:
        kind = spec["kind"]
        if kind not in WIDGETS:
            raise KeyError(f"unknown widget kind '{kind}'. Use one of {KINDS}")
        if kind == "grid" and sum(w["type"] == "grid" for w in self.page["widgets"].values()) >= 1 and not replace:
            raise ValueError("this canvas already has a table; prefer a chart, or replace the existing table")
        source = None if kind == "note" else self.source(spec["source"])
        if kind != "note" and not source:
            raise KeyError(f"unknown source '{spec.get('source')}'. Sources: {[s['id'] for s in self.ws['data']['sources']]}")
        widget = make_widget(spec, source)
        default_w = {"kpi": "quarter", "grid": "full", "note": "full"}.get(kind, "half")
        default_h = {"kpi": 5, "note": 3, "grid": 14}.get(kind, HEIGHT["medium"])
        w = WIDTH.get(spec.get("width") or default_w, 6)
        h = HEIGHT.get(spec.get("height") or "", default_h) if kind not in ("kpi", "note") else default_h
        if replace and replace in self.page["widgets"]:
            box = self.page["widgetLayout"].pop(replace)
            del self.page["widgets"][replace]
        else:
            box = self.place(w, h)
        self.ws["seq"] += 1
        wid = f"w{self.ws['seq']}"
        self.page["widgets"][wid] = widget
        self.page["widgetLayout"][wid] = box
        self._bump()
        return wid

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
        if wid not in self.page["widgets"]:
            raise KeyError(f"no widget {wid}")
        del self.page["widgets"][wid]
        del self.page["widgetLayout"][wid]
        self.compact()
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
        return {"widgets": {k: {**describe(w), "box": self.page["widgetLayout"][k]} for k, w in self.page["widgets"].items()},
                "sources": {s["id"]: [f["id"] for f in s["fields"]] for s in self.ws["data"]["sources"] if not s["id"].startswith("kpi_")}}


def has_chart(canvas: Canvas) -> bool:
    return any(w["type"] not in ("value", "text") for w in canvas.page["widgets"].values())


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
