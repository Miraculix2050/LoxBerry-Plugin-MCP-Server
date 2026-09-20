from types import SimpleNamespace

import pytest

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
    selected = frozenset({"datatype_consistency", "signal_usage_consistency"})

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
        frozenset({"project_connectivity"}),
    )

    assert result["summaries"]["project_connectivity"] == {"unconnected": 1, "ambiguous": 0}


@pytest.mark.parametrize(
    "analysis",
    ["naming_consistency", "datatype_consistency", "graph_outliers", "peer_group_consistency"],
)
def test_role_dependent_analyses_compute_reviewed_signal_usage(monkeypatch, analysis):
    observed = []
    original = project_analysis._usage

    def track_usage(*args):
        observed.append(args[0].key)
        return original(*args)

    monkeypatch.setattr(project_analysis, "_usage", track_usage)

    project_analysis.analyze_knx(
        _view(b'<P><C Type="EIBsensor" U="sensor" EibAddr="1/2/3"><Co U="out"/></C></P>'),
        frozenset({analysis}),
    )

    assert observed


def test_signal_usage_peer_outliers_compare_roles_without_the_usage_signature(monkeypatch):
    def usage_by_source(node, *_args):
        usage = (("minority", None),) if node.source_id == "s4" else (("majority", None),)
        return usage, False

    monkeypatch.setattr(project_analysis, "_usage", usage_by_source)
    project = (
        b"<P>"
        + b"".join(
            f'<C Type="EIBsensor" U="s{index}" EibAddr="1/2/3"><Co U="o{index}"/></C>'.encode()
            for index in range(5)
        )
        + b"</P>"
    )

    result = analyze_knx(_view(project), frozenset({"signal_usage_consistency"}))

    peer_outliers = [
        finding
        for finding in result["findings"]
        if finding["finding_type"] == "signal_usage_peer_outlier"
    ]
    assert len(peer_outliers) == 1
    assert peer_outliers[0]["support"] == {"count": 4, "total": 5, "ratio": 0.8}


def test_usage_analysis_stops_at_the_shared_traversal_budget(monkeypatch):
    monkeypatch.setattr(project_analysis, "_MAX_USAGE_NODES", 1)
    result = analyze_knx(
        _view(
            b'<P><C Type="EIBsensor" U="sensor" EibAddr="1/2/3"><Co U="source"/></C>'
            b'<C Type="EIBPush" U="push"><Co K="Tg" U="trigger"><In Input="source"/></Co>'
            b'<Co K="O" U="output"/></C></P>'
        ),
        frozenset({"signal_usage_consistency"}),
    )

    assert result["analysis_truncated"] is True
    assert result["truncation_reasons"] == ["max_usage_nodes"]
    assert result["coverage"]["reviewed_signal_usage"] == 0


def test_analysis_uses_runtime_evidence_only_for_a_unique_reverse_mapping():
    identifier = "a" * 32
    controls = (
        SimpleNamespace(
            uuid=identifier,
            action_uuid=None,
            subcontrols=(),
            name="First name",
            control_type="Switch",
            room_uuid=None,
            category_uuid=None,
        ),
        SimpleNamespace(
            uuid=identifier,
            action_uuid=None,
            subcontrols=(),
            name="Second name",
            control_type="Dimmer",
            room_uuid=None,
            category_uuid=None,
        ),
    )

    result = analyze_knx(
        _view(
            (
                f'<P><C Type="EIBsensor" U="{identifier}" EibAddr="1/2/3"><Co U="out"/></C></P>'
            ).encode(),
            controls,
        ),
        frozenset({"naming_consistency"}),
    )

    assert result["coverage"]["exact_runtime_mappings"] == 0
    assert result["coverage"]["named_endpoints"] == 0


def test_technology_architecture_does_not_reclassify_mapped_knx_endpoints_as_loxone():
    sensor_id, actor_id = "a" * 32, "b" * 32
    controls = tuple(
        SimpleNamespace(
            uuid=identifier,
            action_uuid=None,
            subcontrols=(),
            name="Mapped endpoint",
            control_type="Switch",
            room_uuid=None,
            category_uuid=None,
        )
        for identifier in (sensor_id, actor_id)
    )
    result = analyze_knx(
        _view(
            f'<P><C Type="EIBsensor" U="{sensor_id}" EibAddr="1/2/3"><Co U="source"/></C>'
            f'<C Type="EIBPush" U="push"><Co K="Tg" U="trigger"><In Input="source"/></Co>'
            f'<Co K="O" U="output"/></C><C Type="EIBactor" U="{actor_id}" EibAddr="1/2/4">'
            f'<Co U="input"><In Input="output"/></Co></C></P>'.encode(),
            controls,
        ),
        frozenset({"technology_architecture"}),
    )

    counts = result["summaries"]["technology_architecture"]["counts"]
    assert counts["knx_to_knx"] == 1
    assert "loxone_to_loxone" not in counts


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

    result = analyze_knx(view, frozenset({"technology_architecture"}))

    counts = result["summaries"]["technology_architecture"]["counts"]
    assert counts.get("knx_to_loxone", 0) == 0
    assert counts["knx_to_knx"] == 1
    sample = result["summaries"]["technology_architecture"]["samples"]["knx_to_knx"][0]
    endpoint_blocks = {
        node.knx.group_address.canonical: node.key
        for node in view.snapshot.graph.nodes
        if node.kind == "block" and node.knx and node.knx.group_address
    }
    assert sample["source_project_node_id"] == endpoint_blocks["1/2/3"]
    assert sample["target_project_node_id"] == endpoint_blocks["1/2/4"]


def test_technology_path_analysis_stops_inside_a_high_fan_out_expansion(monkeypatch):
    monkeypatch.setattr(project_analysis, "_MAX_VISITED_PER_START", 3)
    result = analyze_knx(
        _view(
            b'<P><C Type="EIBsensor" U="sensor" EibAddr="1/2/3"><Co U="source"/></C>'
            b'<C Type="EIBPush" U="push"><Co K="Tg" U="trigger"><In Input="source"/></Co>'
            b'<Co K="O" U="output"/></C></P>'
        ),
        frozenset({"technology_architecture"}),
    )

    assert result["analysis_truncated"] is True
    assert result["truncation_reasons"] == ["max_path_nodes"]


def test_technology_path_analysis_reports_a_depth_limit(monkeypatch):
    monkeypatch.setattr(project_analysis, "_MAX_PATH_DEPTH", 0)
    result = analyze_knx(
        _view(
            b'<P><C Type="EIBsensor" U="sensor" EibAddr="1/2/3"><Co U="source"/></C>'
            b'<C Type="EIBPush" U="push"><Co K="Tg" U="trigger"><In Input="source"/></Co>'
            b'<Co K="O" U="output"/></C></P>'
        ),
        frozenset({"technology_architecture"}),
    )

    assert result["analysis_truncated"] is True
    assert result["truncation_reasons"] == ["max_depth"]


def test_technology_path_analysis_stops_all_endpoint_expansion_at_the_global_path_limit(
    monkeypatch,
):
    monkeypatch.setattr(project_analysis, "_MAX_PATHS", 1)
    observed_descendants = []
    original = project_analysis._descendants

    def track_descendants(key, children):
        observed_descendants.append(key)
        return original(key, children)

    monkeypatch.setattr(project_analysis, "_descendants", track_descendants)
    view = _view(
        b'<P><C Type="EIBsensor" U="sensor" EibAddr="1/2/3"><Co U="source"/></C>'
        b'<C Type="EIBPush" U="push"><Co K="Tg" U="trigger"><In Input="source"/></Co>'
        b'<Co K="O" U="output"/></C><C Type="EIBactor" U="actor1" EibAddr="1/2/4">'
        b'<Co U="input1"><In Input="output"/></Co></C>'
        b'<C Type="EIBactor" U="actor2" EibAddr="1/2/5">'
        b'<Co U="input2"><In Input="output"/></Co></C></P>'
    )

    result = analyze_knx(view, frozenset({"technology_architecture"}))

    blocks = {
        node.source_id: node.key
        for node in view.snapshot.graph.nodes
        if node.kind == "block" and node.source_id in {"sensor", "actor1", "actor2"}
    }
    assert result["truncation_reasons"] == ["max_paths"]
    assert observed_descendants.count(blocks["sensor"]) == 1
    assert observed_descendants.count(blocks["actor1"]) == 0
    assert observed_descendants.count(blocks["actor2"]) == 0


def test_v2_uses_exact_runtime_evidence_for_naming_without_inventing_knx_semantics():
    identifiers = tuple(f"{index:032x}" for index in range(1, 7))
    project = (
        b"<P>"
        + b"".join(
            (
                f'<C Type="EIBsensor" U="{identifier}" EibAddr="1/2/{index}" '
                f'EIBType="1"><Co U="o{index}"/></C>'
            ).encode()
            for index, identifier in enumerate(identifiers, 1)
        )
        + b"</P>"
    )
    controls = tuple(
        SimpleNamespace(
            uuid=identifier,
            action_uuid=None,
            subcontrols=(),
            name=f"Zone {index}" if index < 6 else "Different",
            control_type="Switch",
            room_uuid=None,
            category_uuid=None,
        )
        for index, identifier in enumerate(identifiers, 1)
    )

    result = analyze_knx(_view(project, controls), frozenset({"naming_consistency"}))

    assert result["analysis_version"] == 2
    assert result["coverage"]["exact_runtime_mappings"] == 6
    assert result["coverage"]["reviewed_signal_usage"] == 0
    assert any(item["finding_type"] == "naming_deviation" for item in result["findings"])
    assert {item["code"] for item in result["limitations"]} >= {
        "normalized_dpt_unavailable",
        "semantic_domain_unavailable",
        "usage_semantics_unreviewed",
    }


def test_every_finding_type_honors_the_shared_result_limit(monkeypatch):
    monkeypatch.setattr(project_analysis, "_MAX_FINDINGS", 1)
    result = analyze_knx(
        _view(
            b'<P><C Type="EIBsensor" U="a" EibAddr="1/2/3" EIBType="1"><Co U="ao"/></C>'
            b'<C Type="EIBsensor" U="b" EibAddr="1/2/3" EIBType="5"><Co U="bo"/></C>'
            b'<C Type="EIBsensor" U="c" EibAddr="1/2/4" EIBType="1"><Co U="co"/></C>'
            b'<C Type="EIBsensor" U="d" EibAddr="1/2/4" EIBType="5"><Co U="do"/></C></P>'
        ),
        frozenset({"datatype_consistency"}),
    )

    assert len(result["findings"]) == 1
    assert result["analysis_truncated"] is True
    assert result["truncation_reasons"] == ["max_findings"]
