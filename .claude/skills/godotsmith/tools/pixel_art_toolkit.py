#!/usr/bin/env python3
"""Pixel Art Toolkit — generate, repair, palettize, and animate pixel art.

Combines techniques from pixeldetector, sd-palettize, SD-piXL, and pixel-fix
into a unified pipeline for game sprite creation.

Subcommands:
  generate     Generate pixel art from prompt via ComfyUI with pixel LoRAs
  pixelize     Convert any image to clean pixel art (detect grid, snap, reduce palette)
  palettize    Apply color palette reduction with optional dithering
  repair       Fix pixel grid alignment on misaligned pixel art
  detect       Auto-detect pixel grid size from an image
  spritesheet  Assemble individual frames into a sprite sheet
  animate      Extract animation frames from a sprite sheet
  batch        Run full pipeline on multiple images

Built-in palettes: PICO-8, NES, GameBoy, ENDESGA-32, ENDESGA-64, Sweetie-16, AAP-64
"""

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image

# ---------------------------------------------------------------------------
# Built-in retro palettes (RGB tuples)
# ---------------------------------------------------------------------------

PALETTES = {
    "pico8": [
        (0,0,0), (29,43,83), (126,37,83), (0,135,81),
        (171,82,54), (95,87,79), (194,195,199), (255,241,232),
        (255,0,77), (255,163,0), (255,236,39), (0,228,54),
        (41,173,255), (131,118,156), (255,119,168), (255,204,170),
    ],
    "gameboy": [
        (15,56,15), (48,98,48), (139,172,15), (155,188,15),
    ],
    "nes": [
        (0,0,0), (252,252,252), (248,56,0), (0,0,252),
        (104,68,252), (216,0,204), (228,0,88), (248,120,88),
        (248,184,0), (0,120,0), (0,168,0), (0,168,68),
        (0,88,248), (120,120,120), (188,188,188), (252,224,168),
    ],
    "sweetie16": [
        (26,28,44), (93,39,93), (177,62,83), (239,125,87),
        (255,205,117), (167,240,112), (56,183,100), (37,113,121),
        (41,54,111), (59,93,201), (65,166,246), (115,239,247),
        (244,244,244), (148,176,194), (86,108,134), (51,60,87),
    ],
    "endesga32": [
        (190,74,47), (215,118,67), (234,212,170), (228,166,114),
        (184,111,80), (115,62,57), (62,39,49), (162,38,51),
        (228,59,68), (247,118,34), (254,174,52), (254,231,97),
        (99,199,77), (62,137,72), (38,92,66), (25,60,62),
        (18,78,137), (0,153,219), (44,232,245), (192,203,220),
        (139,155,180), (90,105,136), (58,68,102), (38,43,68),
        (24,20,37), (255,0,68), (104,56,108), (181,80,136),
        (246,117,122), (232,183,150), (194,133,105), (143,86,59),
    ],
    "endesga64": [
        (255,0,64), (31,14,40), (71,23,46), (114,31,55),
        (171,47,56), (212,76,55), (235,120,55), (246,173,72),
        (255,217,94), (255,238,131), (168,224,68), (86,189,68),
        (42,147,82), (27,104,87), (21,71,76), (25,46,57),
        (37,36,81), (41,65,123), (36,101,158), (42,143,176),
        (66,187,186), (115,220,186), (179,241,182), (231,254,204),
        (255,255,255), (211,212,216), (164,169,178), (120,128,141),
        (79,90,105), (48,57,73), (92,58,42), (124,83,52),
        (160,113,65), (193,143,85), (218,182,120), (238,213,159),
        (200,148,136), (174,106,115), (142,70,95), (99,44,71),
        (64,30,60), (140,55,115), (186,82,138), (224,124,158),
        (249,179,185), (149,122,171), (100,81,145), (70,50,115),
        (49,31,79), (21,18,38), (35,29,35), (57,47,49),
        (87,68,66), (114,91,84), (142,119,107), (177,157,141),
        (209,195,178), (233,222,204), (239,135,51), (194,91,43),
        (148,61,45), (107,35,41), (69,21,33), (43,21,44),
    ],
    "aap64": [
        (6,6,8), (20,16,19), (59,31,43), (90,41,44),
        (127,64,49), (175,112,69), (219,173,92), (246,227,149),
        (238,237,206), (176,210,145), (108,169,101), (55,122,82),
        (31,76,74), (23,47,60), (20,29,41), (11,14,23),
        (45,29,52), (79,46,86), (131,62,133), (182,86,173),
        (228,122,196), (249,180,213), (253,230,224), (232,190,172),
        (214,152,134), (185,113,109), (148,79,89), (108,53,72),
        (68,41,60), (43,32,51), (40,43,78), (48,62,111),
        (58,93,148), (72,135,181), (103,179,205), (150,212,222),
        (200,237,235), (171,218,196), (125,193,151), (81,164,115),
        (55,128,97), (42,93,83), (37,62,66), (35,41,46),
        (49,49,45), (75,68,53), (106,92,64), (145,126,82),
        (183,164,107), (215,199,143), (234,222,187), (248,243,228),
        (245,237,186), (243,223,137), (243,202,82), (218,162,48),
        (175,112,48), (133,77,50), (93,52,48), (63,38,42),
        (80,48,52), (109,62,56), (148,81,60), (193,112,68),
        (230,157,82), (246,202,108), (249,231,163), (252,250,222),
    ],
    # --- Extended palettes ---
    "1bit": [(0, 0, 0), (255, 255, 255)],
    "1bit_amber": [(0, 0, 0), (255, 176, 0)],
    "1bit_green": [(0, 0, 0), (0, 255, 65)],
    "cga": [(0, 0, 0), (85, 255, 255), (255, 85, 255), (255, 255, 255)],
    "cga_red": [(0, 0, 0), (85, 255, 85), (255, 85, 85), (255, 255, 85)],
    "c64": [
        (0, 0, 0), (255, 255, 255), (136, 0, 0), (170, 255, 238),
        (204, 68, 204), (0, 204, 85), (0, 0, 170), (238, 238, 119),
        (221, 136, 85), (102, 68, 0), (255, 119, 119), (51, 51, 51),
        (119, 119, 119), (170, 255, 102), (0, 136, 255), (187, 187, 187),
    ],
    "mc": [
        (86, 125, 70), (139, 105, 77), (100, 100, 100), (50, 50, 50),
        (180, 160, 120), (60, 40, 30), (70, 130, 180), (200, 200, 200),
        (170, 50, 50), (40, 80, 40), (140, 140, 60), (100, 60, 30),
        (80, 80, 120), (200, 180, 140), (120, 80, 60), (30, 30, 50),
    ],
    "zx": [
        (0, 0, 0), (0, 0, 215), (215, 0, 0), (215, 0, 215),
        (0, 215, 0), (0, 215, 215), (215, 215, 0), (215, 215, 215),
        (0, 0, 255), (255, 0, 0), (255, 0, 255),
        (0, 255, 0), (0, 255, 255), (255, 255, 0), (255, 255, 255),
    ],
    "msx": [
        (0, 0, 0), (1, 1, 1), (62, 184, 73), (116, 208, 125),
        (89, 85, 224), (128, 118, 241), (185, 94, 81), (101, 219, 239),
        (219, 101, 89), (255, 137, 125), (204, 195, 94), (222, 208, 135),
        (58, 162, 65), (183, 102, 181), (204, 204, 204), (255, 255, 255),
    ],
    "nostalgia": [
        (208, 208, 88), (160, 168, 64), (112, 128, 40), (64, 88, 16),
        (216, 176, 112), (184, 136, 80), (136, 96, 48), (88, 56, 16),
        (200, 120, 88), (160, 80, 56), (120, 48, 32), (80, 24, 16),
        (168, 168, 168), (120, 120, 120), (72, 72, 72), (24, 24, 24),
    ],
    "resurrect64": [
        (46, 34, 47), (62, 53, 70), (80, 73, 95), (101, 97, 115),
        (146, 143, 151), (198, 195, 198), (226, 226, 219), (245, 243, 240),
        (255, 166, 119), (255, 130, 73), (211, 95, 63), (163, 64, 53),
        (119, 41, 44), (87, 28, 39), (55, 22, 36), (34, 15, 30),
        (194, 185, 121), (162, 162, 80), (121, 141, 59), (79, 121, 66),
        (46, 99, 74), (28, 74, 81), (22, 50, 74), (25, 32, 52),
        (64, 128, 168), (107, 162, 195), (157, 199, 207), (194, 228, 216),
        (243, 200, 163), (229, 171, 125), (191, 128, 97), (153, 97, 80),
        (255, 210, 63), (245, 169, 59), (220, 125, 72), (190, 90, 63),
        (196, 79, 119), (165, 55, 109), (118, 40, 93), (73, 36, 79),
        (107, 172, 172), (82, 139, 141), (55, 103, 113), (36, 70, 89),
        (36, 36, 55), (58, 48, 66), (84, 64, 76), (116, 87, 85),
        (157, 116, 96), (191, 149, 116), (211, 177, 143), (236, 210, 178),
        (255, 234, 195), (255, 247, 221), (239, 216, 191), (211, 186, 168),
        (179, 153, 146), (145, 124, 124), (115, 99, 102), (89, 77, 82),
        (61, 57, 63), (42, 39, 49), (30, 27, 36), (17, 14, 22),
    ],
    "apollo": [
        (23, 14, 22), (38, 31, 41), (46, 46, 64), (57, 67, 86),
        (79, 96, 110), (106, 128, 130), (145, 166, 151), (181, 199, 170),
        (220, 229, 199), (147, 105, 78), (119, 72, 54), (94, 47, 40),
        (68, 32, 32), (43, 22, 27), (115, 41, 48), (167, 60, 63),
        (202, 98, 72), (222, 142, 81), (239, 185, 100), (246, 226, 144),
        (209, 155, 128), (179, 113, 105), (151, 78, 90), (116, 51, 75),
        (75, 37, 67), (49, 29, 52), (36, 42, 79), (53, 70, 115),
        (79, 107, 152), (110, 148, 183), (155, 190, 205), (199, 224, 222),
        (81, 102, 68), (63, 73, 47), (47, 50, 34), (35, 32, 26),
    ],
    "steamlords": [
        (33, 30, 51), (46, 53, 77), (62, 79, 92), (92, 108, 93),
        (143, 151, 117), (194, 195, 148), (219, 214, 167), (238, 235, 195),
        (84, 51, 68), (127, 72, 75), (171, 104, 78), (207, 144, 85),
        (230, 187, 106), (243, 222, 138), (255, 250, 172), (255, 255, 215),
    ],
    "journey": [
        (5, 5, 15), (18, 18, 36), (36, 36, 56), (58, 60, 83),
        (82, 89, 113), (117, 125, 143), (164, 170, 182), (218, 224, 234),
        (254, 254, 254), (190, 119, 43), (245, 179, 66), (255, 235, 148),
        (255, 248, 207), (162, 59, 55), (216, 91, 80), (251, 147, 102),
        (248, 200, 158), (46, 56, 88), (57, 85, 119), (77, 125, 153),
        (109, 172, 186), (158, 215, 213), (189, 232, 223), (42, 69, 61),
        (56, 100, 76), (80, 141, 94), (130, 182, 115), (185, 214, 144),
        (217, 235, 180), (102, 42, 67), (143, 57, 93), (186, 80, 117),
        (221, 128, 156), (241, 179, 191), (253, 217, 219),
    ],
}


# ---------------------------------------------------------------------------
# Core algorithms
# ---------------------------------------------------------------------------

def detect_pixel_size(img: Image.Image) -> tuple[int, int]:
    """Detect pixel grid size by analyzing edge gradients (from pixeldetector)."""
    from scipy.signal import find_peaks

    npim = np.array(img.convert("RGB"), dtype=np.float64)

    # Horizontal color differences
    hdiff = np.sqrt(np.sum((npim[:, :-1, :] - npim[:, 1:, :]) ** 2, axis=2))
    hsum = np.sum(hdiff, axis=0)

    # Vertical color differences
    vdiff = np.sqrt(np.sum((npim[:-1, :, :] - npim[1:, :, :]) ** 2, axis=2))
    vsum = np.sum(vdiff, axis=1)

    hpeaks, _ = find_peaks(hsum, distance=1, height=0.0)
    vpeaks, _ = find_peaks(vsum, distance=1, height=0.0)

    h_size = int(np.median(np.diff(hpeaks))) if len(hpeaks) > 1 else 1
    v_size = int(np.median(np.diff(vpeaks))) if len(vpeaks) > 1 else 1

    return max(1, h_size), max(1, v_size)


def repair_pixel_grid(img: Image.Image, pixel_size: int) -> Image.Image:
    """Snap image to perfect pixel grid via nearest-neighbor down+up (from pixel-fix)."""
    w, h = img.size
    small = img.resize((w // pixel_size, h // pixel_size), resample=Image.NEAREST)
    return small  # Return the small version — caller decides whether to upscale


def reduce_palette(img: Image.Image, num_colors: int = 16,
                   palette_name: str = "", dither: bool = False) -> Image.Image:
    """Reduce image colors via k-means quantization (from sd-palettize)."""
    rgb = img.convert("RGB")

    if palette_name and palette_name in PALETTES:
        # Map to fixed palette
        palette_colors = PALETTES[palette_name]
        palette_img = Image.new("P", (1, 1))
        flat = []
        for c in palette_colors:
            flat.extend(c)
        # Pad to 256 colors
        flat.extend([0] * (768 - len(flat)))
        palette_img.putpalette(flat)

        quantized = rgb.quantize(palette=palette_img, dither=1 if dither else 0)
        return quantized.convert("RGBA")
    else:
        # Auto k-means
        quantized = rgb.quantize(colors=num_colors, method=1, kmeans=num_colors, dither=1 if dither else 0)
        return quantized.convert("RGBA")


def auto_detect_best_k(img: Image.Image, max_k: int = 32) -> int:
    """Find optimal number of colors using elbow method."""
    rgb = img.convert("RGB")
    pixels = np.array(rgb).reshape(-1, 3).astype(np.float64)

    # Sample for speed
    if len(pixels) > 10000:
        indices = np.random.choice(len(pixels), 10000, replace=False)
        pixels = pixels[indices]

    distortions = []
    for k in range(1, min(max_k + 1, len(np.unique(pixels, axis=0)) + 1)):
        q = rgb.quantize(colors=k, method=2, kmeans=k, dither=0)
        pal = np.array(q.getpalette()[:k * 3]).reshape(-1, 3).astype(np.float64)
        dists = np.min(np.linalg.norm(pixels[:, np.newaxis] - pal[np.newaxis, :], axis=2), axis=1)
        distortions.append(np.sum(dists ** 2))

    if len(distortions) < 3:
        return min(max_k, 16)

    # Rate of change — find elbow
    roc = []
    for i in range(len(distortions) - 1):
        if distortions[i] > 0:
            roc.append((distortions[i + 1] - distortions[i]) / distortions[i])
        else:
            roc.append(0)

    best_k = np.argmax(roc) + 2 if roc else 16
    return max(2, min(best_k, max_k))


def pixelize(img: Image.Image, target_size: int = 64, num_colors: int = 0,
             palette_name: str = "", dither: bool = False) -> Image.Image:
    """Full pipeline: resize to target pixel dimensions, reduce palette."""
    # Step 1: Resize to target pixel dimensions with nearest neighbor
    w, h = img.size
    aspect = w / h
    if aspect >= 1:
        new_w = target_size
        new_h = max(1, int(target_size / aspect))
    else:
        new_h = target_size
        new_w = max(1, int(target_size * aspect))

    small = img.resize((new_w, new_h), resample=Image.NEAREST)

    # Step 2: Palette reduction
    if num_colors == 0:
        num_colors = auto_detect_best_k(small)

    result = reduce_palette(small, num_colors, palette_name, dither)
    return result


def make_gif(frames: list[Image.Image], fps: int = 8, loop: int = 0) -> bytes:
    """Create animated GIF from frames. Returns GIF bytes."""
    import io
    buf = io.BytesIO()
    duration_ms = max(20, 1000 // fps)  # GIF minimum frame duration is ~20ms
    frames[0].save(buf, format="GIF", save_all=True, append_images=frames[1:],
                   duration=duration_ms, loop=loop, disposal=2)
    return buf.getvalue()


def save_gif(frames: list[Image.Image], output: Path, fps: int = 8) -> Path:
    """Save animated GIF to file."""
    output.parent.mkdir(parents=True, exist_ok=True)
    gif_bytes = make_gif(frames, fps)
    output.write_bytes(gif_bytes)
    return output


def make_spritesheet(frames: list[Image.Image], columns: int = 4) -> Image.Image:
    """Assemble frames into a sprite sheet grid."""
    if not frames:
        raise ValueError("No frames to assemble")
    fw, fh = frames[0].size
    rows = math.ceil(len(frames) / columns)
    sheet = Image.new("RGBA", (fw * columns, fh * rows), (0, 0, 0, 0))
    for i, frame in enumerate(frames):
        r, c = divmod(i, columns)
        sheet.paste(frame, (c * fw, r * fh))
    return sheet


def extract_frames(sheet: Image.Image, columns: int, rows: int) -> list[Image.Image]:
    """Extract individual frames from a sprite sheet."""
    w, h = sheet.size
    fw, fh = w // columns, h // rows
    frames = []
    for r in range(rows):
        for c in range(columns):
            frame = sheet.crop((c * fw, r * fh, (c + 1) * fw, (r + 1) * fh))
            frames.append(frame)
    return frames


# ---------------------------------------------------------------------------
# CLI commands
# ---------------------------------------------------------------------------

def result_json(ok, path=None, error=None, **extra):
    d = {"ok": ok}
    if path: d["path"] = str(path)
    if error: d["error"] = error
    d.update(extra)
    print(json.dumps(d))


def cmd_generate(args):
    """Generate pixel art via ComfyUI with pixel LoRA triggers."""
    from comfyui_client import is_available, generate_image

    if not is_available():
        result_json(False, error="ComfyUI not running")
        sys.exit(1)

    output = Path(args.output)
    trigger = {
        "sprite": "pixel art game sprite, top-down view,",
        "character": "pixel art character sprite sheet, multiple poses,",
        "tileset": "pixel art tileset, seamless tile, top-down view,",
        "item": "pixel art game item, clean icon,",
        "portrait": "pixel art character portrait, detailed face,",
        "landscape": "pixel art landscape, scenic background,",
    }.get(args.type, "pixel art,")

    full_prompt = f"{trigger} {args.prompt}"
    print(f"Generating via ComfyUI: {args.type}...", file=sys.stderr)
    generate_image(full_prompt, output, size="1K")

    # Post-process: pixelize if requested
    if args.pixelize:
        print(f"Pixelizing to {args.target_size}px...", file=sys.stderr)
        img = Image.open(output).convert("RGBA")
        result = pixelize(img, args.target_size, args.colors, args.palette)
        result.save(output)

    result_json(True, path=output)


def cmd_pixelize(args):
    """Convert image to clean pixel art."""
    img = Image.open(args.input).convert("RGBA")
    print(f"Pixelizing {img.size} → {args.target_size}px, palette={args.palette or 'auto'}...", file=sys.stderr)
    result = pixelize(img, args.target_size, args.colors, args.palette, args.dither)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    result.save(output)
    print(f"Saved: {output} ({result.size[0]}x{result.size[1]})", file=sys.stderr)
    result_json(True, path=output, size=list(result.size), colors=len(set(result.convert("RGB").getdata())))


def cmd_palettize(args):
    """Apply palette reduction."""
    img = Image.open(args.input).convert("RGBA")
    print(f"Reducing palette: {args.palette or f'{args.colors} colors'}...", file=sys.stderr)
    result = reduce_palette(img, args.colors, args.palette, args.dither)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    result.save(output)
    result_json(True, path=output, colors=len(set(result.convert("RGB").getdata())))


def cmd_repair(args):
    """Fix pixel grid alignment."""
    img = Image.open(args.input).convert("RGBA")
    if args.auto:
        h, v = detect_pixel_size(img)
        pixel_size = max(h, v)
        print(f"Auto-detected pixel size: {pixel_size}px", file=sys.stderr)
    else:
        pixel_size = args.pixel_size

    result = repair_pixel_grid(img, pixel_size)
    if args.upscale:
        result = result.resize((img.width, img.height), resample=Image.NEAREST)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    result.save(output)
    result_json(True, path=output, pixel_size=pixel_size, size=list(result.size))


def cmd_detect(args):
    """Detect pixel grid size."""
    img = Image.open(args.input).convert("RGBA")
    h, v = detect_pixel_size(img)
    print(json.dumps({"horizontal": h, "vertical": v, "suggested": max(h, v)}))


def cmd_spritesheet(args):
    """Assemble frames into sprite sheet."""
    frames = []
    for fp in sorted(Path(args.input_dir).glob("*.png")):
        frames.append(Image.open(fp).convert("RGBA"))
    if not frames:
        result_json(False, error="No PNG frames found")
        sys.exit(1)

    sheet = make_spritesheet(frames, args.columns)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output)
    rows = math.ceil(len(frames) / args.columns)
    result_json(True, path=output, frames=len(frames), columns=args.columns, rows=rows,
                size=list(sheet.size), frame_size=list(frames[0].size))


def cmd_animate(args):
    """Extract frames from sprite sheet."""
    sheet = Image.open(args.input).convert("RGBA")
    frames = extract_frames(sheet, args.columns, args.rows)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    for i, frame in enumerate(frames):
        frame.save(output_dir / f"frame_{i:04d}.png")
    result_json(True, output_dir=str(output_dir), frames=len(frames),
                frame_size=list(frames[0].size))


def cmd_gif(args):
    """Create animated GIF from sprite sheet or frame directory."""
    if args.input_dir:
        frames = []
        for fp in sorted(Path(args.input_dir).glob("*.png")):
            frames.append(Image.open(fp).convert("RGBA"))
    elif args.sheet:
        sheet = Image.open(args.sheet).convert("RGBA")
        frames = extract_frames(sheet, args.columns, args.rows)
    else:
        result_json(False, error="Provide --input-dir or --sheet")
        sys.exit(1)

    if not frames:
        result_json(False, error="No frames found")
        sys.exit(1)

    output = Path(args.output)
    save_gif(frames, output, args.fps)
    print(f"Saved GIF: {output} ({len(frames)} frames, {args.fps} FPS)", file=sys.stderr)
    result_json(True, path=output, frames=len(frames), fps=args.fps)


def cmd_palettes(args):
    """List available palettes."""
    for name, colors in PALETTES.items():
        print(f"  {name:15s} — {len(colors)} colors")


def main():
    parser = argparse.ArgumentParser(description="Pixel Art Toolkit")
    sub = parser.add_subparsers(dest="command", required=True)

    # generate
    p = sub.add_parser("generate", help="Generate pixel art via ComfyUI")
    p.add_argument("--prompt", required=True)
    p.add_argument("--type", default="sprite", choices=["sprite", "character", "tileset", "item", "portrait", "landscape"])
    p.add_argument("--pixelize", action="store_true", help="Post-process to clean pixel art")
    p.add_argument("--target-size", type=int, default=64, help="Pixel dimensions after pixelization")
    p.add_argument("--colors", type=int, default=0, help="Max colors (0=auto)")
    p.add_argument("--palette", default="", choices=[""] + list(PALETTES.keys()))
    p.add_argument("-o", "--output", required=True)
    p.set_defaults(func=cmd_generate)

    # pixelize
    p = sub.add_parser("pixelize", help="Convert image to pixel art")
    p.add_argument("input", help="Input image")
    p.add_argument("--target-size", type=int, default=64)
    p.add_argument("--colors", type=int, default=0, help="Max colors (0=auto detect)")
    p.add_argument("--palette", default="", choices=[""] + list(PALETTES.keys()))
    p.add_argument("--dither", action="store_true")
    p.add_argument("-o", "--output", required=True)
    p.set_defaults(func=cmd_pixelize)

    # palettize
    p = sub.add_parser("palettize", help="Reduce colors")
    p.add_argument("input")
    p.add_argument("--colors", type=int, default=16)
    p.add_argument("--palette", default="", choices=[""] + list(PALETTES.keys()))
    p.add_argument("--dither", action="store_true")
    p.add_argument("-o", "--output", required=True)
    p.set_defaults(func=cmd_palettize)

    # repair
    p = sub.add_parser("repair", help="Fix pixel grid alignment")
    p.add_argument("input")
    p.add_argument("--pixel-size", type=int, default=8)
    p.add_argument("--auto", action="store_true", help="Auto-detect pixel size")
    p.add_argument("--upscale", action="store_true", help="Upscale back to original size")
    p.add_argument("-o", "--output", required=True)
    p.set_defaults(func=cmd_repair)

    # detect
    p = sub.add_parser("detect", help="Detect pixel grid size")
    p.add_argument("input")
    p.set_defaults(func=cmd_detect)

    # spritesheet
    p = sub.add_parser("spritesheet", help="Assemble frames into sheet")
    p.add_argument("--input-dir", required=True, help="Directory of PNG frames")
    p.add_argument("--columns", type=int, default=4)
    p.add_argument("-o", "--output", required=True)
    p.set_defaults(func=cmd_spritesheet)

    # animate (extract frames)
    p = sub.add_parser("animate", help="Extract frames from sheet")
    p.add_argument("input", help="Sprite sheet PNG")
    p.add_argument("--columns", type=int, required=True)
    p.add_argument("--rows", type=int, required=True)
    p.add_argument("-o", "--output-dir", required=True)
    p.set_defaults(func=cmd_animate)

    # gif
    p = sub.add_parser("gif", help="Create animated GIF from frames or sprite sheet")
    p.add_argument("--input-dir", help="Directory of PNG frames")
    p.add_argument("--sheet", help="Sprite sheet PNG")
    p.add_argument("--columns", type=int, default=4)
    p.add_argument("--rows", type=int, default=4)
    p.add_argument("--fps", type=int, default=8)
    p.add_argument("-o", "--output", required=True)
    p.set_defaults(func=cmd_gif)

    # list palettes
    p = sub.add_parser("palettes", help="List built-in palettes")
    p.set_defaults(func=cmd_palettes)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
