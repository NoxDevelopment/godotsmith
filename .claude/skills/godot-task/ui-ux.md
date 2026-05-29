# UI/UX Reference

Comprehensive reference for building game UI in Godot 4.6 — menus, HUDs, settings, responsive layouts, theming, transitions, and accessibility.

## Control Node Hierarchy

```
Control (base)
├── Container (layout)
│   ├── BoxContainer (H/VBoxContainer)
│   ├── GridContainer
│   ├── FlowContainer (H/VFlowContainer)
│   ├── MarginContainer
│   ├── CenterContainer
│   ├── PanelContainer
│   ├── AspectRatioContainer
│   ├── TabContainer
│   ├── ScrollContainer
│   ├── SplitContainer (H/VSplitContainer)
│   └── SubViewportContainer
├── Button, LinkButton, TextureButton, OptionButton, MenuButton, CheckButton, CheckBox
├── Label, RichTextLabel
├── LineEdit, TextEdit, CodeEdit, SpinBox
├── ProgressBar, TextureProgressBar, HSlider, VSlider
├── TextureRect, NinePatchRect, ColorRect
├── Tree, ItemList
├── TabBar, MenuBar
├── Panel, PopupMenu, PopupPanel
├── FileDialog, AcceptDialog, ConfirmationDialog
└── VideoStreamPlayer
```

## Anchor Presets (Layout Positioning)

```gdscript
# Full rect (fills parent) — use for root UI, overlays, backgrounds
control.set_anchors_preset(Control.PRESET_FULL_RECT)

# Corners
control.set_anchors_preset(Control.PRESET_TOP_LEFT)
control.set_anchors_preset(Control.PRESET_TOP_RIGHT)
control.set_anchors_preset(Control.PRESET_BOTTOM_LEFT)
control.set_anchors_preset(Control.PRESET_BOTTOM_RIGHT)

# Edges (stretch along edge)
control.set_anchors_preset(Control.PRESET_TOP_WIDE)     # top edge, full width
control.set_anchors_preset(Control.PRESET_BOTTOM_WIDE)  # bottom edge, full width
control.set_anchors_preset(Control.PRESET_LEFT_WIDE)    # left edge, full height
control.set_anchors_preset(Control.PRESET_RIGHT_WIDE)   # right edge, full height

# Center
control.set_anchors_preset(Control.PRESET_CENTER)
control.set_anchors_preset(Control.PRESET_HCENTER_WIDE) # center, full width
control.set_anchors_preset(Control.PRESET_VCENTER_WIDE) # center, full height
```

## Container Layout Patterns

### Vertical Stack (most common for menus)
```gdscript
var vbox := VBoxContainer.new()
vbox.set_anchors_preset(Control.PRESET_FULL_RECT)
vbox.add_theme_constant_override("separation", 8)  # gap between children

# Size flags control how children fill available space
var label := Label.new()
label.size_flags_horizontal = Control.SIZE_EXPAND_FILL  # stretch horizontally
label.size_flags_vertical = Control.SIZE_SHRINK_CENTER  # center vertically, don't stretch
label.size_flags_stretch_ratio = 2.0  # take 2x space vs siblings with ratio 1.0
```

### Horizontal Bar (HUD, toolbars)
```gdscript
var hbox := HBoxContainer.new()
hbox.set_anchors_preset(Control.PRESET_TOP_WIDE)
hbox.add_theme_constant_override("separation", 12)

# Left-aligned items
var health := ProgressBar.new()
health.size_flags_horizontal = Control.SIZE_EXPAND_FILL
health.custom_minimum_size.x = 200

# Spacer pushes remaining items right
var spacer := Control.new()
spacer.size_flags_horizontal = Control.SIZE_EXPAND_FILL

# Right-aligned items
var score := Label.new()
score.size_flags_horizontal = Control.SIZE_SHRINK_END
```

### Grid (inventory, level select)
```gdscript
var grid := GridContainer.new()
grid.columns = 4
grid.add_theme_constant_override("h_separation", 4)
grid.add_theme_constant_override("v_separation", 4)
# Children fill left-to-right, top-to-bottom
```

### Margin Padding
```gdscript
var margin := MarginContainer.new()
margin.add_theme_constant_override("margin_left", 20)
margin.add_theme_constant_override("margin_right", 20)
margin.add_theme_constant_override("margin_top", 10)
margin.add_theme_constant_override("margin_bottom", 10)
```

### Scrollable Content
```gdscript
var scroll := ScrollContainer.new()
scroll.set_anchors_preset(Control.PRESET_FULL_RECT)
scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED

var content := VBoxContainer.new()
content.size_flags_horizontal = Control.SIZE_EXPAND_FILL
scroll.add_child(content)
# Add items to content — scroll activates when content exceeds visible area
```

### Responsive with AspectRatioContainer
```gdscript
var aspect := AspectRatioContainer.new()
aspect.ratio = 16.0 / 9.0
aspect.stretch_mode = AspectRatioContainer.STRETCH_WIDTH_CONTROLS_HEIGHT
aspect.alignment_horizontal = AspectRatioContainer.ALIGNMENT_CENTER
```

## Main Menu System

Production-ready main menu with animated transitions:

```gdscript
extends Control
## res://scripts/main_menu.gd

signal start_game
signal quit_game

@onready var title: Label = $VBox/Title
@onready var button_container: VBoxContainer = $VBox/Buttons
@onready var start_btn: Button = $VBox/Buttons/StartButton
@onready var options_btn: Button = $VBox/Buttons/OptionsButton
@onready var quit_btn: Button = $VBox/Buttons/QuitButton

func _ready() -> void:
    start_btn.pressed.connect(_on_start)
    options_btn.pressed.connect(_on_options)
    quit_btn.pressed.connect(_on_quit)
    start_btn.grab_focus()  # keyboard/gamepad navigation starts here
    _animate_entrance()

func _animate_entrance() -> void:
    # Fade in title
    title.modulate.a = 0.0
    var tween := create_tween()
    tween.tween_property(title, ^"modulate:a", 1.0, 0.5)

    # Slide in buttons sequentially
    for i in range(button_container.get_child_count()):
        var btn: Control = button_container.get_child(i)
        btn.modulate.a = 0.0
        btn.position.x -= 50
        tween.tween_property(btn, ^"modulate:a", 1.0, 0.3).set_delay(0.1 * i)
        tween.parallel().tween_property(btn, ^"position:x", btn.position.x + 50, 0.3).set_delay(0.1 * i)

func _on_start() -> void:
    start_game.emit()

func _on_options() -> void:
    # Show options panel (see Settings Menu below)
    pass

func _on_quit() -> void:
    get_tree().quit()
```

### Scene Builder — Main Menu
```gdscript
# In scene builder — full menu hierarchy:
var menu := Control.new()
menu.name = "MainMenu"
menu.set_anchors_preset(Control.PRESET_FULL_RECT)

# Background
var bg := ColorRect.new()
bg.name = "Background"
bg.set_anchors_preset(Control.PRESET_FULL_RECT)
bg.color = Color(0.1, 0.1, 0.15, 1.0)
menu.add_child(bg)

# Centered content
var center := CenterContainer.new()
center.name = "Center"
center.set_anchors_preset(Control.PRESET_FULL_RECT)
menu.add_child(center)

var vbox := VBoxContainer.new()
vbox.name = "VBox"
vbox.add_theme_constant_override("separation", 16)
vbox.custom_minimum_size.x = 300
center.add_child(vbox)

# Title
var title := Label.new()
title.name = "Title"
title.text = "GAME TITLE"
title.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
title.add_theme_font_size_override("font_size", 48)
vbox.add_child(title)

# Button container
var buttons := VBoxContainer.new()
buttons.name = "Buttons"
buttons.add_theme_constant_override("separation", 8)
vbox.add_child(buttons)

for btn_text in ["Start Game", "Options", "Quit"]:
    var btn := Button.new()
    btn.name = btn_text.replace(" ", "") + "Button"
    btn.text = btn_text
    btn.custom_minimum_size.y = 50
    buttons.add_child(btn)
```

## Pause Menu

```gdscript
extends CanvasLayer
## res://scripts/pause_menu.gd

@onready var panel: Control = $PausePanel

func _ready() -> void:
    process_mode = Node.PROCESS_MODE_ALWAYS  # runs during pause
    panel.visible = false
    $PausePanel/VBox/ResumeButton.pressed.connect(_resume)
    $PausePanel/VBox/QuitButton.pressed.connect(_quit_to_menu)

func _unhandled_input(event: InputEvent) -> void:
    if event.is_action_pressed("pause"):
        _toggle_pause()
        get_viewport().set_input_as_handled()

func _toggle_pause() -> void:
    var paused: bool = not get_tree().paused
    get_tree().paused = paused
    panel.visible = paused
    if paused:
        $PausePanel/VBox/ResumeButton.grab_focus()

func _resume() -> void:
    get_tree().paused = false
    panel.visible = false

func _quit_to_menu() -> void:
    get_tree().paused = false
    get_tree().change_scene_to_file("res://scenes/main_menu.tscn")
```

## Settings / Options Menu

Production settings menu with audio, video, and controls:

```gdscript
extends Control
## res://scripts/settings_menu.gd

signal settings_closed

const SETTINGS_PATH := "user://settings.cfg"
var config := ConfigFile.new()

@onready var master_slider: HSlider = $Tabs/Audio/VBox/MasterSlider
@onready var music_slider: HSlider = $Tabs/Audio/VBox/MusicSlider
@onready var sfx_slider: HSlider = $Tabs/Audio/VBox/SFXSlider
@onready var fullscreen_check: CheckButton = $Tabs/Video/VBox/FullscreenCheck
@onready var vsync_check: CheckButton = $Tabs/Video/VBox/VsyncCheck
@onready var resolution_option: OptionButton = $Tabs/Video/VBox/ResolutionOption
@onready var back_btn: Button = $BackButton

var resolutions: Array[Vector2i] = [
    Vector2i(1280, 720), Vector2i(1920, 1080), Vector2i(2560, 1440), Vector2i(3840, 2160)
]

func _ready() -> void:
    _setup_resolution_options()
    _load_settings()
    _connect_signals()
    back_btn.pressed.connect(_on_back)

func _setup_resolution_options() -> void:
    for res in resolutions:
        resolution_option.add_item("%dx%d" % [res.x, res.y])

func _connect_signals() -> void:
    master_slider.value_changed.connect(_on_master_changed)
    music_slider.value_changed.connect(_on_music_changed)
    sfx_slider.value_changed.connect(_on_sfx_changed)
    fullscreen_check.toggled.connect(_on_fullscreen_toggled)
    vsync_check.toggled.connect(_on_vsync_toggled)
    resolution_option.item_selected.connect(_on_resolution_selected)

func _on_master_changed(value: float) -> void:
    var bus_idx: int = AudioServer.get_bus_index("Master")
    AudioServer.set_bus_volume_db(bus_idx, linear_to_db(value))
    AudioServer.set_bus_mute(bus_idx, value < 0.01)

func _on_music_changed(value: float) -> void:
    var bus_idx: int = AudioServer.get_bus_index("Music")
    if bus_idx >= 0:
        AudioServer.set_bus_volume_db(bus_idx, linear_to_db(value))

func _on_sfx_changed(value: float) -> void:
    var bus_idx: int = AudioServer.get_bus_index("SFX")
    if bus_idx >= 0:
        AudioServer.set_bus_volume_db(bus_idx, linear_to_db(value))

func _on_fullscreen_toggled(enabled: bool) -> void:
    if enabled:
        DisplayServer.window_set_mode(DisplayServer.WINDOW_MODE_FULLSCREEN)
    else:
        DisplayServer.window_set_mode(DisplayServer.WINDOW_MODE_WINDOWED)

func _on_vsync_toggled(enabled: bool) -> void:
    if enabled:
        DisplayServer.window_set_vsync_mode(DisplayServer.VSYNC_ENABLED)
    else:
        DisplayServer.window_set_vsync_mode(DisplayServer.VSYNC_DISABLED)

func _on_resolution_selected(idx: int) -> void:
    var res: Vector2i = resolutions[idx]
    DisplayServer.window_set_size(res)
    # Center window
    var screen_size: Vector2i = DisplayServer.screen_get_size()
    DisplayServer.window_set_position((screen_size - res) / 2)

func _load_settings() -> void:
    if config.load(SETTINGS_PATH) != OK:
        return
    master_slider.value = config.get_value("audio", "master", 1.0)
    music_slider.value = config.get_value("audio", "music", 0.8)
    sfx_slider.value = config.get_value("audio", "sfx", 1.0)
    fullscreen_check.button_pressed = config.get_value("video", "fullscreen", false)
    vsync_check.button_pressed = config.get_value("video", "vsync", true)
    var res_idx: int = config.get_value("video", "resolution_idx", 0)
    resolution_option.selected = res_idx
    # Apply loaded settings
    _on_master_changed(master_slider.value)
    _on_music_changed(music_slider.value)
    _on_sfx_changed(sfx_slider.value)
    _on_fullscreen_toggled(fullscreen_check.button_pressed)
    _on_vsync_toggled(vsync_check.button_pressed)
    if res_idx < resolutions.size():
        _on_resolution_selected(res_idx)

func save_settings() -> void:
    config.set_value("audio", "master", master_slider.value)
    config.set_value("audio", "music", music_slider.value)
    config.set_value("audio", "sfx", sfx_slider.value)
    config.set_value("video", "fullscreen", fullscreen_check.button_pressed)
    config.set_value("video", "vsync", vsync_check.button_pressed)
    config.set_value("video", "resolution_idx", resolution_option.selected)
    config.save(SETTINGS_PATH)

func _on_back() -> void:
    save_settings()
    settings_closed.emit()
```

## Input Rebinding

```gdscript
extends Control
## Input rebinding panel — shows current bindings and lets player reassign

var _waiting_for_input := false
var _action_to_rebind := ""
var _button_to_update: Button = null

func _create_binding_row(action: String, display_name: String, parent: Control) -> void:
    var hbox := HBoxContainer.new()
    var label := Label.new()
    label.text = display_name
    label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    hbox.add_child(label)

    var btn := Button.new()
    btn.custom_minimum_size.x = 200
    _update_binding_label(btn, action)
    btn.pressed.connect(_start_rebind.bind(action, btn))
    hbox.add_child(btn)
    parent.add_child(hbox)

func _update_binding_label(btn: Button, action: String) -> void:
    var events: Array[InputEvent] = InputMap.action_get_events(action)
    if events.size() > 0:
        btn.text = events[0].as_text()
    else:
        btn.text = "[unbound]"

func _start_rebind(action: String, btn: Button) -> void:
    _waiting_for_input = true
    _action_to_rebind = action
    _button_to_update = btn
    btn.text = "Press a key..."

func _input(event: InputEvent) -> void:
    if not _waiting_for_input:
        return
    if event is InputEventKey or event is InputEventMouseButton or event is InputEventJoypadButton:
        if event.is_pressed():
            # Remove old bindings and set new one
            InputMap.action_erase_events(_action_to_rebind)
            InputMap.action_add_event(_action_to_rebind, event)
            _update_binding_label(_button_to_update, _action_to_rebind)
            _waiting_for_input = false
            get_viewport().set_input_as_handled()
```

## HUD Patterns

### Health Bar
```gdscript
# Scene builder — health bar with label
var health_bar := TextureProgressBar.new()
health_bar.name = "HealthBar"
health_bar.custom_minimum_size = Vector2(200, 24)
health_bar.max_value = 100
health_bar.value = 100
# Tint: green at full, red at low
health_bar.tint_progress = Color(0.2, 0.8, 0.2)

# Or simpler:
var simple_bar := ProgressBar.new()
simple_bar.name = "HealthBar"
simple_bar.show_percentage = false
simple_bar.custom_minimum_size = Vector2(200, 20)
```

### Animated Health Change
```gdscript
# In runtime script:
func update_health(new_hp: int, max_hp: int) -> void:
    var ratio: float = float(new_hp) / float(max_hp)
    var tween := create_tween()
    tween.tween_property(health_bar, ^"value", ratio * 100.0, 0.3).set_ease(Tween.EASE_OUT)
    # Color shift
    var color: Color = Color.GREEN.lerp(Color.RED, 1.0 - ratio)
    tween.parallel().tween_property(health_bar, ^"tint_progress", color, 0.3)
    # Shake on damage
    if ratio < health_bar.value / 100.0:
        _shake_element(health_bar)

func _shake_element(node: Control) -> void:
    var original: Vector2 = node.position
    var tween := create_tween()
    for i in range(4):
        var offset := Vector2(randf_range(-4, 4), randf_range(-2, 2))
        tween.tween_property(node, ^"position", original + offset, 0.04)
    tween.tween_property(node, ^"position", original, 0.04)
```

### Score / Counter Display
```gdscript
func update_score(new_score: int) -> void:
    # Animate counting up
    var tween := create_tween()
    var current: int = int(score_label.text)
    tween.tween_method(_set_score_text, current, new_score, 0.5)

func _set_score_text(value: int) -> void:
    score_label.text = str(value)
```

### Minimap
```gdscript
# Scene builder — minimap using SubViewport
var minimap_container := SubViewportContainer.new()
minimap_container.name = "MinimapContainer"
minimap_container.set_anchors_preset(Control.PRESET_BOTTOM_RIGHT)
minimap_container.custom_minimum_size = Vector2(200, 200)
minimap_container.offset_left = -220
minimap_container.offset_top = -220
minimap_container.offset_right = -20
minimap_container.offset_bottom = -20
minimap_container.stretch = true

var viewport := SubViewport.new()
viewport.name = "MinimapViewport"
viewport.size = Vector2i(200, 200)
viewport.render_target_update_mode = SubViewport.UPDATE_ALWAYS
viewport.transparent_bg = true
minimap_container.add_child(viewport)

# Add an orthographic camera looking down
var cam := Camera3D.new()
cam.name = "MinimapCamera"
cam.projection = Camera3D.PROJECTION_ORTHOGONAL
cam.size = 50.0  # world units visible
cam.rotation_degrees = Vector3(-90, 0, 0)
cam.position.y = 100
viewport.add_child(cam)
```

### Floating Damage Numbers
```gdscript
# In runtime script — spawn at world position
func show_damage(amount: int, world_pos: Vector3) -> void:
    var label := Label.new()
    label.text = str(amount)
    label.add_theme_font_size_override("font_size", 24)
    label.add_theme_color_override("font_color", Color.RED if amount > 0 else Color.GREEN)
    label.z_index = 100

    # Convert 3D to 2D screen position
    var screen_pos: Vector2 = get_viewport().get_camera_3d().unproject_position(world_pos)
    label.position = screen_pos
    label.pivot_offset = label.size / 2  # center origin

    get_tree().root.add_child(label)

    var tween := create_tween()
    tween.tween_property(label, ^"position:y", screen_pos.y - 60, 0.8)
    tween.parallel().tween_property(label, ^"modulate:a", 0.0, 0.8).set_delay(0.3)
    tween.tween_callback(label.queue_free)
```

### Tooltip
```gdscript
# Runtime — tooltip follows mouse, shows on hover
var tooltip_panel: PanelContainer
var tooltip_label: Label

func _ready() -> void:
    tooltip_panel = PanelContainer.new()
    tooltip_panel.visible = false
    tooltip_panel.z_index = 100
    tooltip_panel.mouse_filter = Control.MOUSE_FILTER_IGNORE
    tooltip_label = Label.new()
    tooltip_label.add_theme_font_size_override("font_size", 14)
    tooltip_panel.add_child(tooltip_label)
    add_child(tooltip_panel)

func show_tooltip(text: String) -> void:
    tooltip_label.text = text
    tooltip_panel.visible = true

func hide_tooltip() -> void:
    tooltip_panel.visible = false

func _process(_delta: float) -> void:
    if tooltip_panel.visible:
        tooltip_panel.position = get_viewport().get_mouse_position() + Vector2(16, 16)
        # Keep on screen
        var vp_size: Vector2 = get_viewport_rect().size
        if tooltip_panel.position.x + tooltip_panel.size.x > vp_size.x:
            tooltip_panel.position.x = vp_size.x - tooltip_panel.size.x
        if tooltip_panel.position.y + tooltip_panel.size.y > vp_size.y:
            tooltip_panel.position.y -= tooltip_panel.size.y + 32
```

## Scene Transitions

### Fade Transition
```gdscript
extends CanvasLayer
## res://scripts/scene_transition.gd — Autoload singleton

@onready var color_rect: ColorRect = $ColorRect

func _ready() -> void:
    color_rect.set_anchors_preset(Control.PRESET_FULL_RECT)
    color_rect.color = Color.BLACK
    color_rect.mouse_filter = Control.MOUSE_FILTER_IGNORE
    color_rect.modulate.a = 0.0

func change_scene(path: String, duration: float = 0.5) -> void:
    # Fade out
    var tween := create_tween()
    tween.tween_property(color_rect, ^"modulate:a", 1.0, duration)
    await tween.finished
    # Switch scene
    get_tree().change_scene_to_file(path)
    # Fade in
    tween = create_tween()
    tween.tween_property(color_rect, ^"modulate:a", 0.0, duration)
```

### Loading Screen
```gdscript
extends Control
## res://scripts/loading_screen.gd

@onready var progress_bar: ProgressBar = $VBox/ProgressBar
@onready var status_label: Label = $VBox/StatusLabel

var _scene_path: String
var _progress: Array = []

func load_scene(path: String) -> void:
    _scene_path = path
    visible = true
    ResourceLoader.load_threaded_request(path)

func _process(_delta: float) -> void:
    if _scene_path.is_empty():
        return
    var status: int = ResourceLoader.load_threaded_get_status(_scene_path, _progress)
    match status:
        ResourceLoader.THREAD_LOAD_IN_PROGRESS:
            progress_bar.value = _progress[0] * 100.0
            status_label.text = "Loading... %d%%" % int(_progress[0] * 100)
        ResourceLoader.THREAD_LOAD_LOADED:
            var scene: PackedScene = ResourceLoader.load_threaded_get(_scene_path)
            get_tree().change_scene_to_packed(scene)
        ResourceLoader.THREAD_LOAD_FAILED:
            status_label.text = "Failed to load!"
            _scene_path = ""
```

## Theme System

```gdscript
# Creating a theme programmatically
var theme := Theme.new()

# Font
var font := load("res://assets/fonts/game_font.ttf") as FontFile
theme.set_default_font(font)
theme.set_default_font_size(16)

# Button style
var btn_normal := StyleBoxFlat.new()
btn_normal.bg_color = Color(0.2, 0.2, 0.3)
btn_normal.corner_radius_top_left = 4
btn_normal.corner_radius_top_right = 4
btn_normal.corner_radius_bottom_left = 4
btn_normal.corner_radius_bottom_right = 4
btn_normal.content_margin_left = 16
btn_normal.content_margin_right = 16
btn_normal.content_margin_top = 8
btn_normal.content_margin_bottom = 8

var btn_hover := btn_normal.duplicate()
btn_hover.bg_color = Color(0.3, 0.3, 0.45)

var btn_pressed := btn_normal.duplicate()
btn_pressed.bg_color = Color(0.15, 0.15, 0.2)

var btn_focus := btn_normal.duplicate()
btn_focus.border_width_left = 2
btn_focus.border_width_right = 2
btn_focus.border_width_top = 2
btn_focus.border_width_bottom = 2
btn_focus.border_color = Color(0.5, 0.7, 1.0)

theme.set_stylebox("normal", "Button", btn_normal)
theme.set_stylebox("hover", "Button", btn_hover)
theme.set_stylebox("pressed", "Button", btn_pressed)
theme.set_stylebox("focus", "Button", btn_focus)
theme.set_color("font_color", "Button", Color.WHITE)
theme.set_color("font_hover_color", "Button", Color(0.9, 0.95, 1.0))
theme.set_font_size("font_size", "Button", 18)

# Panel style
var panel_style := StyleBoxFlat.new()
panel_style.bg_color = Color(0.12, 0.12, 0.18, 0.9)
panel_style.corner_radius_top_left = 8
panel_style.corner_radius_top_right = 8
panel_style.corner_radius_bottom_left = 8
panel_style.corner_radius_bottom_right = 8
panel_style.border_width_left = 1
panel_style.border_width_right = 1
panel_style.border_width_top = 1
panel_style.border_width_bottom = 1
panel_style.border_color = Color(0.3, 0.3, 0.4)
theme.set_stylebox("panel", "PanelContainer", panel_style)

# Apply to root control
root_control.theme = theme
```

## Focus & Gamepad Navigation

```gdscript
# Set focus neighbors for non-linear layouts (grid, radial menus)
btn_a.focus_neighbor_right = btn_b.get_path()
btn_b.focus_neighbor_left = btn_a.get_path()
btn_a.focus_neighbor_bottom = btn_c.get_path()

# Containers auto-assign focus neighbors for their children
# VBoxContainer: up/down navigation
# HBoxContainer: left/right navigation
# GridContainer: all 4 directions

# Initial focus — call after adding to tree
btn_start.grab_focus()

# Check focus state
if btn.has_focus():
    pass

# Focus signals
btn.focus_entered.connect(_on_focus_entered)
btn.focus_exited.connect(_on_focus_exited)

# Focus visual feedback (in runtime script)
func _on_focus_entered() -> void:
    var tween := create_tween()
    tween.tween_property(self, ^"scale", Vector2(1.05, 1.05), 0.1)

func _on_focus_exited() -> void:
    var tween := create_tween()
    tween.tween_property(self, ^"scale", Vector2.ONE, 0.1)
```

## UI Sound Effects

```gdscript
# Autoload — UIAudio singleton
extends Node

var _hover_sound: AudioStreamPlayer
var _click_sound: AudioStreamPlayer
var _back_sound: AudioStreamPlayer

func _ready() -> void:
    _hover_sound = _create_player("res://assets/audio/ui_hover.wav", -10.0)
    _click_sound = _create_player("res://assets/audio/ui_click.wav", -8.0)
    _back_sound = _create_player("res://assets/audio/ui_back.wav", -8.0)

func _create_player(path: String, volume_db: float) -> AudioStreamPlayer:
    var player := AudioStreamPlayer.new()
    player.stream = load(path)
    player.volume_db = volume_db
    player.bus = &"SFX"
    add_child(player)
    return player

func play_hover() -> void:
    _hover_sound.play()
func play_click() -> void:
    _click_sound.play()
func play_back() -> void:
    _back_sound.play()

# Connect to buttons:
func setup_button(btn: Button) -> void:
    btn.mouse_entered.connect(play_hover)
    btn.focus_entered.connect(play_hover)
    btn.pressed.connect(play_click)
```

## RichTextLabel Effects

```gdscript
# BBCode formatting in labels
var rtl := RichTextLabel.new()
rtl.bbcode_enabled = true
rtl.text = "[b]Bold[/b] [i]Italic[/i] [color=red]Red[/color]"

# Typewriter effect
rtl.visible_characters = 0
var tween := create_tween()
tween.tween_property(rtl, ^"visible_ratio", 1.0, text_length * 0.03)

# Useful BBCode tags:
# [center] [right] [left] — alignment
# [font_size=24] — size
# [outline_color=black][outline_size=2] — outline
# [wave amp=20 freq=2] — wave animation
# [shake rate=10 level=5] — shake animation
# [rainbow freq=0.2 sat=0.8 val=0.8] — rainbow color
# [fade start=4 length=3] — fade out characters
# [img]res://icon.png[/img] — inline image
# [url=https://...]Click[/url] — clickable link
# [hint=tooltip text]Hover me[/hint] — tooltip on hover
```

## Notification / Toast System

```gdscript
extends CanvasLayer
## res://scripts/notification_manager.gd — Autoload

var _container: VBoxContainer

func _ready() -> void:
    layer = 100  # above everything
    _container = VBoxContainer.new()
    _container.set_anchors_preset(Control.PRESET_TOP_RIGHT)
    _container.offset_left = -320
    _container.offset_right = -20
    _container.offset_top = 20
    _container.add_theme_constant_override("separation", 8)
    add_child(_container)

func show_notification(text: String, duration: float = 3.0, color: Color = Color.WHITE) -> void:
    var panel := PanelContainer.new()
    var label := Label.new()
    label.text = text
    label.add_theme_color_override("font_color", color)
    label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
    panel.add_child(label)
    panel.modulate.a = 0.0

    _container.add_child(panel)
    _container.move_child(panel, 0)  # newest on top

    var tween := create_tween()
    tween.tween_property(panel, ^"modulate:a", 1.0, 0.2)
    tween.tween_interval(duration)
    tween.tween_property(panel, ^"modulate:a", 0.0, 0.3)
    tween.tween_callback(panel.queue_free)
```

## Dialog Box / Text Box

```gdscript
extends PanelContainer
## res://scripts/dialog_box.gd

signal dialog_finished

@onready var name_label: Label = $VBox/NameLabel
@onready var text_label: RichTextLabel = $VBox/TextLabel
@onready var continue_indicator: Label = $VBox/ContinueIndicator

var _lines: Array[Dictionary] = []  # [{speaker, text}, ...]
var _current_line: int = -1
var _typing := false
var _chars_per_second: float = 40.0

func start_dialog(lines: Array[Dictionary]) -> void:
    _lines = lines
    _current_line = -1
    visible = true
    _advance()

func _advance() -> void:
    _current_line += 1
    if _current_line >= _lines.size():
        visible = false
        dialog_finished.emit()
        return

    var line: Dictionary = _lines[_current_line]
    name_label.text = line.get("speaker", "")
    text_label.text = line.get("text", "")
    text_label.visible_ratio = 0.0
    continue_indicator.visible = false
    _typing = true

    var duration: float = text_label.text.length() / _chars_per_second
    var tween := create_tween()
    tween.tween_property(text_label, ^"visible_ratio", 1.0, duration)
    tween.tween_callback(_on_typing_done)

func _on_typing_done() -> void:
    _typing = false
    continue_indicator.visible = true

func _unhandled_input(event: InputEvent) -> void:
    if not visible:
        return
    if event.is_action_pressed("ui_accept"):
        if _typing:
            # Skip to end of current line
            text_label.visible_ratio = 1.0
            _on_typing_done()
            get_tree().create_tween().kill()  # stop typewriter
        else:
            _advance()
        get_viewport().set_input_as_handled()
```

## Accessibility Basics

```gdscript
# Minimum touch target size (44x44 dp for mobile)
button.custom_minimum_size = Vector2(44, 44)

# High contrast text — ensure 4.5:1 contrast ratio
label.add_theme_color_override("font_color", Color.WHITE)
# Add outline for readability over varied backgrounds
label.add_theme_constant_override("outline_size", 2)
label.add_theme_color_override("font_outline_color", Color.BLACK)

# Font size scaling
func set_ui_scale(scale: float) -> void:
    get_tree().root.content_scale_factor = scale

# Colorblind-safe palette — use shapes/patterns in addition to color
# Don't rely on red/green distinction alone

# Screen reader: set tooltip on interactive elements
button.tooltip_text = "Start a new game"
```

## Responsive Layout (Multi-Resolution)

```gdscript
# project.godot stretch settings for responsive UI:
# canvas_items mode — UI scales, game renders at native
# expand aspect — UI fills available space

# Safe area for mobile (notch, rounded corners)
func _ready() -> void:
    var safe_area: Rect2i = DisplayServer.get_display_safe_area()
    var margin := MarginContainer.new()
    margin.add_theme_constant_override("margin_left", safe_area.position.x)
    margin.add_theme_constant_override("margin_top", safe_area.position.y)

# Detect orientation change
func _notification(what: int) -> void:
    if what == NOTIFICATION_WM_SIZE_CHANGED:
        var size: Vector2 = get_viewport_rect().size
        if size.x > size.y:
            _layout_landscape()
        else:
            _layout_portrait()
```

## Performance & Advanced Patterns

### UI Element Pooling
Pool frequently created/destroyed elements (chat messages, damage numbers, inventory slots) to avoid allocation churn:

```gdscript
class_name UIPool
extends Node

const MAX_POOL_SIZE := 20
var _pool: Array[Control] = []
var _scene: PackedScene

func _init(scene: PackedScene) -> void:
    _scene = scene

func acquire() -> Control:
    if _pool.is_empty():
        return _scene.instantiate()
    var ctrl: Control = _pool.pop_back()
    ctrl.visible = true
    return ctrl

func release(ctrl: Control) -> void:
    if ctrl.get_parent():
        ctrl.get_parent().remove_child(ctrl)
    ctrl.visible = false
    if _pool.size() < MAX_POOL_SIZE:
        _pool.append(ctrl)
    else:
        ctrl.queue_free()
```

### Metadata-Driven ItemList
Associate arbitrary data with visible items — cleaner than parallel arrays:

```gdscript
func populate_inventory(items: Array) -> void:
    item_list.clear()
    for item in items:
        var idx: int = item_list.add_item(item.name, item.icon)
        item_list.set_item_metadata(idx, item)  # store the whole object
        item_list.set_item_tooltip(idx, item.description)

func _on_item_selected(idx: int) -> void:
    var item = item_list.get_item_metadata(idx)  # retrieve full data
    show_item_details(item)
```

### Reusable Modal Confirmation
Store the confirm action as a `Callable` for fully reusable dialogs:

```gdscript
extends AcceptDialog

var _on_confirm: Callable

func _ready() -> void:
    confirmed.connect(_fire_callback)

func show_confirm(message: String, callback: Callable) -> void:
    dialog_text = message
    _on_confirm = callback
    popup_centered()

func _fire_callback() -> void:
    if _on_confirm.is_valid():
        _on_confirm.call()
    _on_confirm = Callable()

# Usage:
# confirm_dialog.show_confirm("Delete save?", _delete_save)
```

### Viewport-Driven Responsive Layout
React to runtime resolution/orientation changes:

```gdscript
func _ready() -> void:
    get_viewport().size_changed.connect(_on_viewport_changed)
    _on_viewport_changed()

func _on_viewport_changed() -> void:
    var size: Vector2 = get_viewport_rect().size
    var aspect: float = size.x / size.y
    if aspect < 1.0:
        _apply_portrait_layout()
    elif aspect < 1.5:
        _apply_compact_landscape_layout()
    else:
        _apply_wide_landscape_layout()
```

### Performance Tips

- **`clip_contents = true`** — Prevents rendering off-screen content in scrolling/masked panels.
- **Disable hidden UI** — `process_mode = Node.PROCESS_MODE_DISABLED` on hidden menus avoids per-frame cost.
- **CanvasLayer over z_index** — Use explicit `layer` values (0 = world, 10 = HUD, 100 = pause/modal) for predictable draw order.
- **RichTextLabel cost** — BBCode parsing is not cheap. Cache parsed text; avoid updating every frame. Plain Label if no formatting needed.
- **TextureAtlas UI sprites** — Pack all UI icons into a single atlas texture to reduce draw calls.
- **Batch similar elements** — Keep like-typed controls under the same parent (same theme, same shader) for batching.
- **Theme inheritance** — Base theme in `.tres` + per-screen overrides avoids duplicate StyleBox resources.
- **Signal, don't poll** — Update UI from state-change signals, not `_process()`.

### Accessibility: Text Scaling via Groups
Tag scalable elements and adjust en masse from a settings slider:

```gdscript
# In scaffold / scene builders, add scalable labels to a group:
label.add_to_group("scalable_text")

# Autoload — AccessibilityManager:
extends Node

var _text_scale: float = 1.0

func set_text_scale(scale: float) -> void:
    _text_scale = scale
    for node in get_tree().get_nodes_in_group("scalable_text"):
        if node is Label or node is RichTextLabel or node is Button:
            node.add_theme_font_size_override("font_size", int(16 * scale))

# Hook to settings slider in options menu:
# accessibility_slider.value_changed.connect(AccessibilityManager.set_text_scale)
```

## Common UI Anti-Patterns

- **Don't use `position` for layout** — use containers and anchors. Manual positioning breaks at different resolutions.
- **Don't nest ScrollContainers** — causes scroll conflicts. Use TabContainer or show/hide sections.
- **Don't use `_process()` for UI updates** — use signals. Connect to data changes, not polling.
- **Don't ignore focus order** — gamepad users can't navigate without proper focus neighbors.
- **Don't hardcode pixel sizes** — use `custom_minimum_size` as minimums, let containers handle the rest.
- **Don't skip `mouse_filter`** — overlapping invisible Controls eat mouse events. Set `mouse_filter = MOUSE_FILTER_IGNORE` on non-interactive overlays.
- **Don't forget `set_anchors_preset()`** — Controls default to top-left with zero size. Always set anchors.
