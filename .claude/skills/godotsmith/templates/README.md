# Drop-in Templates

Production-ready system scaffolding. The scaffold step can copy these wholesale into a new project rather than regenerating from scratch.

## Available Templates

| Template | Contents | When to Use |
|----------|----------|-------------|
| `menu_system/` | Main menu scene builder + controller, pause menu | Any game with a title screen |
| `save_system/` | `SaveManager` autoload with versioned saves, autosave, migration | Any game with progression |
| `settings_system/` | `SettingsManager` autoload (audio buses, video, accessibility, rebinding persistence) | Any game with options |

## Usage From Scaffold

```bash
# Copy template into project:
cp -r "${CLAUDE_SKILL_DIR}/templates/menu_system/scenes/"* scenes/
cp -r "${CLAUDE_SKILL_DIR}/templates/menu_system/scripts/"* scripts/

# Build the menu scene:
timeout 60 godot --headless --script scenes/build_main_menu.gd

# For save/settings autoloads — register in project.godot:
#   [autoload]
#   SaveManager="*res://scripts/save_manager.gd"
#   SettingsManager="*res://scripts/settings_manager.gd"
```

## Template Conventions

All templates follow these rules:
- Scripts reference `$Path/To/Node` exactly as the scene builder creates them
- No hardcoded asset paths — provide placeholders or use procedural styling
- Signals are declared at the top; handlers at the bottom
- `Node.PROCESS_MODE_ALWAYS` on pause UI
- Audio buses expected: `Master`, `Music`, `SFX` (add in `project.godot` or via AudioServer at boot)
- "scalable_text" group on any label that should respond to accessibility text scaling
- "persistent" group on nodes that should be saved (must implement `save_data() -> Dictionary`)
- "player" group on the player node (SaveManager queries it)
- "game_manager" group on a global manager node (for flags)

## Customization

After copy:
1. Open the copied `.gd` files and replace placeholder strings ("GAME TITLE", button labels)
2. Adjust colors/fonts to match `STYLE_PROFILE.json`
3. Wire up scene transitions in the main menu's signal handlers
4. Add audio bus layout if not already in `project.godot`:
   ```ini
   [audio]
   buses/default_bus_layout="res://default_bus_layout.tres"
   ```
