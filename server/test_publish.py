"""Tests for the publish pipeline lint + preset writer (run: pytest server/test_publish.py)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from publish_profiles import (  # noqa: E402
    PUBLISH_PROFILES,
    lint_project,
    parse_project_godot,
)
from export_runner import build_preset_block, ensure_export_preset  # noqa: E402

# A trimmed-down replica of a godogen template's project.godot: two actions
# with full keyboard+joypad(+D-pad) bindings, one keyboard/mouse-only action.
GOOD_PROJECT = '''config_version=5

[application]

config/name="Fixture"
run/main_scene="res://scenes/main.tscn"

[display]

window/size/viewport_width=1152
window/size/viewport_height=648

[input]

move_up={
"deadzone": 0.2,
"events": [Object(InputEventKey,"physical_keycode":87,"script":null), Object(InputEventJoypadMotion,"device":-1,"axis":1,"axis_value":-1.0,"script":null), Object(InputEventJoypadButton,"device":-1,"button_index":11,"pressure":0.0,"pressed":false,"script":null)]
}
attack={
"deadzone": 0.5,
"events": [Object(InputEventMouseButton,"button_index":1,"script":null), Object(InputEventJoypadButton,"device":-1,"button_index":2,"pressure":0.0,"pressed":false,"script":null)]
}
'''

KEYBOARD_ONLY_PROJECT = GOOD_PROJECT.replace(
    ', Object(InputEventJoypadMotion,"device":-1,"axis":1,"axis_value":-1.0,"script":null)'
    ', Object(InputEventJoypadButton,"device":-1,"button_index":11,"pressure":0.0,"pressed":false,"script":null)',
    '',
).replace(
    ', Object(InputEventJoypadButton,"device":-1,"button_index":2,"pressure":0.0,"pressed":false,"script":null)',
    '',
)


def _write_project(tmp_path: Path, content: str) -> Path:
    (tmp_path / "project.godot").write_text(content, encoding="utf-8")
    return tmp_path


def test_profiles_have_required_fields():
    assert set(PUBLISH_PROFILES) == {
        "windows-desktop", "linux-desktop", "html5-share", "arm-handheld",
    }
    for pid, prof in PUBLISH_PROFILES.items():
        assert prof["id"] == pid
        for key in ("exportPreset", "resolutionTargets", "inputRequirements",
                    "packaging", "binaryName", "templateBinaries", "presetOptions"):
            assert key in prof, f"{pid} missing {key}"
        assert prof["packaging"] in ("zip", "folder")
        assert prof["presetOptions"], f"{pid}: empty [preset.N.options] makes Godot warn"


def test_parse_project_godot(tmp_path):
    proj = _write_project(tmp_path, GOOD_PROJECT)
    parsed = parse_project_godot(proj)
    assert parsed["exists"]
    assert parsed["main_scene"] == "res://scenes/main.tscn"
    assert (parsed["viewport_width"], parsed["viewport_height"]) == (1152, 648)
    assert set(parsed["actions"]) == {"move_up", "attack"}
    assert parsed["actions"]["move_up"]["joy_buttons"] == {11}
    assert parsed["actions"]["move_up"]["has_joy_motion"]
    assert parsed["actions"]["attack"]["has_joypad"]


def test_lint_windows_desktop_clean(tmp_path):
    proj = _write_project(tmp_path, GOOD_PROJECT)
    result = lint_project(proj, PUBLISH_PROFILES["windows-desktop"])
    assert result["ok"]
    assert result["findings"] == []


def test_lint_missing_project(tmp_path):
    result = lint_project(tmp_path / "nope", PUBLISH_PROFILES["windows-desktop"])
    assert not result["ok"]
    assert result["findings"][0]["code"] == "PROJECT_MISSING"


def test_lint_main_scene_missing(tmp_path):
    proj = _write_project(
        tmp_path, GOOD_PROJECT.replace('run/main_scene="res://scenes/main.tscn"\n', ""))
    result = lint_project(proj, PUBLISH_PROFILES["windows-desktop"])
    assert not result["ok"]
    assert [f["code"] for f in result["findings"]] == ["MAIN_SCENE_MISSING"]


def test_lint_gamepad_only_flags_keyboard_actions(tmp_path):
    proj = _write_project(tmp_path, KEYBOARD_ONLY_PROJECT)
    result = lint_project(proj, PUBLISH_PROFILES["arm-handheld"])
    assert not result["ok"]
    codes = [f["code"] for f in result["findings"]]
    # both actions lack joypad bindings; move_up additionally lacks a D-pad button
    assert codes.count("INPUT_NO_JOYPAD") == 2
    assert "INPUT_NO_DPAD" in codes


def test_lint_arm_handheld_resolution_warning(tmp_path):
    # 1152x648 exceeds both 480p-class targets -> warning, but ok stays True
    proj = _write_project(tmp_path, GOOD_PROJECT)
    result = lint_project(proj, PUBLISH_PROFILES["arm-handheld"])
    assert result["ok"]
    assert [f["code"] for f in result["findings"]] == ["RES_EXCEEDS_TARGET"]

    # 854x480 matches the primary target -> no resolution finding
    sized = GOOD_PROJECT.replace("viewport_width=1152", "viewport_width=854") \
                        .replace("viewport_height=648", "viewport_height=480")
    proj2 = _write_project(tmp_path, sized)
    result2 = lint_project(proj2, PUBLISH_PROFILES["arm-handheld"])
    assert all(f["code"] != "RES_EXCEEDS_TARGET" for f in result2["findings"])


def test_lint_resolution_unset_is_info(tmp_path):
    stripped = "\n".join(
        l for l in GOOD_PROJECT.splitlines() if not l.startswith("window/size/"))
    proj = _write_project(tmp_path, stripped)
    result = lint_project(proj, PUBLISH_PROFILES["windows-desktop"])
    assert result["ok"]
    assert [f["code"] for f in result["findings"]] == ["RES_UNSET"]
    assert result["findings"][0]["severity"] == "info"


def test_preset_block_uses_forward_slashes():
    # Godot's ConfigFile treats backslashes as escapes; a raw Windows path in
    # export_path corrupts the whole export_presets.cfg.
    block = build_preset_block(
        PUBLISH_PROFILES["windows-desktop"], 0, "C:\\tmp\\out\\game.exe")
    assert 'export_path="C:/tmp/out/game.exe"' in block
    assert "\\" not in block


def test_ensure_export_preset_appends_and_dedupes(tmp_path):
    proj = _write_project(tmp_path, GOOD_PROJECT)
    name1 = ensure_export_preset(proj, PUBLISH_PROFILES["windows-desktop"], "out/a.exe")
    name2 = ensure_export_preset(proj, PUBLISH_PROFILES["arm-handheld"], "out/b.arm64")
    assert (name1, name2) == ("windows-desktop", "arm-handheld")
    cfg = (proj / "export_presets.cfg").read_text(encoding="utf-8")
    assert "[preset.0]" in cfg and "[preset.1]" in cfg
    assert 'binary_format/architecture="arm64"' in cfg

    # re-running for an existing profile must not duplicate the preset
    ensure_export_preset(proj, PUBLISH_PROFILES["windows-desktop"], "out/c.exe")
    assert cfg == (proj / "export_presets.cfg").read_text(encoding="utf-8")


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
