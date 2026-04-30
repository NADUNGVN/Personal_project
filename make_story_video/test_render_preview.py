"""
test_render_preview.py — Visual preview
Fixes: 
- Justify text
- Solid black background
- Image "full" (padded to fit 1920x1080 without crop)
- Karaoke highlight: orange background box sweeping left-to-right, staying orange after swept
"""
import json, os, re, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

BASE_DIR           = os.path.dirname(os.path.abspath(__file__))
STORY_DETAILS_FILE = os.path.join(BASE_DIR, "input", "story_details.json")
IMAGE_INPUT_PATH   = os.path.join(BASE_DIR, "input", "img", "Gemini_Generated_Image_4wgdq54wgdq54wgd.png")
OUTPUT_DIR         = os.path.join(BASE_DIR, "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)
OUT_FILE = os.path.join(OUTPUT_DIR, "preview_test.mp4")

VIDEO_W, VIDEO_H = 1920, 1080
IMAGE_H          = int(VIDEO_H * 2 / 3)   # 720
TEXT_PANEL_H     = VIDEO_H - IMAGE_H       # 360
TEXT_PANEL_Y     = IMAGE_H

FONT_SIZE        = 34
LINE_GAP         = 20
TEXT_MARGIN_X    = 80
LINES_PER_PANEL  = 5

COLOR_BG          = (255, 255, 255)
COLOR_TEXT        = (0, 0, 0)
COLOR_BOX         = (255, 140, 0) # Orange highlight box

PREVIEW_SEC   = 30
WPM           = 130
OUTPUT_FPS    = 24


# ── helpers ──────────────────────────────────────────────────────────────────
def load_font(size):
    for p in [r"C:\Windows\Fonts\segoeuib.ttf", r"C:\Windows\Fonts\arialbd.ttf", r"C:\Windows\Fonts\calibrib.ttf"]:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()

def prepare_image(path):
    img = Image.open(path).convert("RGB")
    sw, sh = img.size
    # "full bề ngang": scale width to exactly VIDEO_W
    scale = VIDEO_W / sw
    new_w = VIDEO_W
    new_h = int(sh * scale)
    img = img.resize((new_w, new_h), Image.LANCZOS)
    
    if new_h >= IMAGE_H:
        # crop vertically center
        t = (new_h - IMAGE_H) // 2
        return img.crop((0, t, VIDEO_W, t + IMAGE_H))
    else:
        # pad vertically
        res = Image.new("RGB", (VIDEO_W, IMAGE_H), (0,0,0))
        t = (IMAGE_H - new_h) // 2
        res.paste(img, (0, t))
        return res

def fake_timestamps(synopsis, max_words):
    words = re.findall(r"\S+", synopsis)[:max_words]
    spw = 60.0 / WPM; t = 0.5; out = []
    for w in words:
        dur = spw*(1.4 if w[-1] in ".!?" else 1.15 if w[-1] in ",;:" else 1.0)
        out.append({"word":w,"start":round(t,3),"end":round(t+dur*0.85,3)}); t+=dur
    return out

def wrap_and_justify(words, font, max_w, x_offset):
    sp = font.getlength(" ")
    lines = []; cur = []; cw = 0.0
    
    # 1. Wrap into lines
    for w in words:
        ww = font.getlength(w["word"])
        if cur and cw + sp + ww > max_w:
            lines.append(cur); cur = [w]; cw = ww
        else:
            cur.append(w); cw += (sp + ww) if cur[:-1] else ww
    if cur: lines.append(cur)
    
    # 2. Assign X coordinates (Justify)
    positioned_lines = []
    for line in lines:
        total_word_w = sum(font.getlength(w["word"]) for w in line)
        if len(line) > 1:
            gap = (max_w - total_word_w) / (len(line) - 1)
            # If gap is too large (likely last line of paragraph), don't justify fully
            if gap > sp * 3.5:
                gap = sp
                start_x = x_offset + (max_w - (total_word_w + gap * (len(line) - 1))) / 2
            else:
                start_x = x_offset
        else:
            gap = sp
            start_x = x_offset + (max_w - total_word_w) / 2
            
        pos_line = []
        x = start_x
        for w in line:
            ww = font.getlength(w["word"])
            pos_line.append({
                "word": w["word"],
                "start": w["start"],
                "end": w["end"],
                "x": x,
                "w": ww
            })
            x += ww + gap
        positioned_lines.append(pos_line)
    return positioned_lines

def to_panels(lines, n):
    return [{"lines":lines[i:i+n],
             "start":lines[i][0]["start"],
             "end":lines[min(i+n,len(lines))-1][-1]["end"]}
            for i in range(0,len(lines),n)]

# ── frame composer ────────────────────────────────────────────────────────────
def make_composer(image_panel, panels, font, total_dur):
    base = Image.new("RGB", (VIDEO_W, VIDEO_H), COLOR_BG)
    base.paste(image_panel, (0, 0))
    base_arr = np.array(base)
    line_h = FONT_SIZE + 10

    def make_frame(t):
        panel = None
        for p in panels:
            if p["start"] <= t <= p["end"] + 0.8: 
                panel = p; break
        if panel is None: 
            return base_arr.copy()

        img = Image.fromarray(base_arr.copy())
        draw = ImageDraw.Draw(img)
        
        lines = panel["lines"]
        total_h = len(lines) * line_h + (len(lines) - 1) * LINE_GAP
        start_y = TEXT_PANEL_Y + (TEXT_PANEL_H - total_h) // 2

        # 1. Draw orange highlight boxes connected
        for i, line in enumerate(lines):
            y = start_y + i * (line_h + LINE_GAP)
            y1 = y - 4
            y2 = y + line_h + 4
            segments = []
            
            for w_idx, w in enumerate(line):
                if t >= w["start"]:
                    if t >= w["end"] or w["end"] <= w["start"]:
                        prog = 1.0
                    else:
                        prog = min(1.0, max(0.0, (t - w["start"]) / (w["end"] - w["start"])))
                    
                    if prog > 0:
                        l = w["x"] - 6
                        r = w["x"] + w["w"] * prog + 6
                        segments.append((l, r))
                        
                # Gap segment to the next word
                if w_idx < len(line) - 1:
                    next_w = line[w_idx + 1]
                    prev_end = w["end"]
                    next_start = next_w["start"]
                    if t > prev_end:
                        if next_start <= prev_end:
                            prog = 1.0
                        else:
                            prog = min(1.0, max(0.0, (t - prev_end) / (next_start - prev_end)))
                        if prog > 0:
                            gap_left = w["x"] + w["w"] + 6
                            gap_right = next_w["x"] - 6
                            if gap_right > gap_left:
                                conn_right = gap_left + (gap_right - gap_left) * prog
                                segments.append((gap_left, conn_right))
                                
            if not segments:
                continue
                
            # Merge overlapping segments
            segments.sort(key=lambda s: s[0])
            merged = []
            cur_l, cur_r = segments[0]
            for l, r in segments[1:]:
                if l <= cur_r + 0.5:
                    cur_r = max(cur_r, r)
                else:
                    merged.append((cur_l, cur_r))
                    cur_l, cur_r = l, r
            merged.append((cur_l, cur_r))
            
            for l, r in merged:
                if r - l > 4:
                    try:
                        draw.rounded_rectangle((l, y1, r, y2), radius=8, fill=COLOR_BOX)
                    except:
                        draw.rectangle((l, y1, r, y2), fill=COLOR_BOX)

        # 2. Draw text
        for i, line in enumerate(lines):
            y = start_y + i * (line_h + LINE_GAP)
            for w in line:
                draw.text((w["x"], y), w["word"], font=font, fill=COLOR_TEXT)

        return np.array(img)

    return make_frame

# ── main ──────────────────────────────────────────────────────────────────────
def render_preview():
    from moviepy import VideoClip
    with open(STORY_DETAILS_FILE, encoding="utf-8") as f: 
        story = json.load(f)
    synopsis = story.get("synopsis", "")
    
    words = fake_timestamps(synopsis, len(re.findall(r"\S+", synopsis)))
    total = min(PREVIEW_SEC, words[-1]["end"] + 0.8)

    print(f"\n  {VIDEO_W}x{VIDEO_H} | {total:.0f}s | font={FONT_SIZE}px")
    img_panel = prepare_image(IMAGE_INPUT_PATH)
    font = load_font(FONT_SIZE)

    max_w = VIDEO_W - TEXT_MARGIN_X * 2
    lines = wrap_and_justify(words, font, max_w, TEXT_MARGIN_X)
    panels = to_panels(lines, LINES_PER_PANEL)
    print(f"  {len(words)} words | {len(lines)} lines | {len(panels)} panels")

    mf = make_composer(img_panel, panels, font, total)
    print("  Rendering ...")
    VideoClip(mf, duration=total).write_videofile(
        OUT_FILE, fps=OUTPUT_FPS, codec="libx264", audio=False,
        threads=4, ffmpeg_params=["-pix_fmt", "yuv420p"], logger=None)
    print(f"\n  [DONE] {OUT_FILE}\n")

if __name__ == "__main__":
    render_preview()
