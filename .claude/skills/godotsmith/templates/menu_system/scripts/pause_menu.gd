extends CanvasLayer
## res://scripts/pause_menu.gd — Pause menu overlay. Toggle with "pause" input action.

signal resumed
signal quit_to_menu_pressed

@onready var panel: Control = $PausePanel
@onready var resume_btn: Button = $PausePanel/VBox/ResumeButton
@onready var menu_btn: Button = $PausePanel/VBox/QuitToMenuButton

func _ready() -> void:
    process_mode = Node.PROCESS_MODE_ALWAYS
    panel.visible = false
    resume_btn.pressed.connect(_resume)
    menu_btn.pressed.connect(_quit_to_menu)

func _unhandled_input(event: InputEvent) -> void:
    if event.is_action_pressed("pause"):
        _toggle()
        get_viewport().set_input_as_handled()

func _toggle() -> void:
    var paused: bool = not get_tree().paused
    get_tree().paused = paused
    panel.visible = paused
    if paused:
        resume_btn.grab_focus()
    else:
        resumed.emit()

func _resume() -> void:
    get_tree().paused = false
    panel.visible = false
    resumed.emit()

func _quit_to_menu() -> void:
    get_tree().paused = false
    quit_to_menu_pressed.emit()
