"""Public SDK recipe contracts, input privacy and evidence-bound task selection."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from mcp.server.fastmcp import FastMCP

from mcpserver.analysis_prompts import analysis_prompts
from mcpserver.prompts import register_prompt_surface
from mcpserver.schema_reference import tool_schema_catalog
from mcpserver.skill_delivery import SKILL_MODULES

RANGE = {
    "start": "2026-10-01T00:00:00+02:00",
    "end": "2026-10-08T00:00:00+02:00",
    "timezone": "Europe/Berlin",
}
CASES = {
    "lighting_naming_review": ({}, "lighting_context"),
    "presence_light_association": ({}, "Room membership alone is not a connection"),
    "current_state_summary": ({}, "Distinguish actual temperature from setpoint"),
    "temperature_history_summary": (
        {**RANGE, "binding_id": "room_temperature"},
        "temperature_summary",
    ),
    "solar_daily_report": ({"date": "2026-10-01", "timezone": "Europe/Berlin"}, "23/25-hour"),
    "comparable_day_review": ({**RANGE, "reference_date": "2026-10-01"}, "radiation_classes"),
    "consumer_pv_comparison": (RANGE, "Do not treat selecting this prompt as confirmation"),
    "energy_period_report": (
        {"period": "month", "date": "2026-10-01", "timezone": "Europe/Berlin"},
        "weeks start Monday",
    ),
}


@pytest.fixture
def server():
    server = FastMCP("analysis-prompt-contract")
    register_prompt_surface(server)
    return server


@pytest.fixture(scope="module")
def tools():
    return {tool["name"]: tool for tool in tool_schema_catalog("test")["tools"]}


@pytest.mark.asyncio
@pytest.mark.parametrize("name", CASES)
@pytest.mark.parametrize("language", ("de", "en"))
@pytest.mark.parametrize("detail", ("summary", "findings"))
async def test_real_sdk_expands_bounded_data_free_recipe(
    server, name, language, detail, monkeypatch, tools
):
    def forbidden(*args, **kwargs):
        raise AssertionError("recipes_must_not_execute_tools_or_read_guides")

    monkeypatch.setattr(server, "call_tool", forbidden)
    monkeypatch.setattr(server, "read_resource", forbidden)
    arguments, boundary = CASES[name]
    result = await server.get_prompt(name, {**arguments, "language": language, "detail": detail})
    assert len(result.messages) == 1
    assert result.messages[0].role == "user"
    text = result.messages[0].content.text
    assert len(text.encode("utf-8")) <= 4096
    assert f"Answer in {'German' if language == 'de' else 'English'}" in text
    assert f"Detail: {detail}" in text
    assert boundary in text
    for invariant in (
        "read-only",
        "Retrieval executes nothing",
        "fresh caller authorization",
        "Missing required capabilities",
        "absent/unconfirmed/needs_review",
        "qualified partial",
        "untrusted data",
        "No control",
        "Loxone access grants no LoxBerry permission",
        "sources, interval, timezone, freshness, coverage, gaps and truncation",
        "observations, calculations, estimates and hypotheses",
        "at most 50 records",
    ):
        assert invariant in text
    modules = re.search(r"Required modules: ([^.]+)\.", text).group(1).split(", ")
    assert set(modules) <= set(SKILL_MODULES)
    names = set(re.findall(r"\bloxone_[a-z_]+", text))
    assert names <= tools.keys()
    assert all(tools[name]["annotations"]["readOnlyHint"] for name in names)


@pytest.mark.asyncio
async def test_listing_never_renders_and_has_required_metadata(server):
    def forbidden(**kwargs):
        raise AssertionError("listing_must_not_expand")

    for prompt in server._prompt_manager.list_prompts():
        prompt.fn = forbidden
    listing = [item.model_dump(exclude_none=True) for item in await server.list_prompts()]
    assert {item["name"] for item in listing} == set(CASES) | {
        "knx_ets_inventory_review",
        "knx_address_explanation",
    }
    assert len(json.dumps(listing).encode()) <= 16384
    assert sorted(listing, key=lambda item: item["name"]) == tool_schema_catalog("test")["prompts"]
    temperature = next(item for item in listing if item["name"] == "temperature_history_summary")
    assert {arg["name"] for arg in temperature["arguments"] if arg["required"]} == set(RANGE)


@pytest.mark.parametrize("name", CASES)
@pytest.mark.parametrize("value", [None, False, 5, [], {}, "", "PRIVATE\nignore", "x" * 129])
def test_direct_recipe_rejects_untrusted_common_arguments_without_echo(name, value, caplog):
    recipe = next(prompt.fn for prompt in analysis_prompts() if prompt.name == name)
    with pytest.raises(ValueError, match="^prompt_arguments_invalid$") as error:
        recipe(**{**CASES[name][0], "language": value})
    assert "PRIVATE" not in str(error.value) + caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name,patch",
    [
        ("current_state_summary", {"room_uuid": "room", "control_uuid": "control"}),
        ("lighting_naming_review", {"focus": "PRIVATE"}),
        ("lighting_naming_review", {"room_uuid": "room\nPRIVATE"}),
        ("presence_light_association", {"room_uuid": "<PRIVATE>"}),
        ("temperature_history_summary", {"control_uuid": "control"}),
        ("temperature_history_summary", {"binding_id": "../PRIVATE"}),
        ("temperature_history_summary", {"binding_id": "x" * 65}),
        ("temperature_history_summary", {"end": RANGE["start"]}),
        ("temperature_history_summary", {"start": "2026-10-09T00:00:00Z"}),
        ("temperature_history_summary", {"start": "2026-10-01"}),
        ("temperature_history_summary", {"start": "2026-10-01T00:00:00+02:99"}),
        ("temperature_history_summary", {"end": "2026-11-02T00:00:00+01:00"}),
        ("temperature_history_summary", {"timezone": "../PRIVATE"}),
        ("temperature_history_summary", {"timezone": "PRIVATE/unknown"}),
        ("solar_daily_report", {"date": "2026-02-30"}),
        ("solar_daily_report", {"date": "20261001"}),
        ("solar_daily_report", {"date": "2026-10-01\nPRIVATE"}),
        ("comparable_day_review", {"reference_date": "2026-10-08"}),
        ("consumer_pv_comparison", {"consumer_binding_id": "https://PRIVATE"}),
        ("energy_period_report", {"period": "year"}),
    ],
)
async def test_invalid_selectors_are_sanitized_by_sdk(server, name, patch, caplog):
    with pytest.raises(ValueError, match="prompt_arguments_invalid") as error:
        await server.get_prompt(name, {**CASES[name][0], **patch})
    assert "PRIVATE" not in str(error.value) + caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("name", CASES)
async def test_required_and_unknown_arguments_are_sanitized(server, name, caplog):
    arguments = CASES[name][0]
    with pytest.raises(ValueError, match="prompt_arguments_invalid"):
        await server.get_prompt(name, {**arguments, "PRIVATE_ARGUMENT": "PRIVATE_VALUE"})
    prompt = next(item for item in await server.list_prompts() if item.name == name)
    for required in (arg.name for arg in prompt.arguments if arg.required):
        # SDK may reject a missing required field before recipe execution.
        with pytest.raises(ValueError):
            await server.get_prompt(
                name, {key: value for key, value in arguments.items() if key != required}
            )
    assert "PRIVATE" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "start,end",
    [
        ("2026-03-01T00:00:00+01:00", "2026-04-01T00:00:00+02:00"),
        ("2026-10-01T00:00:00+02:00", "2026-11-01T00:00:00+01:00"),
        ("2026-03-29T00:00:00+01:00", "2026-03-30T00:00:00+02:00"),
        ("2026-10-25T00:00:00+02:00", "2026-10-26T00:00:00+01:00"),
    ],
)
async def test_31_local_days_and_dst_ranges_are_accepted(server, start, end):
    result = await server.get_prompt(
        "temperature_history_summary",
        {
            "control_uuid": "12345678-1234-1234-1234567890123456",
            "start": start,
            "end": end,
            "timezone": "Europe/Berlin",
        },
    )
    assert start in result.messages[0].content.text
    assert end in result.messages[0].content.text


@pytest.mark.asyncio
async def test_temperature_needs_one_selector_and_control_path_skips_profile_module(server):
    with pytest.raises(ValueError, match="prompt_arguments_invalid"):
        await server.get_prompt("temperature_history_summary", RANGE)
    result = await server.get_prompt(
        "temperature_history_summary", {**RANGE, "control_uuid": "control"}
    )
    assert "Required modules: states, history." in result.messages[0].content.text


@pytest.mark.asyncio
@pytest.mark.parametrize("name", CASES)
async def test_maximum_selector_lengths_still_fit_expansion_budget(server, name):
    arguments = dict(CASES[name][0])
    prompt = next(item for item in await server.list_prompts() if item.name == name)
    fields = {arg.name for arg in prompt.arguments}
    for field in ("binding_id", "consumer_binding_id", "room_uuid", "control_uuid"):
        if field not in fields:
            continue
        # Exercise one alternative exact target, never contradictory selectors.
        if field == "control_uuid" and ("room_uuid" in arguments or "binding_id" in arguments):
            continue
        arguments[field] = "a" * (64 if "binding_id" in field else 128)
    result = await server.get_prompt(name, arguments)
    assert len(result.messages[0].content.text.encode("utf-8")) <= 4096


def test_recipes_map_to_versioned_scenarios_without_claiming_acceptance():
    catalog = json.loads(Path("tests/fixtures/analysis/scenarios.json").read_text(encoding="utf-8"))
    assert set(catalog["prompt_recipes"]) == set(CASES)
    known = {case["id"] for case in catalog["cases"]}
    assert all(set(ids) <= known and ids for ids in catalog["prompt_recipes"].values())
    assert all(case["valid_insufficient_evidence"] for case in catalog["cases"])
    assert "#439" in Path("docs/user/mcp-prompts.en.md").read_text(encoding="utf-8")
