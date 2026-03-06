import os
import re
import difflib
import subprocess
import shutil
import numpy as np
import csv
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import webbrowser
import time
from faster_whisper import WhisperModel
import warnings
warnings.filterwarnings("ignore")
try:
    from moviepy.video.io.VideoFileClip import VideoFileClip
    from moviepy.video.compositing.CompositeVideoClip import CompositeVideoClip
    from moviepy.video.compositing.concatenate import concatenate_videoclips
    from moviepy.video.VideoClip import ColorClip, ImageClip, VideoClip
    from moviepy.audio.AudioClip import CompositeAudioClip, AudioClip
    from moviepy.audio.io.AudioFileClip import AudioFileClip
except ImportError:
    # Fallback for different MoviePy versions
    print("Specific imports failed, falling back to generic moviepy or moviepy.editor...")
    try:
        from moviepy import VideoFileClip, AudioFileClip, CompositeVideoClip, concatenate_videoclips, ColorClip, ImageClip, VideoClip, CompositeAudioClip, AudioClip
    except ImportError:
        from moviepy.editor import VideoFileClip, AudioFileClip, CompositeVideoClip, concatenate_videoclips, ColorClip, ImageClip, VideoClip, CompositeAudioClip, AudioClip



# --- FFMPEG ---

# --- CONFIG ---
CURRENT_DIR = Path(__file__).parent
VIDEO_DIR = CURRENT_DIR / "input"
MERGED_AUDIO_PATH = VIDEO_DIR / "audio.mp3"
TOP_IMAGE_PATH = VIDEO_DIR / "top_image.png"
SCRIPT_FILE = VIDEO_DIR / "text.txt"
BG_IMAGE_PATH = CURRENT_DIR / "image_background" / "ChatGPT Image 13_35_23 23 thg 1, 2026.png"
OUTPUT_FILE = CURRENT_DIR / "final_split_screen_optimized.mp4"
TEMP_DIR = CURRENT_DIR / "temp"
TEMP_DIR.mkdir(exist_ok=True)

VIDEO_WIDTH = 1080
VIDEO_HEIGHT = 1920
TOP_HEIGHT = int(VIDEO_HEIGHT * 0.3)
BOTTOM_HEIGHT = VIDEO_HEIGHT - TOP_HEIGHT

FONT_PATH = "arialbd.ttf"
FONT_SIZE_SCENE_1 = 55
FONT_SIZE_SCENE_2 = 40 
TEXT_ALIGN = "justify"  # "center" | "left" | "justify"
JUSTIFY_MAX_GAP_MULT = 3.0  # avoid overly wide gaps on short lines
DEFAULT_SEGMENT_GAP = 0.12
DEBUG_TIMING = True
SPLIT_MARKER_PHRASE = "Please listen carefully"

# --- PACING ---
PRE_ROLL = 0.08          # small lead-in to avoid abrupt starts
POST_ROLL_SCENE_1 = 0.08 # slight tail for intro segments
POST_ROLL_SCENE_2 = 0.00 # keep scene 2 flowing
SCENE1_END_PAUSE = 0.00  # no pause after marker
SCENE2_END_PAUSE = 0.25  # short tail after last line

# --- CONFIG & WHISPER ---


device = "cuda" if os.environ.get("CUDA_VISIBLE_DEVICES") != "-1" else "cpu"
WHISPER_MODEL = WhisperModel("large-v3", device=device, compute_type="float16" if device=="cuda" else "int8")

def get_timings(audio_path):
    print(f"  [STT] Analyzing {os.path.basename(audio_path)}...")
    segments, _ = WHISPER_MODEL.transcribe(audio_path, word_timestamps=True)
    all_words = []
    for s in segments:
        if s.words:
            for w in s.words:
                all_words.append({'word': w.word.strip(), 'start': w.start, 'end': w.end})
    if not all_words: return 0.0, 0.0, []
    return all_words[0]['start'], all_words[-1]['end'], all_words

def strip_wrapping_quotes(value):
    v = value.strip()
    if len(v) >= 2 and ((v[0] == v[-1]) and v[0] in ['"', "'"]):
        return v[1:-1].strip()
    return v

def parse_text_file(path):
    if not path.exists():
        raise FileNotFoundError(f"Text file not found: {path}")
    intro = ""
    title = ""
    description = ""
    outro = ""
    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            m = re.match(r'^(intro|into|title|description|outro)\s*:\s*(.*)$', line, re.IGNORECASE)
            if not m:
                continue
            key = m.group(1).lower()
            value = strip_wrapping_quotes(m.group(2))
            if key in ("intro", "into"):
                intro = value
            elif key == "title":
                title = value
            elif key == "description":
                description = value
            elif key == "outro":
                outro = value
    return intro, title, description, outro



def split_video_segment(video_path, split_text_marker):
    orig_clip = VideoFileClip(str(video_path))
    temp_wav = TEMP_DIR / "split_analysis.wav"
    orig_clip.audio.write_audiofile(str(temp_wav), logger=None)
    segments, _ = WHISPER_MODEL.transcribe(str(temp_wav), word_timestamps=True)
    all_words = [w for s in segments for w in s.words]
    split_time = orig_clip.duration / 2
    
    clean_marker = split_text_marker.replace(".","").lower().strip()
    for w in all_words:
        if clean_marker in w.word.lower():
            split_time = w.end
            break
            
    print(f"  [SPLIT] {video_path.name} at {split_time:.2f}s")
    return subclip_safe(orig_clip, 0, split_time), subclip_safe(orig_clip, split_time, orig_clip.duration)

def subclip_safe(clip, t_start, t_end):
    try:
        return clip.subclipped(t_start, t_end)
    except AttributeError:
        return clip.subclip(t_start, t_end)

def subclip_audio_safe(clip, t_start, t_end):
    try:
        return clip.subclipped(t_start, t_end)
    except AttributeError:
        return clip.subclip(t_start, t_end)

def trim_to_speech(clip, start, end, pre_roll, post_roll):
    if end <= start:
        return clip, start, end
    seg_start = max(0.0, start - pre_roll)
    seg_end = min(clip.duration, end + post_roll)
    if seg_end - seg_start < 0.1:
        return clip, start, end
    trimmed = subclip_safe(clip, seg_start, seg_end)
    adj_start = max(0.0, start - seg_start)
    adj_end = max(adj_start, end - seg_start)
    return trimmed, adj_start, adj_end

def pad_audio_to_duration(audio_clip, target_duration, fallback_fps=44100):
    if audio_clip is None:
        return AudioClip(lambda t: 0, duration=target_duration, fps=fallback_fps)
    if audio_clip.duration >= target_duration:
        return audio_clip
    fps = getattr(audio_clip, "fps", None) or fallback_fps
    silence = AudioClip(lambda t: 0, duration=target_duration - audio_clip.duration, fps=fps)
    return CompositeAudioClip([audio_clip, silence.with_start(audio_clip.duration)]).with_duration(target_duration)

def get_word_timings_for_audio(audio_clip, out_path):
    audio_clip.write_audiofile(str(out_path), logger=None)
    _, _, words = get_timings(str(out_path))
    return words

def make_freeze_clip(clip, duration, fps=44100):
    freeze = clip.to_ImageClip(t=max(0, clip.duration-0.1)).with_duration(duration)
    silence = AudioClip(lambda t: 0, duration=duration, fps=fps)
    return freeze.with_audio(silence)

def slice_timings(words, t_start, t_end):
    sliced = []
    for w in words:
        if w['end'] < t_start or w['start'] > t_end:
            continue
        s = max(w['start'], t_start) - t_start
        e = min(w['end'], t_end) - t_start
        sliced.append({'word': w['word'], 'start': s, 'end': e})
    return sliced

def normalize_token(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())

def tokenize_text(text):
    raw = re.findall(r"[A-Za-z0-9']+", text.lower())
    tokens = []
    for t in raw:
        nt = normalize_token(t)
        if nt:
            tokens.append(nt)
    return tokens

def filter_words_by_time(words, t_start, t_end):
    sliced = []
    for w in words:
        if w["end"] < t_start or w["start"] > t_end:
            continue
        sliced.append(w)
    return sliced

def write_word_timings_csv(words, path):
    with open(path, "w", encoding="utf-8") as f:
        f.write("idx,word,start,end,duration\n")
        for i, w in enumerate(words):
            start = float(w.get("start", 0.0))
            end = float(w.get("end", 0.0))
            word = str(w.get("word", "")).replace('"', '""')
            f.write(f'{i},"{word}",{start:.3f},{end:.3f},{(end-start):.3f}\n')

def read_word_timings_csv(path):
    print(f"  [CSV] Reading timings from {path}...")
    words = []
    if not os.path.exists(path):
         print(f"  [ERROR] File not found: {path}")
         return []
         
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                words.append({
                    "word": row["word"],
                    "start": float(row["start"]),
                    "end": float(row["end"])
                })
            except ValueError:
                continue
    return words

def find_split_time(words, marker):
    def norm_word(s):
        return re.sub(r"[^a-z0-9]", "", s.lower())
    target = norm_word(marker)
    for w in words:
        if norm_word(w['word']) == target:
            return w['end']
    return None

def find_split_time_phrase(words, phrase):
    tokens = [normalize_token(w['word']) for w in words if normalize_token(w['word'])]
    ends = [w['end'] for w in words if normalize_token(w['word'])]
    phrase_tokens = tokenize_text(phrase)
    if not phrase_tokens or not tokens:
        return None
    n = len(phrase_tokens)
    for i in range(len(tokens) - n + 1):
        if tokens[i:i+n] == phrase_tokens:
            return ends[i + n - 1]
    return None



# --- VISUAL ENGINE ---
def create_text_layout(text, width, height, font_size, color, title_text=None, align="center"):
    img = Image.new('RGBA', (width, height), (0,0,0,0))
    draw = ImageDraw.Draw(img)
    def load_font(size):
        try:
            return ImageFont.truetype(FONT_PATH, size)
        except Exception:
            return ImageFont.load_default()

    font = load_font(font_size)
    
    # Title
    start_y = 0
    if title_text:
        t_font = load_font(int(font_size*1.6))
        lines = []
        c_line = []
        for w in title_text.split():
            if draw.textbbox((0,0), " ".join(c_line+[w]), font=t_font)[2] < width*0.9: c_line.append(w)
            else: lines.append(c_line); c_line = [w]
        if c_line: lines.append(c_line)
        
        y = 50
        for l in lines:
            ls = " ".join(l)
            bb = draw.textbbox((0,0), ls, font=t_font)
            lx = (width - (bb[2]-bb[0]))//2
            draw.text((lx, y), ls, font=t_font, fill=color)
            y += int(font_size*2)
        start_y = y + 40
        
    # Optimized Text Layout (auto-fit if text is too long)
    max_w = width - 160 # Increased margin (was 100) -> 80px padding each side
    available_height = height - start_y - 20
    if available_height < 60:
        available_height = height - start_y

    def build_lines(active_font):
        lines = []; c_line = []
        def get_wh(t):
            b = draw.textbbox((0,0), t, font=active_font)
            return (b[2]-b[0]), (b[3]-b[1])
        words = text.split()
        for w in words:
            if get_wh(" ".join(c_line + [w]))[0] <= max_w: c_line.append(w)
            else: lines.append(c_line); c_line = [w]
        if c_line: lines.append(c_line)
        return lines, get_wh

    body_font_size = font_size
    line_spacing_factor = 2.0
    while True:
        font = load_font(body_font_size)
        lines, get_wh = build_lines(font)
        try:
            ascent, descent = font.getmetrics()
            base_line_h = ascent + descent
        except Exception:
            base_line_h = get_wh("Ag")[1]
        total_h = (base_line_h * line_spacing_factor) * len(lines)
        if total_h <= available_height or body_font_size <= 18:
            break
        body_font_size -= 2

    if total_h > available_height and len(lines) > 0:
        line_spacing_factor = max(1.2, available_height / (base_line_h * len(lines)))
        total_h = (base_line_h * line_spacing_factor) * len(lines)

    if not title_text: start_y = (height - total_h)//2
    
    curr_y = start_y
    layout_items = []
    space_w, _ = get_wh(" ")
    left_margin = (width - max_w) // 2
    
    for li, line in enumerate(lines):
        # Alignment per line
        sum_word_w = sum([get_wh(w)[0] for w in line])
        gap = space_w
        if align == "center":
            line_w = sum_word_w + gap * (len(line) - 1)
            curr_x = (width - line_w) // 2
        elif align == "justify":
            if len(line) > 1 and li < len(lines) - 1:
                extra = max_w - sum_word_w
                gap = extra / (len(line) - 1) if extra > 0 else space_w
                if gap > space_w * JUSTIFY_MAX_GAP_MULT:
                    gap = space_w
                curr_x = left_margin
            else:
                curr_x = left_margin
        else:
            curr_x = left_margin
            
        # 3. Draw Words (uniform line height for smoother highlight boxes)
        lh = base_line_h
        line_top = curr_y
        line_bottom = curr_y + lh
        for w in line:
            ww, _ = get_wh(w)
            draw.text((int(round(curr_x)), int(round(curr_y))), w, font=font, fill=color)
            
            p_x = 10; p_y = 8
            layout_items.append({
                'text': w,
                'bbox': (curr_x - p_x, line_top - p_y, curr_x + ww + p_x, line_bottom + p_y),
                'line': li
            })
            
            curr_x += ww + gap
            
        curr_y += lh * line_spacing_factor
        
    return img, layout_items

# --- Custom Dynamic Clip Class ---
class HighlightRenderer(VideoClip):
    def __init__(self, timings, layout, box_color, size, duration, direction="ltr"):
        super().__init__()
        self.timings = timings
        self.layout = layout
        self.box_color = box_color
        self.size = size
        self.duration = duration
        self.direction = direction
        # Cache per-line vertical bounds for smooth merged highlights
        self.line_bounds = {}
        for item in self.layout:
            line = item.get("line", 0)
            y1 = item["bbox"][1]
            y2 = item["bbox"][3]
            if line not in self.line_bounds:
                self.line_bounds[line] = [y1, y2]
            else:
                self.line_bounds[line][0] = min(self.line_bounds[line][0], y1)
                self.line_bounds[line][1] = max(self.line_bounds[line][1], y2)
        # MoviePy v2 expects frame_function; v1 uses make_frame
        self.frame_function = self.make_frame
        
    def make_frame(self, t):
        # Create transparent frame
        frame_img = Image.new('RGBA', self.size, (0,0,0,0))
        draw = ImageDraw.Draw(frame_img)

        # Build highlight segments per line using per-word start/end timings.
        segments_by_line = {line: [] for line in self.line_bounds.keys()}
        for i, item in enumerate(self.layout):
            timing = self.timings[i]
            start = timing["start"]
            end = timing["end"]
            if t < start:
                continue

            x1, y1, x2, y2 = item["bbox"]
            w = max(0.0, x2 - x1)
            line = item.get("line", 0)
            if line not in segments_by_line:
                segments_by_line[line] = []

            if t >= end or end <= start:
                left, right = x1, x2
            else:
                # Partial fill for the current word.
                progress = (t - start) / max(end - start, 1e-6)
                progress = min(1.0, max(0.0, progress))
                if self.direction == "rtl":
                    left = x2 - (w * progress)
                    right = x2
                else:
                    left = x1
                    right = x1 + (w * progress)

            if right - left >= 1.0:
                segments_by_line[line].append((left, right))

        # Draw connectors between adjacent words on the same line.
        # Connector animates during the gap between words (after previous word ends).
        for i in range(len(self.layout) - 1):
            if self.layout[i].get("line") != self.layout[i + 1].get("line"):
                continue
            line = self.layout[i].get("line", 0)
            prev_end = self.timings[i]["end"]
            next_start = self.timings[i + 1]["start"]
            if t <= prev_end:
                continue
            gap_left = self.layout[i]["bbox"][2]
            gap_right = self.layout[i + 1]["bbox"][0]
            if gap_right <= gap_left:
                continue
            if next_start <= prev_end:
                progress = 1.0
            else:
                progress = (t - prev_end) / max(next_start - prev_end, 1e-6)
                progress = min(1.0, max(0.0, progress))
            if progress <= 0.0:
                continue
            conn_right = gap_left + (gap_right - gap_left) * progress
            if conn_right - gap_left >= 1.0:
                if line not in segments_by_line:
                    segments_by_line[line] = []
                segments_by_line[line].append((gap_left, conn_right))

        # Merge segments per line and draw a single rounded shape for smooth edges
        merge_eps = 0.5
        for line, segments in segments_by_line.items():
            if not segments:
                continue
            segments.sort(key=lambda s: s[0])
            merged = []
            cur_l, cur_r = segments[0]
            for l, r in segments[1:]:
                if l <= cur_r + merge_eps:
                    cur_r = max(cur_r, r)
                else:
                    merged.append((cur_l, cur_r))
                    cur_l, cur_r = l, r
            merged.append((cur_l, cur_r))

            y1, y2 = self.line_bounds.get(line, (0, 0))
            h = max(0.0, y2 - y1)
            for l, r in merged:
                w = max(0.0, r - l)
                if w < 1.0 or h < 1.0:
                    continue
                radius = min(12, w / 2.0, h / 2.0)
                draw.rounded_rectangle((l, y1, r, y2), radius=radius, fill=self.box_color)
        return np.array(frame_img)

def build_word_timings(layout, karaoke_timings):
    def tokenize(s):
        return re.findall(r"[A-Za-z0-9]+", s.lower())

    layout_tokens = []
    for idx, item in enumerate(layout):
        toks = tokenize(item['text'])
        if toks:
            for t in toks:
                layout_tokens.append((t, idx))

    timing_tokens = []
    timing_starts = []
    timing_ends = []
    for kw in karaoke_timings:
        toks = tokenize(kw['word'])
        for t in toks:
            timing_tokens.append(t)
            timing_starts.append(kw['start'])
            timing_ends.append(kw['end'])

    if not layout_tokens or not timing_tokens:
        # Fallback: evenly spaced timings
        default_dur = 0.15
        t = 0.0
        times = []
        for _ in range(len(layout)):
            times.append({'start': t, 'end': t + default_dur})
            t += default_dur
        return times

    sm = difflib.SequenceMatcher(
        a=[t for t, _ in layout_tokens],
        b=timing_tokens,
        autojunk=False
    )

    word_times = [{'start': None, 'end': None} for _ in range(len(layout))]
    for i, j, n in sm.get_matching_blocks():
        for k in range(n):
            li = layout_tokens[i + k][1]
            ts = timing_starts[j + k]
            te = timing_ends[j + k]
            if word_times[li]['start'] is None or ts < word_times[li]['start']:
                word_times[li]['start'] = ts
            if word_times[li]['end'] is None or te > word_times[li]['end']:
                word_times[li]['end'] = te

    # Compute a reasonable default duration from known words
    known_durs = [
        wt['end'] - wt['start']
        for wt in word_times
        if wt['start'] is not None and wt['end'] is not None and wt['end'] > wt['start']
    ]
    default_dur = float(np.median(known_durs)) if known_durs else 0.15
    default_dur = max(0.08, min(default_dur, 0.6))
    min_dur = 0.04

    # Fill missing times and enforce non-decreasing order
    prev_end = 0.0
    for i in range(len(word_times)):
        s = word_times[i]['start']
        e = word_times[i]['end']

        if s is None and e is None:
            s = prev_end
            e = s + default_dur
        elif s is None:
            s = max(prev_end, e - default_dur)
        elif e is None:
            e = s + default_dur

        if s < prev_end:
            s = prev_end
        if e < s + min_dur:
            e = s + min_dur

        word_times[i]['start'] = s
        word_times[i]['end'] = e
        prev_end = e

    # 2nd pass: Smart Gap Filling (Continuous Flow within Sentences)
    # Logic: If a word does NOT end with sentence-ending punctuation, 
    # extend its duration to touch the next word. This removes "flickering" gaps.
    sentence_endings = ('.', '!', '?', ':', ';', ',') # Treat comma as mild break, but maybe fill if short?
    # Let's strictly fill for non-punctuation, and conditionally fill commas if gap is small.
    
    for i in range(len(word_times) - 1):
        curr = word_times[i]
        nxt = word_times[i+1]
        
        # Get the text from layout to check punctuation
        # layout items are usually words like "Hello," or "World."
        raw_text = layout[i]['text'].strip()
        
        has_punctuation = raw_text.endswith(sentence_endings)
        
        if curr['end'] is not None and nxt['start'] is not None:
             gap = nxt['start'] - curr['end']
             
             # If gap is valid
             if gap > 0:
                 # RULE 1: If NO punctuation, Always fill the gap (make it continuous)
                 if not has_punctuation:
                     curr['end'] = nxt['start']
                     
                 # RULE 2: If it behaves like a comma (short pause), limit the gap
                 elif raw_text.endswith(','):
                     # If gap is huge (e.g. > 0.8s), keep it. If small, fill it to look smoother.
                     if gap < 0.4:
                         curr['end'] = nxt['start']
                 
                 # RULE 3: Sentence endings (., !, ?) PRESERVE the gap/silence
                 # (No action needed, gap remains)

    # 3rd pass: Global Sync Offset (Fix 'Karaoke faster than Audio')
    # Whisper timestamps are 'technical starts' (onset). 
    # Human perception lags slightly. We delay visuals to match the 'vowel center'.
    # +0.14s is usually the sweet spot for English speech.
    SYNC_OFFSET = 0.14
    for wt in word_times:
        if wt['start'] is not None:
            wt['start'] += SYNC_OFFSET
        if wt['end'] is not None:
            wt['end'] += SYNC_OFFSET
            
    return word_times

def render_split_scene(image_top_path, audio_clip, text_content, karaoke_timings, font_size, text_color, box_color, use_paper_bg=False, title_text=None, align="center"):
    duration = audio_clip.duration
    
    # 1. TOP IMAGE
    top_img_clip = ImageClip(str(image_top_path))
    ratio_vid = top_img_clip.w / top_img_clip.h
    ratio_slot = VIDEO_WIDTH / TOP_HEIGHT
    if ratio_vid > ratio_slot:
        vid = top_img_clip.resized(height=TOP_HEIGHT)
        vid_layer = vid.cropped(x1=(vid.w - VIDEO_WIDTH)//2, width=VIDEO_WIDTH)
    else:
        vid = top_img_clip.resized(width=VIDEO_WIDTH)
        vid_layer = vid.cropped(y1=(vid.h - TOP_HEIGHT)//2, height=TOP_HEIGHT)
    vid_layer = vid_layer.with_duration(duration).with_position(('center', 'top'))

    # 2. BOTTOM BG
    if use_paper_bg and BG_IMAGE_PATH.exists():
        bg_img = ImageClip(str(BG_IMAGE_PATH))
        new_w = VIDEO_WIDTH
        bgb = bg_img.resized(width=new_w)
        if bgb.h > BOTTOM_HEIGHT: bgb = bgb.cropped(y1=(bgb.h-BOTTOM_HEIGHT)//2, height=BOTTOM_HEIGHT)
        else: bgb = bgb.resized(height=BOTTOM_HEIGHT).cropped(x1=(bgb.w-VIDEO_WIDTH)//2, width=VIDEO_WIDTH)
        bg_bottom = bgb.with_duration(duration).with_position(('center', 'bottom'))
    else:
        bg_bottom = ColorClip(size=(VIDEO_WIDTH, BOTTOM_HEIGHT), color=(20,20,20)).with_duration(duration).with_position(('center', 'bottom'))

    # 3. TEXT & HIGHLIGHTS
    img_text, layout = create_text_layout(text_content, VIDEO_WIDTH, BOTTOM_HEIGHT, font_size, text_color, title_text, align=align)
    clip_text = ImageClip(np.array(img_text)).with_duration(duration).with_position((0, TOP_HEIGHT))
    
    # Prepare Matches
    word_timings = build_word_timings(layout, karaoke_timings)
    
    # 4. INSTANTIATE CUSTOM RENDERER
    highlight_clip = HighlightRenderer(
        timings=word_timings, 
        layout=layout, 
        box_color=box_color, 
        size=(VIDEO_WIDTH, BOTTOM_HEIGHT), 
        duration=duration,
        direction="ltr"
    ).with_position((0, TOP_HEIGHT))
    
    final = CompositeVideoClip(
        [vid_layer, bg_bottom, highlight_clip, clip_text],
        size=(VIDEO_WIDTH, VIDEO_HEIGHT)
    ).with_audio(audio_clip).with_duration(duration)
    return final

def find_content_end_time(words, text):
    """
    Finds the end timestamp of the last word in 'words' that matches 'text'.
    Used to trim trailing audio (outros) not in the script.
    """
    text_tokens = tokenize_text(text)
    audio_tokens = [normalize_token(w['word']) for w in words]
    audio_ends = [w['end'] for w in words]
    
    if not text_tokens or not audio_tokens:
        return None
        
    sm = difflib.SequenceMatcher(None, text_tokens, audio_tokens)
    last_match_end_idx = -1
    
    for _, j, n in sm.get_matching_blocks():
        if n > 0:
            current_last = j + n - 1
            if current_last > last_match_end_idx:
                last_match_end_idx = current_last
                
    if last_match_end_idx != -1 and last_match_end_idx < len(audio_ends):
        return audio_ends[last_match_end_idx]
    return None

def main():
    print("--- 2-Scene Unified Style Split Screen Generator ---")
    
    intro_text, title_text, description_text, outro_text = parse_text_file(SCRIPT_FILE)
    if not intro_text:
        raise ValueError("INTRO not found in text.txt (expected Intro/Into: ...)")
    if not description_text:
        raise ValueError("DESCRIPTION not found in text.txt")

    SCENE_1_TEXT = intro_text
    SCENE_2_TEXT = description_text
    TITLE_TEXT = title_text
    final_clips = []

    # --- Load Audio ---
    print("\n--- Loading Audio ---")
    audio_path = MERGED_AUDIO_PATH
    if not audio_path.exists():
        # Try to find mp4 as fallback, or mp3, wav.
        mp3s = sorted(VIDEO_DIR.glob("*.mp3"))
        wavs = sorted(VIDEO_DIR.glob("*.wav"))
        mp4s = sorted(VIDEO_DIR.glob("*.mp4"))
        
        if mp3s:
            audio_path = mp3s[0]
        elif wavs:
            audio_path = wavs[0]
        elif mp4s:
            # Load video just to get audio over it
            print(f"[INFO] Using {mp4s[0].name} for audio track.")
            full_audio = VideoFileClip(str(mp4s[0])).audio
            audio_path = None
        else:
            raise FileNotFoundError(f"No audio file (mp3/wav) found in: {VIDEO_DIR}")

    if audio_path is not None:
        full_audio = AudioFileClip(str(audio_path))
    
    # 1. GENERATE TIMINGS
    manual_csv_path = CURRENT_DIR / "manual_timings.csv"
    
    # FORCE FRESH START
    if manual_csv_path.exists():
        try:
            manual_csv_path.unlink()
            print("[INFO] Cleared previous manual_timings.csv to force fresh edit.")
        except Exception as e:
            print(f"[WARN] Could not delete old CSV: {e}")

    print("\n[INFO] Running Whisper Analysis...")
    full_words = get_word_timings_for_audio(full_audio, TEMP_DIR / "full_orig.wav")
        
    # 2. MANUAL CHECKPOINT
    write_word_timings_csv(full_words, manual_csv_path)
    print("\n" + "="*60)
    print(f"  [MANUAL CHECK] Timings initial draft saved to: {manual_csv_path.name}")
    print("  LAUNCHING EDITOR SERVER AUTOMATICALLY...")
    print("="*60)
    
    # --- AUTO-LAUNCH EDITOR SUBPROCESS ---
    import subprocess
    import sys
    editor_process = None
    try:
        editor_process = subprocess.Popen([sys.executable, "launch_editor.py"], cwd=CURRENT_DIR)
        
        print("\n  >>> EDITOR IS RUNNING. Please edit in browser.")
        print("  >>> Click 'SAVE & FINISH' in browser to CONTINUE automatically.")
        
        editor_process.wait()
        print("  [INFO] Editor finished. Resuming rendering...")
        
    finally:
        if editor_process:
            print("  [INFO] Closing Editor Server...")
            editor_process.terminate()
            editor_process.wait()

    
    # 3. RELOAD TIMINGS
    full_words = read_word_timings_csv(manual_csv_path)
    if not full_words:
        raise ValueError("Loaded empty timings! Please check your CSV file.")

    # 4. RENDER SINGLE SCENE
    
    # Use TITLE_TEXT + SCENE_2_TEXT over the whole duration
    # If there is also intro text from the script file you want to include,
    # you can concatenate it if needed. For now, assuming only 1 scene with all text.
    FULL_TEXT = description_text
    TITLE_TEXT = title_text
    
    # Trim out parts not in the text
    content_end = find_content_end_time(full_words, FULL_TEXT)
    if content_end is not None:
        trim_end = content_end + 0.5
        if trim_end < full_audio.duration:
            print(f"  [TRIM] Detected content end at {content_end:.2f}s. Trimming silence.")
            full_audio = subclip_audio_safe(full_audio, 0, trim_end)
            full_words = [w for w in full_words if w['end'] <= trim_end]
            
    if SCENE2_END_PAUSE > 0:
        full_audio = pad_audio_to_duration(full_audio, full_audio.duration + SCENE2_END_PAUSE)

    print("  [RENDER] Processing Single Scene Layout & Clip...")
    # Assume image is required
    top_image_to_use = TOP_IMAGE_PATH
    if not top_image_to_use.exists():
        # fallback black if no image
        print("[WARN] TOP_IMAGE_PATH not found, falling back to black background")
        bg_top = ColorClip(size=(VIDEO_WIDTH, TOP_HEIGHT), color=(0,0,0)).with_duration(full_audio.duration).with_position(('center', 'top'))
        
        # We need to change render_split_scene back temporarily or mock it.
        # It's better to just pass the image. Let's create a black image.
        black_img = Image.new('RGB', (VIDEO_WIDTH, TOP_HEIGHT), color=(0,0,0))
        black_img_path = TEMP_DIR / "black_top.png"
        black_img.save(black_img_path)
        top_image_to_use = black_img_path
        
    final_clip = render_split_scene(
        top_image_to_use, full_audio, FULL_TEXT, full_words, FONT_SIZE_SCENE_2,
        text_color=(20,20,20,255), box_color=(210, 120, 50, 200),
        use_paper_bg=True, title_text=TITLE_TEXT, align=TEXT_ALIGN
    )
    
    print(f"  [RENDER] Writing video to: {OUTPUT_FILE}")
    final_clip.write_videofile(str(OUTPUT_FILE), fps=24, codec='libx264', audio_codec='aac', ffmpeg_params=['-pix_fmt', 'yuv420p'])
    
    print(f"  [RENDER] Writing video to: {OUTPUT_FILE}")
    final.write_videofile(str(OUTPUT_FILE), fps=24, codec='libx264', audio_codec='aac', ffmpeg_params=['-pix_fmt', 'yuv420p'])
    print(f"DONE: {OUTPUT_FILE}")

    # CLEANUP
    files_to_clean = [
        manual_csv_path,
        CURRENT_DIR / "temp_viz_audio.mp3",
        TEMP_DIR / "full_orig.wav"
    ]
    
    print("[INFO] Cleaning up temporary files...")
    for f in files_to_clean:
        if f.exists():
            try:
                f.unlink()
                print(f"  - Deleted: {f.name}")
            except Exception as e:
                print(f"  [WARN] Failed to delete {f.name}: {e}")

if __name__ == "__main__":
    main()
