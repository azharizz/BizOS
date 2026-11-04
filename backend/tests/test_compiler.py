"""The canvas: valid AG Studio state, real grid layout, few tables, follow-up runs edit the same workspace."""
import pytest

from bizos import compiler, flows


def build(name):
    findings = flows.make_flow(name).run({})
    ws = compiler.new_workspace("t")
    canvas = compiler.Canvas(ws)
    compiler.register(canvas, findings, {})
    compiler.compose_default(canvas, findings)
    return ws, canvas


def boxes_overlap(a, b):
    return not (a["xTrack"] + a["xSpan"] <= b["xTrack"] or b["xTrack"] + b["xSpan"] <= a["xTrack"]
                or a["yTrack"] + a["ySpan"] <= b["yTrack"] or b["yTrack"] + b["ySpan"] <= a["yTrack"])


@pytest.mark.parametrize("name", list(flows.FLOWS))
def test_every_flow_composes_a_valid_dashboard(name):
    ws, _ = build(name)
    sources = {s["id"]: {f["id"] for f in s["fields"]} for s in ws["data"]["sources"]}
    page = ws["state"]["pages"][0]
    types = [w["type"] for w in page["widgets"].values()]
    assert types.count("value") >= 3, "KPIs live in the canvas as value tiles"
    assert types.count("grid") <= 1, "never drown the user in tables"
    assert set(page["widgets"]) == set(page["widgetLayout"])
    for w in page["widgets"].values():
        for refs in w["dataMapping"].values():
            for ref in refs:
                src, field = ref["id"].split(".", 1)
                assert field in sources[src], ref
    boxes = list(page["widgetLayout"].values())
    assert all(b["xTrack"] + b["xSpan"] <= compiler.COLUMNS for b in boxes)
    assert not any(boxes_overlap(a, b) for i, a in enumerate(boxes) for b in boxes[i + 1:])


def test_kpis_fill_a_row_and_percent_keeps_a_decimal():
    ws, canvas = build("finance")  # 6 KPIs -> quarter width, two rows
    kpis = [b for k, b in ws["state"]["pages"][0]["widgetLayout"].items() if ws["state"]["pages"][0]["widgets"][k]["type"] == "value"]
    assert {b["xSpan"] for b in kpis} == {3}
    rate = canvas.source("kpi_failure_rate_last_21d")
    assert rate["data"][0]["value"] == 51.9 and rate["fields"][0]["format"] == "decimalFormat"


def test_follow_up_run_edits_the_same_canvas_below_existing_widgets():
    ws, first = build("ceo")
    bottom, count = first.bottom(), len(ws["state"]["pages"][0]["widgets"])
    canvas = compiler.Canvas(ws)  # next run
    wid = canvas.add({"kind": "donut", "source": "scenarios", "x": "scenario", "y": ["gross_profit_90d"], "title": "GP mix", "width": "third"})
    page = ws["state"]["pages"][0]
    assert len(page["widgets"]) == count + 1 and page["widgetLayout"][wid]["yTrack"] >= bottom
    assert page["widgets"][wid]["type"] == "donut-chart"


def test_replace_keeps_position_and_bad_specs_explain_themselves():
    ws, canvas = build("ceo")
    page = ws["state"]["pages"][0]
    chart = next(k for k, w in page["widgets"].items() if w["type"] == "bar-chart-grouped")
    box = dict(page["widgetLayout"][chart])
    new = canvas.add({"kind": "area", "source": "undercut", "x": "product", "y": ["gap_pct"], "title": "Gap"}, replace=chart)
    assert page["widgetLayout"][new] == box and chart not in page["widgets"]
    with pytest.raises(KeyError, match="Use one of"):
        canvas.add({"kind": "hologram", "source": "undercut", "title": "x"})
    with pytest.raises(KeyError, match="Fields"):
        canvas.add({"kind": "line", "source": "undercut", "x": "nope", "y": ["gap_pct"], "title": "x"})


def test_removing_a_widget_closes_the_gap():
    ws = compiler.new_workspace("c")
    canvas = compiler.Canvas(ws)
    canvas.put_source("t", [{"k": "a", "v": 1}, {"k": "b", "v": 2}])
    top, middle, bottom = (canvas.add({"kind": "column", "source": "t", "x": "k", "y": ["v"], "title": n, "width": "full"}) for n in "ABC")
    layout = ws["state"]["pages"][0]["widgetLayout"]
    assert layout[bottom]["yTrack"] == 22
    canvas.remove(middle)
    assert layout[top]["yTrack"] == 0 and layout[bottom]["yTrack"] == 11, "the widget below slides up into the gap"


def test_whole_number_kpis_show_without_decimals():
    ws = compiler.new_workspace("i")
    canvas = compiler.Canvas(ws)
    canvas.add_kpi("Models released", 24)
    canvas.add_kpi("Blend price", 0.03)
    assert canvas.source("kpi_models_released")["fields"][0]["format"] == "integerFormat"
    assert canvas.source("kpi_blend_price")["fields"][0]["format"] == "decimalFormat"
