# Godot Capture (Windows)

Screenshot and video capture for Godot projects on Windows. Godot runs directly with GPU — no xvfb or display server needed.

The Godot project is the working directory. All paths below are relative to it.

## Screenshot Capture

Screenshots go in `screenshots/` (gitignored). Each task gets a subfolder.

```bash
MOVIE=screenshots/{task_folder}
rm -rf $MOVIE && mkdir -p $MOVIE
touch screenshots/.gdignore
timeout 30 godot --rendering-method forward_plus \
    --write-movie $MOVIE/frame.png \
    --fixed-fps 10 --quit-after {N} \
    --script test/test_task.gd 2>&1
```

Where `{task_folder}` is derived from the task name/number (e.g., `task_01_terrain`). Use lowercase with underscores.

**Timeout:** `timeout 30` is a safety net — `--quit-after` handles exit normally. Exit code 124 means timeout fired.

**Windows note:** On Windows, `timeout` is a bash command (from Git Bash / MSYS2). If unavailable, run godot directly — `--quit-after` handles exit. Kill stuck processes with `taskkill /F /IM godot.exe` if needed.

### Frame Rate and Duration

`--quit-after {N}` is the frame count. Choose based on scene type:
- **Static scenes** (decoration, terrain, UI): `--fixed-fps 1`. Adjust `--quit-after` for however many views needed (e.g. 8 frames for a camera orbit).
- **Dynamic scenes** (physics, movement, gameplay): `--fixed-fps 10`. Low FPS breaks physics — `delta` becomes too large, causing tunneling and erratic behavior. Typical: 3-10s (30-100 frames).

### Rendering Method

Windows with a discrete GPU (NVIDIA/AMD) uses `--rendering-method forward_plus` by default in Godot 4.6. This gives real shadows, SSR, SSAO, glow, volumetric fog.

For machines without a discrete GPU, use `--rendering-method gl_compatibility` as fallback:
```bash
timeout 30 godot --rendering-method gl_compatibility \
    --write-movie $MOVIE/frame.png \
    --fixed-fps 10 --quit-after {N} \
    --script test/test_task.gd 2>&1
```

## Video Capture

```bash
VIDEO=screenshots/presentation
rm -rf $VIDEO && mkdir -p $VIDEO
touch screenshots/.gdignore
timeout 60 godot --rendering-method forward_plus \
    --write-movie $VIDEO/output.avi \
    --fixed-fps 30 --quit-after 900 \
    --script test/presentation.gd 2>&1
# Convert AVI (MJPEG) to MP4 (H.264)
ffmpeg -i $VIDEO/output.avi \
    -c:v libx264 -pix_fmt yuv420p -crf 28 -preset slow \
    -vf "scale='min(1280,iw)':-2" \
    -movflags +faststart \
    $VIDEO/gameplay.mp4 2>&1
```

**AVI to MP4:** Godot outputs MJPEG AVI. ffmpeg converts to H.264 MP4. CRF 28 + `-preset slow` targets ~2-5MB for a 30s clip at 720p. `-movflags +faststart` enables streaming preview. Scale filter caps width at 1280px (no-op if already smaller).

## Killing Stuck Processes

If Godot hangs (missing `quit()` in a scene builder, infinite loop, etc.):
```bash
taskkill /F /IM Godot.exe 2>/dev/null || true
```
