"""Paired KNX format evidence through the real LoxCC snapshot boundary."""

import struct
import zlib
from types import SimpleNamespace

import pytest

from mcpserver.loxone.project.analysis import analyze_knx
from mcpserver.loxone.project.graph import build_snapshot
from mcpserver.loxone.project.knx_datatypes import verified_knx_format
from mcpserver.loxone.project.mapping import ProjectView, map_runtime
from mcpserver.loxone.project.models import ProjectBundle, ProjectFile
from mcpserver.loxone.project.parser import parse_project
from mcpserver.loxone.project.query import ProjectQuery
from mcpserver.loxone.project.worker import process_project
from mcpserver.tools import ProjectKnxData


@pytest.mark.parametrize(
    "body,expected",
    [
        ("", True),
        ('<C Type="Switch"/>', True),
        ('<C Type="Switch" Type="Switch"/>', True),
        ('<C Type="Document" Type="Switch"/>', True),
        ('<C Type="Switch" Type="Document"/>', True),
        ('<C Type="Document"/>', False),
        ('<C Type="Document" Type="Document"/>', False),
        ('<X Type="Document"/>', False),
        ('<C ConfigVersion="17020828"/>', False),
        ('<C Type="Switch" ConfigVersion="17020828"/>', False),
        ('<X Type="Document" ConfigVersion="17020828"/>', False),
        ('<C Type="Document" Type="Switch" ConfigVersion="17020828"/>', False),
    ],
)
def test_format_boundary_rejects_additional_documents_and_foreign_versions(body, expected):
    assert verified_knx_format(parse_project(config(body))) is expected


def config(body: str, version: str = "17020828") -> bytes:
    return (
        '<ControlList Version="274"><C Type="Document" ConfigVersion="'
        + version
        + '"/>'
        + body
        + "</ControlList>"
    ).encode()


def packed(data: bytes) -> bytes:
    extra = len(data) - 15
    block = b"\xf0" + bytes([255]) * (extra // 255) + bytes([extra % 255]) + data
    return struct.pack("<IIII", 0xAABBCCEE, len(block), len(data), zlib.crc32(data)) + block


def query(*parts: bytes) -> ProjectQuery:
    snapshot = build_snapshot(
        ProjectBundle(
            "test",
            tuple(ProjectFile(f"part-{i}.LoxCC", packed(data)) for i, data in enumerate(parts)),
            1,
        )
    )
    return ProjectQuery(
        ProjectView(
            snapshot, map_runtime(snapshot, SimpleNamespace(last_modified="v", controls=()))
        ),
        {},
    )


def describe(data: bytes):
    q = query(data)
    node = next(n for n in q.view.snapshot.graph.nodes if n.knx is not None)
    return q.describe(node, limit=10)["knx"]


@pytest.mark.parametrize(
    "kind,code,eis,mains",
    [
        ("EIBsensor", "4", 5, [9]),
        ("EIBsensor", "5", 6, [5]),
        ("EIBsensor", "8", 9, [14]),
        ("EIBsensor", "9", 10, [7, 8]),
        ("EIBactor", "1", 2, [3]),
        ("EIBactor", "2", 3, [10]),
        ("EIBactor", "3", 4, [11]),
        ("EIBactor", "4", 5, [9]),
        ("EIBactor", "5", 6, [5]),
        ("EIBactor", "6", 7, [1]),
    ],
)
def test_paired_explicit_codes_through_snapshot(kind, code, eis, mains):
    detail = describe(config(f'<C Type="{kind}" U="x" EIBType="{code}" EibAddr="1/2/3"/>'))
    typed = ProjectKnxData.model_validate(detail)
    assert typed.datatype.source_value == code
    assert typed.datatype.system == "dpt_main_type"
    assert typed.datatype.normalized_code == (str(mains[0]) if len(mains) == 1 else None)
    evidence = typed.normalized_dpt_evidence
    assert evidence.dpt_main_types == mains and evidence.eis == eis
    assert evidence.subtype is None and evidence.compatibility == "not_established"
    assert evidence.source_format == "miniserver_loxcc"


@pytest.mark.parametrize(
    "kind,eis,mains,status",
    [
        ("EIBsensor", None, [1], "mapped_implicit_config_default"),
        ("EIBactor", None, [1], "mapped_implicit_config_default"),
        ("EIBtextsensor", 15, [16], "mapped_object_type"),
        ("EIBtextactor", 15, [16], "mapped_object_type"),
    ],
)
def test_absent_codes_preserve_absence(kind, eis, mains, status):
    detail = describe(config(f'<C Type="{kind}" U="x" EibAddr="1/2/3"/>'))
    assert detail["datatype"] is None
    evidence = detail["normalized_dpt_evidence"]
    assert evidence["eis"] == eis and evidence["dpt_main_types"] == mains
    assert evidence["status"] == status


@pytest.mark.parametrize(
    "attrs",
    [
        'Type="EIBsensor" EIBType="2"',
        'Type="EIBactor" EIBType="8"',
        'Type="EIBactor" EIBType="0"',
        'Type="EIBactor" EIBType=""',
        'Type="EIBactor" EIBType=" "',
        'Type="EIBactor" EIBType="4" EIBType="5"',
        'Type="EIBactor" EIBType="4" EIBType="4"',
        'Type="EIBsensor" Type="EIBsensor"',
        'Type="EIBextsensor"',
    ],
)
def test_unpaired_and_ambiguous_values_stay_unresolved(attrs):
    detail = describe(config(f'<C {attrs} U="x" EibAddr="1/2/3"/>'))
    assert detail["normalized_dpt_evidence"] is None
    assert detail["datatype"] is None or detail["datatype"]["system"] == "unknown"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda x: x.replace(b'Version="274"', b'Version="275"'),
        lambda x: x.replace(b'Version="274"', b'Version="274" Version="274"'),
        lambda x: x.replace(b'ConfigVersion="17020828"', b'ConfigVersion="other"'),
        lambda x: x.replace(
            b'ConfigVersion="17020828"', b'ConfigVersion="17020828" ConfigVersion="17020828"'
        ),
        lambda x: x.replace(
            b"</ControlList>", b'<C Type="Document" ConfigVersion="17020828"/></ControlList>'
        ),
    ],
)
@pytest.mark.parametrize("attribute", ["", ' EIBType="4"'])
def test_version_guards_cover_defaults_and_codes(mutation, attribute):
    data = config(f'<C Type="EIBsensor"{attribute} U="x" EibAddr="1/2/3"/>')
    assert describe(mutation(data))["normalized_dpt_evidence"] is None


def test_version_is_part_local_and_analysis_exposes_remaining_gap():
    body = '<C Type="EIBsensor" EIBType="4" U="x" EibAddr="1/2/3"/>'
    q = query(config(body), config(body, "other"))
    nodes = [n for n in q.view.snapshot.graph.nodes if n.knx is not None]
    assert sum(n.knx.normalized_dpt_evidence is not None for n in nodes) == 1
    assert q.view.snapshot.model_version == 15
    result = analyze_knx(q.view, analyses={"datatype_consistency"})
    assert (
        next(x["count"] for x in result["limitations"] if x["code"] == "normalized_dpt_unavailable")
        == 1
    )


@pytest.mark.asyncio
async def test_isolated_worker_preserves_evidence():
    data = packed(config('<C Type="EIBsensor" U="x" EibAddr="1/2/3" EIBType="4"/>'))
    snapshot, _ = await process_project(data)
    node = next(n for n in snapshot.graph.nodes if n.knx is not None)
    assert node.knx.normalized_dpt_evidence.dpt_main_types == (9,)
    assert snapshot.model_version == 15
