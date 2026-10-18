"""Unrelated helpers defer solar models without bypassing source validation."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from mcpserver.config import ConfigError, PluginConfig


@pytest.mark.parametrize("sources", [None, {}, "", False, [None], [{}], [{}] * 17])
def test_disabled_solar_still_validates_all_source_values(sources):
    document = PluginConfig.defaults().to_document()
    document["event_history"]["solar_sources"] = sources
    with pytest.raises(ConfigError, match="event_history.solar_sources is unsupported"):
        PluginConfig.from_document(document)


def test_empty_config_helpers_defer_models_and_configured_sources_keep_contracts():
    root = Path(__file__).resolve().parents[1]
    code = """
import sys
from mcpserver.config import ConfigError, PluginConfig
import mcpserver.knx.admin
base = PluginConfig.defaults().to_document()
parsed = PluginConfig.from_document(base)
assert parsed.solar_history_sources == ()
assert 'mcpserver.solar_recording' not in sys.modules
assert 'mcpserver.solar_history' not in sys.modules
assert 'pydantic' not in sys.modules

# Even disabled recording must validate and retain configured sources.
source = dict(control_uuid='12345678-1234-1234-1234567890123456',
    state_uuid='12345678-1234-1234-1234567890123457', kind='irradiance',
    unit='W/m²', source_reference='explicit local source', confirmed=True)
base['event_history']['solar_sources'] = [source]
parsed = PluginConfig.from_document(base)
assert len(parsed.solar_history_sources) == 1
assert parsed.to_document()['event_history']['solar_sources'][0]['confirmed'] is True
assert 'mcpserver.solar_history' not in sys.modules
base['event_history']['solar_sources'] = [source, source]
try:
    PluginConfig.from_document(base)
except ConfigError:
    pass
else:
    raise AssertionError('duplicate disabled sources accepted')
from mcpserver.solar_recording import observations
assert observations([(1.0, {'value': 2.0})])[0].value == 2.0
"""
    subprocess.run(
        [sys.executable, "-c", code],
        cwd=root,
        env={**os.environ, "PYTHONPATH": str(root / "src")},
        capture_output=True,
        text=True,
        check=True,
    )
