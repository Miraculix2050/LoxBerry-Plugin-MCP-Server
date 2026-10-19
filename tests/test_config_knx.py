"""Config-source evidence must never silently become Miniserver semantics."""

import json
from pathlib import Path

import pytest

from mcpserver.loxone.project.config_knx import inspect_config_knx, main
from mcpserver.loxone.project.models import ProjectError
from mcpserver.loxone.project.parser import parse_project
from mcpserver.loxone.project.semantics import classify_knx

FIXTURE = Path(__file__).parent / "fixtures/project/config-knx-datatypes.xml"


def config(body: str, version: str = "17020828") -> bytes:
    return (
        f'<ControlList Version="274"><C Type="Document" ConfigVersion="{version}"/>'
        f"{body}</ControlList>"
    ).encode()


def test_observed_config_fixture() -> None:
    result = inspect_config_knx(FIXTURE.read_bytes())
    assert result["version_verified"] is True
    records = result["records"]
    assert isinstance(records, list)
    mapped = {
        record["source_value"]: (record["eis"], record["dpt_main_types"])
        for record in records
        if record["status"] == "mapped_explicit_code"
    }
    assert mapped == {
        "1": (2, (3,)),
        "2": (3, (10,)),
        "3": (4, (11,)),
        "4": (5, (9,)),
        "5": (6, (5,)),
        "6": (7, (1,)),
        "8": (9, (14,)),
        "9": (10, (7, 8)),
        "10": (11, (12, 13)),
        "13": (14, (5, 6)),
    }
    defaults = [r for r in records if r["status"] == "mapped_implicit_config_default"]
    assert {r["source_type"] for r in defaults} == {"EIBsensor", "EIBactor"}
    assert len(defaults) == 2
    assert all(r["source_value"] is None and r["eis"] is None for r in defaults)
    assert all(r["dpt_main_types"] == (1,) for r in defaults)
    assert sum(r["status"] == "mapped_object_type" for r in records) == 2


@pytest.mark.parametrize("source_type", ["EIBsensor", "EIBactor"])
@pytest.mark.parametrize("code", ["0", "7", "11", "12", "14", "99", "04", "", " "])
def test_unobserved_codes_remain_unresolved(source_type: str, code: str) -> None:
    result = inspect_config_knx(config(f'<C Type="{source_type}" EIBType="{code}"/>'))
    assert result["records"][0]["eis"] is None
    assert result["records"][0]["dpt_main_types"] == ()
    assert result["records"][0]["status"] == "unresolved"


@pytest.mark.parametrize("source_type", ["EIBsensor", "EIBactor"])
def test_absent_code_uses_dpt1_default_without_eis(source_type: str) -> None:
    record = inspect_config_knx(config(f'<C Type="{source_type}" Title="EIS5 DPT9"/>'))["records"][
        0
    ]
    assert record["status"] == "mapped_implicit_config_default"
    assert record["source_value"] is None
    assert record["eis"] is None
    assert record["dpt_main_types"] == (1,)


def test_eis7_keeps_explicit_provenance() -> None:
    records = inspect_config_knx(config('<C Type="EIBactor"/><C Type="EIBactor" EIBType="6"/>'))[
        "records"
    ]
    assert records[0]["dpt_main_types"] == records[1]["dpt_main_types"] == (1,)
    assert records[0]["eis"] is None
    assert records[1]["eis"] == 7
    assert records[1]["source_value"] == "6"
    assert records[1]["status"] == "mapped_explicit_code"


@pytest.mark.parametrize(
    "body",
    [
        '<C Type="EIBsensor" EIBType="6" Title="Jalousie EIS7 (DPT1)"/>',
        '<C Type="EIBactor" EIBType="13"/>',
        '<C Type="EIBtextactor" EIBType="4"/>',
        '<C Type="EIBactor" EIBType="4" EIBType="5"/>',
        '<C Type="EIBsensor" EIBType="4" EIBType="5"/>',
    ],
)
def test_no_inference_from_names_conflicts_or_other_families(body: str) -> None:
    record = inspect_config_knx(config(body))["records"][0]
    assert record["eis"] is None
    assert record["dpt_main_types"] == ()
    assert record["status"] == "unresolved"


def test_default_excludes_extended_families() -> None:
    result = inspect_config_knx(config('<C Type="EIBextsensor"/><C Type="EIBextactor"/>'))
    assert result["records"] == []


def test_version_and_source_boundary() -> None:
    body = '<C Type="EIBactor" EIBType="4"/><C Type="EIBsensor"/><C Type="EIBactor"/>'
    for data in (
        config(body, "other"),
        config(body).replace(b'Version="274"', b'Version="275"'),
        config(body + '<C Type="Document" ConfigVersion="other"/>'),
        config(body + '<C Type="Document" ConfigVersion="17020828"/>'),
        config(body).replace(b'Version="274"', b'Version="274" Version="274"'),
        config(body).replace(
            b'ConfigVersion="17020828"',
            b'ConfigVersion="17020828" ConfigVersion="17020828"',
        ),
    ):
        result = inspect_config_knx(data)
        assert result["version_verified"] is False
        assert all(r["status"] == "unsupported_version" for r in result["records"])
        assert all(r["dpt_main_types"] == () for r in result["records"])
    with pytest.raises(ProjectError):
        inspect_config_knx(b"\xee\xcc\xbb\xaa")
    with pytest.raises(ProjectError):
        inspect_config_knx(b"<Root/>")
    with pytest.raises(ProjectError):
        inspect_config_knx(b'<!DOCTYPE x [<!ENTITY y "z">]><ControlList/>')


@pytest.mark.parametrize("source_type", ["EIBsensor", "EIBactor"])
@pytest.mark.parametrize("code", [None, "4", "6"])
def test_miniserver_classifier_keeps_raw_code(source_type: str, code: str | None) -> None:
    attribute = "" if code is None else f' EIBType="{code}"'
    element = parse_project(
        f'<C Type="{source_type}" EibAddr="1/2/3"{attribute}/>'.encode()
    ).elements[0]
    semantics = classify_knx(element)
    assert semantics is not None
    if code is None:
        assert semantics.datatype is None
        return
    assert semantics.datatype is not None
    assert semantics.datatype.source_value == code
    assert semantics.datatype.normalized_code is None
    assert semantics.datatype.system == "unknown"


def test_cli_omits_private_attributes(monkeypatch, capsys, tmp_path) -> None:
    path = tmp_path / "sample.Loxone"
    path.write_bytes(config('<C Type="EIBactor" EIBType="4" Title="private-name"/>'))
    monkeypatch.setattr("sys.argv", ["config_knx", str(path)])
    assert main() == 0
    output = capsys.readouterr().out
    assert "private-name" not in output
    assert json.loads(output)["records"][0]["eis"] == 5
