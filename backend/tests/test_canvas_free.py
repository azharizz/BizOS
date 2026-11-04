"""Free design: every AG Studio widget type, any format, many tables, pages, a theme, and BizOS's own widgets
(plan graph, diagram, ideas map, summary, action) that sit anywhere on the canvas."""
import pytest

from bizos import compiler


@pytest.fixture
def canvas():
    ws = compiler.new_workspace("f1")
    c = compiler.Canvas(ws)
    c.put_source("sales", [{"region": "North", "product": "Tea", "month": "2026-01", "revenue": 120.5, "units": 10, "margin_pct": 31.2},
                           {"region": "South", "product": "Coffee", "month": "2026-02", "revenue": 80.0, "units": 7, "margin_pct": 22.4}])
    return c


def refs_ok(ws, widget):
    fields = {s["id"]: {f["id"] for f in s["fields"]} for s in ws["data"]["sources"]}
    for refs in widget["dataMapping"].values():
        for r in refs:
            src, f = r["id"].split(".", 1)
            assert f in fields[src], r


SPECS = [
    ({"kind": "stacked-bar", "x": "region", "y": ["revenue"], "series": "product"}, "bar-chart-stacked"),
    ({"kind": "column-100", "x": "region", "y": ["revenue"]}, "column-chart-stacked-100"),
    ({"kind": "stacked-area", "x": "month", "y": ["revenue"]}, "area-chart-stacked"),
    ({"kind": "scatter", "x": "units", "y": ["revenue"], "group": "product"}, "scatter-chart"),
    ({"kind": "bubble", "x": "units", "y": ["revenue"], "group": "product", "size": "margin_pct"}, "bubble-chart"),
    ({"kind": "radar-line", "x": "region", "y": ["revenue", "units"]}, "radar-line-chart"),
    ({"kind": "radial-bar", "x": "region", "y": ["revenue"]}, "radial-bar-chart"),
    ({"kind": "nightingale", "x": "region", "y": ["revenue"]}, "nightingale-chart"),
    ({"kind": "sunburst", "x": "region", "levels": ["product"], "y": ["revenue"]}, "sunburst-chart"),
    ({"kind": "pyramid", "x": "region", "y": ["units"]}, "pyramid-chart"),
    ({"kind": "pivot", "rows": ["region"], "columns": ["month"], "values": ["revenue"]}, "pivot-grid"),
    ({"kind": "gauge", "value": "margin_pct", "agg": "avg"}, "radial-gauge"),
    ({"kind": "linear-gauge", "value": "units"}, "linear-gauge"),
    ({"kind": "list-filter", "value": "region"}, "list-filter"),
    ({"kind": "date-filter", "value": "month"}, "date-filter"),
    ({"kind": "button-filter", "value": "product"}, "button-filter"),
    ({"kind": "stacked-combo", "x": "region", "y": ["revenue"], "y2": ["margin_pct"]}, "combo-chart-stacked-column-line"),
]


@pytest.mark.parametrize("spec,ag_type", SPECS)
def test_every_ag_studio_widget_type_maps_to_real_fields(canvas, spec, ag_type):
    wid = canvas.add({**spec, "source": "sales", "title": "T"})
    w = canvas.page["widgets"][wid]
    assert w["type"] == ag_type and w["format"]["title"]["text"] == "T"
    refs_ok(canvas.ws, w)


def test_scatter_and_bubble_explain_what_they_need(canvas):
    with pytest.raises(KeyError, match="group"):
        canvas.add({"kind": "scatter", "source": "sales", "x": "units", "y": ["revenue"], "title": "x"})
    with pytest.raises(KeyError, match="size"):
        canvas.add({"kind": "bubble", "source": "sales", "x": "units", "y": ["revenue"], "group": "product", "title": "x"})


def test_no_table_limit_and_any_size(canvas):
    a = canvas.add({"kind": "grid", "source": "sales", "title": "One"})
    b = canvas.add({"kind": "grid", "source": "sales", "title": "Two", "width": 5, "height": 20})
    box = canvas.page["widgetLayout"][b]
    assert a != b and box["xSpan"] == 5 and box["ySpan"] == 20


def test_format_passes_through_and_configure_deep_merges(canvas):
    wid = canvas.add({"kind": "line", "source": "sales", "x": "month", "y": ["revenue"], "title": "Trend",
                      "format": {"style": {"series": {"strokeWidth": 4}}}})
    canvas.configure(wid, {"style": {"series": {"marker": {"enabled": True}}}}, title="Revenue trend")
    f = canvas.page["widgets"][wid]["format"]
    assert f["style"]["series"] == {"strokeWidth": 4, "marker": {"enabled": True}} and f["title"]["text"] == "Revenue trend"
    with pytest.raises(ValueError, match="object"):
        canvas.configure(wid, "red")
    with pytest.raises(KeyError):
        canvas.configure("w999", {})


def test_text_and_image_blocks(canvas):
    # Seen live: AG Studio's text widget shows Markdown raw (**bold**) in a huge font: text is a BizOS Markdown widget.
    t = canvas.add({"kind": "text", "text": "## Why margins fell\nSupplier price rise.", "title": ""})
    i = canvas.add({"kind": "image", "src": "https://example.com/logo.png", "title": "Logo"})
    assert canvas.page["widgets"][t]["type"] == "bizos-text" and canvas.ws["content"][t]["text"].startswith("## Why")
    assert canvas.page["widgets"][i]["format"]["style"]["src"] == "https://example.com/logo.png"
    with pytest.raises(ValueError, match="http"):
        canvas.add({"kind": "image", "src": "javascript:alert(1)", "title": "x"})


def test_pages_hold_their_own_widgets(canvas):
    canvas.add({"kind": "kpi", "source": "sales", "value": "revenue", "title": "Revenue"})
    pid = canvas.add_page("Details")
    assert pid != "canvas" and canvas.page["id"] == pid and canvas.ws["state"]["selectedPageId"] == pid
    wid = canvas.add({"kind": "grid", "source": "sales", "title": "Rows"})
    assert canvas.page["widgetLayout"][wid]["yTrack"] == 0, "a new page starts at the top"
    assert [p["title"] for p in canvas.ws["pages"]] == ["Overview", "Details"]
    summary = canvas.summary()
    assert summary["pages"] == [{"id": "canvas", "title": "Overview"}, {"id": pid, "title": "Details"}]
    assert summary["widgets"][wid]["page"] == pid
    canvas.use_page("canvas")
    canvas.remove(wid)  # found on its own page
    assert compiler.widget_count(canvas.ws) == 1
    with pytest.raises(KeyError, match="pages"):
        canvas.use_page("nope")


def test_theme_accepts_colours_and_fonts_only(canvas):
    canvas.set_theme({"accent": "#4DFFB2", "background": "#0E0F0C", "palette": ["#4DFFB2", "#C9A227"], "font": "IBM Plex Mono", "radius": 8})
    assert canvas.ws["theme"]["accent"] == "#4DFFB2" and canvas.ws["theme"]["radius"] == 8
    with pytest.raises(ValueError, match="colour"):
        canvas.set_theme({"accent": "red; background:url(x)"})
    with pytest.raises(ValueError, match="font"):
        canvas.set_theme({"font": "x</style>"})


def test_bizos_widgets_sit_on_the_canvas_like_any_other(canvas):
    plan = canvas.add({"kind": "plan", "title": "How I worked"})
    diagram = canvas.add({"kind": "diagram", "title": "Reorder plan", "source_text": "gantt\n  title Reorder\n  section PO\n  Order :a1, 2026-11-05, 3d"})
    ideas = canvas.add({"kind": "ideas", "title": "What we can do", "center": "Margin is falling",
                        "ideas": [{"label": "Switch supplier", "effort": "medium", "risk": "act", "ask": "Compare suppliers for Product A"}]})
    summary = canvas.add({"kind": "summary", "title": "Brief"})
    action = canvas.add({"kind": "action", "title": "Approve", "action_id": "pp-1"})
    types = {canvas.page["widgets"][w]["type"] for w in (plan, diagram, ideas, summary, action)}
    assert types == {"bizos-plan", "bizos-diagram", "bizos-ideas", "bizos-summary", "bizos-action"}
    # Seen live: AG Studio drops format keys it doesn't know, so the content lives in the workspace, by widget id.
    assert canvas.ws["content"][diagram]["source"].startswith("gantt")
    assert canvas.ws["content"][ideas]["ideas"][0]["ask"] == "Compare suppliers for Product A"
    assert canvas.ws["content"][action] == {"actionId": "pp-1"}
    assert "style" not in canvas.page["widgets"][diagram].get("format", {})
    canvas.remove(diagram)
    assert diagram not in canvas.ws["content"]
    with pytest.raises(ValueError, match="diagram type"):
        canvas.add({"kind": "diagram", "title": "x", "source_text": "<script>alert(1)</script>"})
    with pytest.raises(ValueError, match="ideas"):
        canvas.add({"kind": "ideas", "title": "x", "center": "c", "ideas": []})
