from mcpserver.loxone.models import Control, LoxoneIdentity, LoxoneStructure
from mcpserver.loxone.runtime import normalize_control_history_entries
from tools.measure_history_latency import first_visible_history_control


def test_probe_finds_visible_nested_history_control() -> None:
    child = Control("child", "Nested", "Switch", None, None, "action", (), has_history=True)
    root = Control("root", "Parent", "Switch", None, None, None, (), subcontrols=(child,))
    hidden = Control("hidden", "Hidden", "Switch", None, None, "hidden", (), has_history=True)
    structure = LoxoneStructure(
        LoxoneIdentity("reader", "serial"),
        "current",
        (),
        (),
        (root,),
        hidden_controls=(hidden,),
    )

    assert first_visible_history_control(structure) is child


def test_probe_uses_runtime_history_normalization() -> None:
    raw = [
        {"ts": 123, "what": "valid", "trigger": "", "triggerType": "", "impacts": []},
        {"ts": True, "what": "invalid"},
    ]

    assert len(normalize_control_history_entries(raw)) == 1
