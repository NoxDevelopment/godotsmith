extends SceneTree
## Scene builder — Main Menu with title, buttons, background.
## Run: timeout 60 godot --headless --script scenes/build_main_menu.gd

func _initialize() -> void:
    var root := Control.new()
    root.name = "MainMenu"
    root.set_anchors_preset(Control.PRESET_FULL_RECT)
    root.set_script(load("res://scripts/main_menu.gd"))

    # Background
    var bg := ColorRect.new()
    bg.name = "Background"
    bg.set_anchors_preset(Control.PRESET_FULL_RECT)
    bg.color = Color(0.08, 0.08, 0.12, 1.0)
    root.add_child(bg)

    # Centered content
    var center := CenterContainer.new()
    center.name = "Center"
    center.set_anchors_preset(Control.PRESET_FULL_RECT)
    root.add_child(center)

    var vbox := VBoxContainer.new()
    vbox.name = "VBox"
    vbox.add_theme_constant_override("separation", 16)
    vbox.custom_minimum_size = Vector2(320, 0)
    center.add_child(vbox)

    # Title
    var title := Label.new()
    title.name = "Title"
    title.text = "GAME TITLE"
    title.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
    title.add_theme_font_size_override("font_size", 48)
    vbox.add_child(title)

    # Spacer
    var spacer := Control.new()
    spacer.custom_minimum_size.y = 24
    vbox.add_child(spacer)

    # Button container
    var buttons := VBoxContainer.new()
    buttons.name = "Buttons"
    buttons.add_theme_constant_override("separation", 8)
    vbox.add_child(buttons)

    for btn_text in ["Start Game", "Options", "Credits", "Quit"]:
        var btn := Button.new()
        btn.name = btn_text.replace(" ", "") + "Button"
        btn.text = btn_text
        btn.custom_minimum_size.y = 48
        buttons.add_child(btn)

    _set_owners(root, root)
    var packed := PackedScene.new()
    packed.pack(root)
    ResourceSaver.save(packed, "res://scenes/main_menu.tscn")
    print("Saved: res://scenes/main_menu.tscn")
    quit(0)

func _set_owners(node: Node, owner: Node) -> void:
    for c in node.get_children():
        c.owner = owner
        if c.scene_file_path.is_empty():
            _set_owners(c, owner)
