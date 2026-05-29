extends Control
## res://scripts/main_menu.gd — Main menu controller.

signal start_pressed
signal options_pressed
signal credits_pressed

@onready var start_btn: Button = $Center/VBox/Buttons/StartGameButton
@onready var options_btn: Button = $Center/VBox/Buttons/OptionsButton
@onready var credits_btn: Button = $Center/VBox/Buttons/CreditsButton
@onready var quit_btn: Button = $Center/VBox/Buttons/QuitButton
@onready var title: Label = $Center/VBox/Title
@onready var buttons_vbox: VBoxContainer = $Center/VBox/Buttons

func _ready() -> void:
    start_btn.pressed.connect(func(): start_pressed.emit())
    options_btn.pressed.connect(func(): options_pressed.emit())
    credits_btn.pressed.connect(func(): credits_pressed.emit())
    quit_btn.pressed.connect(func(): get_tree().quit())
    start_btn.grab_focus()
    _animate_entrance()

func _animate_entrance() -> void:
    title.modulate.a = 0.0
    var tween := create_tween()
    tween.tween_property(title, ^"modulate:a", 1.0, 0.5)
    for i in range(buttons_vbox.get_child_count()):
        var btn: Control = buttons_vbox.get_child(i)
        btn.modulate.a = 0.0
        tween.tween_property(btn, ^"modulate:a", 1.0, 0.25).set_delay(0.08 * i)
