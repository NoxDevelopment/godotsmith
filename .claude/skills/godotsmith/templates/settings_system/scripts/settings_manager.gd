extends Node
## res://scripts/settings_manager.gd — Autoload. Persistent settings loaded on boot.
## Register in project.godot:
##   [autoload]
##   SettingsManager="*res://scripts/settings_manager.gd"

signal settings_changed(section: String, key: String, value: Variant)

const SETTINGS_PATH := "user://settings.cfg"

var config := ConfigFile.new()
var _defaults := {
    "audio": {"master": 1.0, "music": 0.8, "sfx": 1.0},
    "video": {"fullscreen": false, "vsync": true, "resolution_idx": 1},
    "controls": {},  # action_name -> InputEvent dictionary
    "accessibility": {"text_scale": 1.0, "reduce_motion": false, "high_contrast": false},
}

func _ready() -> void:
    _load()
    _apply_all()

func _load() -> void:
    if config.load(SETTINGS_PATH) != OK:
        # Create with defaults
        for section in _defaults:
            for key in _defaults[section]:
                config.set_value(section, key, _defaults[section][key])
        config.save(SETTINGS_PATH)

func get_value(section: String, key: String) -> Variant:
    return config.get_value(section, key, _defaults.get(section, {}).get(key))

func set_value(section: String, key: String, value: Variant) -> void:
    config.set_value(section, key, value)
    config.save(SETTINGS_PATH)
    _apply_one(section, key, value)
    settings_changed.emit(section, key, value)

func _apply_all() -> void:
    for section in _defaults:
        for key in _defaults[section]:
            _apply_one(section, key, get_value(section, key))

func _apply_one(section: String, key: String, value: Variant) -> void:
    match [section, key]:
        ["audio", "master"]:     _set_bus_volume("Master", value)
        ["audio", "music"]:      _set_bus_volume("Music", value)
        ["audio", "sfx"]:        _set_bus_volume("SFX", value)
        ["video", "fullscreen"]:
            var mode: int = DisplayServer.WINDOW_MODE_FULLSCREEN if value else DisplayServer.WINDOW_MODE_WINDOWED
            DisplayServer.window_set_mode(mode)
        ["video", "vsync"]:
            var vs: int = DisplayServer.VSYNC_ENABLED if value else DisplayServer.VSYNC_DISABLED
            DisplayServer.window_set_vsync_mode(vs)
        ["accessibility", "text_scale"]:
            for node in get_tree().get_nodes_in_group("scalable_text"):
                if node is Label or node is Button or node is RichTextLabel:
                    node.add_theme_font_size_override("font_size", int(16 * value))

func _set_bus_volume(bus_name: String, linear: float) -> void:
    var idx: int = AudioServer.get_bus_index(bus_name)
    if idx < 0:
        return
    AudioServer.set_bus_volume_db(idx, linear_to_db(maxf(linear, 0.0001)))
    AudioServer.set_bus_mute(idx, linear < 0.01)

func rebind_action(action: StringName, event: InputEvent) -> void:
    InputMap.action_erase_events(action)
    InputMap.action_add_event(action, event)
    # Persist as dictionary
    var controls: Dictionary = config.get_value("controls", "", {})
    controls[str(action)] = _event_to_dict(event)
    config.set_value("controls", "", controls)
    config.save(SETTINGS_PATH)

func _event_to_dict(ev: InputEvent) -> Dictionary:
    if ev is InputEventKey:
        return {"type": "key", "physical_keycode": ev.physical_keycode}
    elif ev is InputEventMouseButton:
        return {"type": "mouse", "button_index": ev.button_index}
    elif ev is InputEventJoypadButton:
        return {"type": "joy_button", "button_index": ev.button_index}
    elif ev is InputEventJoypadMotion:
        return {"type": "joy_axis", "axis": ev.axis, "axis_value": ev.axis_value}
    return {}
