from types import SimpleNamespace

import mcpserver.loxone.project.analysis as project_analysis
from mcpserver.loxone.project.analysis import analyze_knx
from mcpserver.loxone.project.graph import ProjectPartSummary, ProjectSnapshot, build_graph
from mcpserver.loxone.project.mapping import ProjectView, map_runtime
from mcpserver.loxone.project.parser import parse_project


def _view(data: bytes, controls: tuple[SimpleNamespace, ...] = ()) -> ProjectView:
    snapshot = ProjectSnapshot(
        "project",
        3,
        (ProjectPartSummary("p", 1, ()),),
        build_graph((("p", parse_project(data)),)),
    )
    return ProjectView(
        snapshot, map_runtime(snapshot, SimpleNamespace(last_modified="v", controls=controls))
    )


def test_analysis_reports_project_local_datatype_and_usage_facts_deterministically():
    view = _view(
        b'<P><C Type="EIBsensor" U="a" EibAddr="1/2/3" EIBType="1"><Co U="ao"/></C>'
        b'<C Type="EIBsensor" U="b" EibAddr="1/2/3" EIBType="5"><Co U="bo"/></C>'
        b'<C Type="EIBsensor" U="c" EibAddr="1/2/4"><Co K="AQ" U="co"/></C>'
        b'<C Type="EIBPush" U="push"><Co K="Tg" U="trigger"><In Input="co"/></Co>'
        b'<Co K="O" U="out"/></C></P>'
    )
    selected = frozenset({"raw_datatype_reuse", "signal_usage"})

    first = analyze_knx(view, selected)
    second = analyze_knx(view, selected)

    assert first == second
    conflict = next(
        item for item in first["findings"] if item["finding_type"] == "raw_datatype_conflict"
    )
    assert conflict["group_address"] == "1/2/3"
    assert conflict["raw_datatypes"] == ["1", "5"]
    assert all("incompatible" not in str(item) for item in first["findings"])


def test_analysis_only_reports_address_deviations_for_strong_evidenced_peer_groups():
    nodes = b"".join(
        (
            f'<C Type="EIBsensor" U="s{i}" EibAddr="1/2/{i}" EIBType="1">'
            f'<Co K="AQ" U="co{i}"/></C><C Type="EIBPush" U="p{i}">'
            f'<Co K="Tg" U="t{i}"><In Input="co{i}"/></Co><Co K="O" U="o{i}"/></C>'
        ).encode()
        for i in range(5)
    )
    nodes += (
        b'<C Type="EIBsensor" U="outlier" EibAddr="2/2/9" EIBType="1">'
        b'<Co K="AQ" U="co9"/></C><C Type="EIBPush" U="p9">'
        b'<Co K="Tg" U="t9"><In Input="co9"/></Co><Co K="O" U="o9"/></C>'
    )

    result = analyze_knx(_view(b"<P>" + nodes + b"</P>"), frozenset({"address_patterns"}))

    deviations = [
        item for item in result["findings"] if item["finding_type"] == "address_pattern_deviation"
    ]
    assert {
        (item["prefix_level"], tuple(item["dominant_prefix"]), tuple(item["deviation_prefix"]))
        for item in deviations
    } == {
        (1, (1,), (2,)),
        (2, (1, 2), (2, 2)),
    }


def test_analysis_scopes_unconnected_evidence_to_the_project_graph():
    result = analyze_knx(
        _view(b'<P><C Type="EIBsensor" U="isolated" EibAddr="1/2/3"><Co U="co"/></C></P>'),
        frozenset({"project_connectivity"}),
    )

    finding = result["findings"][0]
    assert finding["finding_type"] == "no_project_signal_relationship"
    assert "unused" not in str(finding)


def test_analysis_skips_signal_usage_when_the_selected_analysis_does_not_need_it(monkeypatch):
    def usage_should_not_run(*_args):
        raise AssertionError("signal usage must not be computed")

    monkeypatch.setattr(project_analysis, "_usage", usage_should_not_run)

    result = project_analysis.analyze_knx(
        _view(b'<P><C Type="EIBsensor" U="sensor" EibAddr="1/2/3"><Co U="out"/></C></P>'),
        frozenset({"raw_datatype_reuse"}),
    )

    assert result["summaries"]["raw_datatype_reuse"] == {"conflicts": 0}


def test_technology_path_analysis_never_reverses_at_a_logic_input_merge():
    loxone_id = "a" * 32
    view = _view(
        f'<P><C Type="EIBsensor" U="sensor" EibAddr="1/2/3"><Co U="sensor-out"/></C>'
        f'<C Type="DigitalInput" U="{loxone_id}"><Co U="loxone-out"/></C>'
        f'<C Type="EIBPush" U="push"><Co K="Tg" U="trigger"><In Input="sensor-out"/></Co>'
        f'<Co K="On" U="on"><In Input="loxone-out"/></Co><Co K="O" U="output"/></C>'
        f'<C Type="EIBactor" U="actor" EibAddr="1/2/4"><Co U="actor-in"><In Input="output"/>'
        f"</Co></C></P>".encode(),
        (SimpleNamespace(uuid=loxone_id, action_uuid=None, subcontrols=()),),
    )

    result = analyze_knx(view, frozenset({"technology_paths"}))

    counts = result["summaries"]["technology_paths"]["counts"]
    assert counts.get("knx_to_loxone", 0) == 0
    assert counts["knx_to_knx"] == 1
    sample = result["summaries"]["technology_paths"]["samples"]["knx_to_knx"][0]
    endpoint_blocks = {
        node.knx.group_address.canonical: node.key
        for node in view.snapshot.graph.nodes
        if node.kind == "block" and node.knx and node.knx.group_address
    }
    assert sample["source_project_node_id"] == endpoint_blocks["1/2/3"]
    assert sample["target_project_node_id"] == endpoint_blocks["1/2/4"]
