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
    assert sum(r["status"] == "missing_code" for r in records) == 2
    assert sum(r["status"] == "mapped_object_type" for r in records) == 2


@pytest.mark.parametrize("code", ["0", "7", "11", "12", "14", "99", "04", ""])
def test_unobserved_codes_remain_unresolved(code: str) -> None:
    result = inspect_config_knx(config(f'<C Type="EIBactor" EIBType="{code}"/>'))
    assert result["records"][0]["eis"] is None


@pytest.mark.parametrize(
    "body",
    [
        '<C Type="EIBsensor" EIBType="6" Title="Jalousie EIS7 (DPT1)"/>',
        '<C Type="EIBactor" EIBType="13"/>',
        '<C Type="EIBtextactor" EIBType="4"/>',
        '<C Type="EIBactor" EIBType="4" EIBType="5"/>',
        '<C Type="EIBsensor" Title="EIS5 DPT9"/>',
    ],
)
def test_no_inference_from_names_conflicts_or_other_families(body: str) -> None:
    assert inspect_config_knx(config(body))["records"][0]["eis"] is None


def test_version_and_source_boundary() -> None:
    body = '<C Type="EIBactor" EIBType="4"/>'
    for data in (
        config(body, "other"),
        config(body).replace(b'Version="274"', b'Version="275"'),
        config(body + '<C Type="Document" ConfigVersion="other"/>'),
    ):
        result = inspect_config_knx(data)
        assert result["version_verified"] is False
        assert result["records"][0]["status"] == "unsupported_version"
    with pytest.raises(ProjectError):
        inspect_config_knx(b"\xee\xcc\xbb\xaa")
    with pytest.raises(ProjectError):
        inspect_config_knx(b"<Root/>")
    with pytest.raises(ProjectError):
        inspect_config_knx(b'<!DOCTYPE x [<!ENTITY y "z">]><ControlList/>')


def test_miniserver_classifier_keeps_raw_code() -> None:
    element = parse_project(b'<C Type="EIBactor" EibAddr="1/2/3" EIBType="4"/>').elements[0]
    semantics = classify_knx(element)
    assert semantics is not None
    assert semantics.datatype is not None
    assert semantics.datatype.source_value == "4"
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
