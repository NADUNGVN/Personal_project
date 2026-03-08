import json
import math
import os

import numpy as np
from faster_whisper import WhisperModel
from moviepy import AudioFileClip, VideoClip
from PIL import Image, ImageDraw, ImageFont

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INPUT_DIR = os.path.join(BASE_DIR, "input")
CURRENT_OUT_DIR_FILE = os.path.join(INPUT_DIR, "current_output_dir.txt")

if os.path.exists(CURRENT_OUT_DIR_FILE):
    with open(CURRENT_OUT_DIR_FILE, "r", encoding="utf-8") as f:
        OUTPUT_DIR = f.read().strip()
else:
    OUTPUT_DIR = os.path.join(BASE_DIR, "output")

IMAGE_DIR = os.path.join(INPUT_DIR, "image")
IMAGE_INPUT_PATH = os.path.join(IMAGE_DIR, "image_input.png")
TOPICS_FILE = os.path.join(INPUT_DIR, "topics.txt")

SUBTITLE_FONT_SIZE = 30
SUBTITLE_Y_OFFSET = -250
SUBTITLE_MAX_WORDS_PER_SCREEN = 12

VIS_Y_OFFSET = -100
VIS_BAR_COUNT = 35
VIS_BAR_WIDTH = 7
VIS_BAR_SPACING = 3
VIS_MAX_HEIGHT = 150

TESTING_MODE = False
TESTING_DURATION_SEC = 60

SPEAKER_CONFIG = {
    "Sarah": {"color": "#FFE333"},
    "Alex": {"color": "#00FFFF"},
    "Emma": {"color": "#FFE333"},
    "Davis": {"color": "#00FFFF"},
    "Michael": {"color": "#FF9E80"},
    "Nicole": {"color": "#C5E1A5"},
    "Adam": {"color": "#B39DDB"},
    "Sky": {"color": "#80CBC4"},
    "Default": {"color": "#00FFFF"},
}


def calculate_log_bins(fft_data, sample_rate, chunk_size, num_bins, min_fq, max_fq):
    freqs = np.fft.rfftfreq(chunk_size, 1.0 / sample_rate)
    valid_indices = np.where((freqs >= min_fq) & (freqs <= max_fq))[0]
    if len(valid_indices) == 0:
        return np.zeros(num_bins)

    valid_fft = fft_data[valid_indices]
    valid_freqs = freqs[valid_indices]
    log_edges = np.geomspace(min_fq, max_fq, num_bins + 1)
    bins = np.zeros(num_bins)

    for i in range(num_bins):
        idx = np.where((valid_freqs >= log_edges[i]) & (valid_freqs < log_edges[i + 1]))[0]
        bins[i] = np.mean(valid_fft[idx]) if len(idx) > 0 else 0

    return bins


def get_target_podcast_files():
    if not os.path.exists(TOPICS_FILE):
        raise FileNotFoundError(f"Cannot find topics file: {TOPICS_FILE}")

    with open(TOPICS_FILE, "r", encoding="utf-8") as f:
        topics = [line.strip() for line in f if line.strip()]

    if not topics:
        raise ValueError("topics.txt is empty")

    topic_name = topics[0]
    safe_topic_name = "".join([c for c in topic_name if c.isalnum() or c == " "]).rstrip().replace(" ", "_")

    mp3_path = os.path.join(OUTPUT_DIR, f"{safe_topic_name}_podcast.mp3")
    json_path = os.path.join(OUTPUT_DIR, f"{safe_topic_name}_subtitles.json")

    if not os.path.exists(mp3_path):
        raise FileNotFoundError(f"Cannot find MP3: {mp3_path}")
    if not os.path.exists(json_path):
        raise FileNotFoundError(f"Cannot find subtitles JSON: {json_path}")

    return mp3_path, json_path, safe_topic_name


def extract_word_timestamps(audio_path, subtitles):
    import difflib
    import re

    print("Starting Faster-Whisper for word-level alignment...")
    model = WhisperModel("base.en", device="cuda", compute_type="float16")
    segments, _ = model.transcribe(audio_path, word_timestamps=True)

    whisper_words = []
    for segment in segments:
        for word in segment.words:
            whisper_words.append(
                {
                    "word": word.word.strip(),
                    "start": float(word.start),
                    "end": float(word.end),
                }
            )

    gt_words = []
    for sub in subtitles:
        speaker = sub.get("speaker", "Alex")
        text = sub.get("text", "")
        words = re.findall(r"\S+", text)
        for w in words:
            gt_words.append(
                {
                    "word": w,
                    "speaker": speaker,
                    "start": sub.get("start_time_sec", 0.0),
                    "end": sub.get("end_time_sec", 0.0),
                }
            )

    def clean_word(txt):
        return re.sub(r"[^a-zA-Z0-9]", "", txt).lower()

    gt_texts = [clean_word(x["word"]) for x in gt_words]
    w_texts = [clean_word(x["word"]) for x in whisper_words]

    matcher = difflib.SequenceMatcher(None, gt_texts, w_texts)
    for match in matcher.get_matching_blocks():
        for i in range(match.size):
            gt_idx = match.a + i
            w_idx = match.b + i
            if gt_texts[gt_idx] and w_texts[w_idx]:
                gt_words[gt_idx]["start"] = whisper_words[w_idx]["start"]
                gt_words[gt_idx]["end"] = whisper_words[w_idx]["end"]
                gt_words[gt_idx]["matched"] = True

    # Interpolate unmatched words
    for i in range(len(gt_words)):
        if gt_words[i].get("matched"):
            continue

        left_t = None
        for j in range(i - 1, -1, -1):
            if gt_words[j].get("matched"):
                left_t = gt_words[j]["end"]
                break

        right_t = None
        for j in range(i + 1, len(gt_words)):
            if gt_words[j].get("matched"):
                right_t = gt_words[j]["start"]
                break

        if left_t is None:
            left_t = gt_words[i]["start"]
        if right_t is None:
            right_t = gt_words[i]["end"]
        if right_t < left_t:
            right_t = left_t + 0.1

        k_start = i
        while k_start > 0 and not gt_words[k_start - 1].get("matched"):
            k_start -= 1
        k_end = i
        while k_end < len(gt_words) - 1 and not gt_words[k_end + 1].get("matched"):
            k_end += 1

        k_len = k_end - k_start + 1
        idx_in_hole = i - k_start
        step = (right_t - left_t) / (k_len + 1)

        gt_words[i]["start"] = left_t + step * (idx_in_hole + 1)
        gt_words[i]["end"] = gt_words[i]["start"] + step * 0.8

    print(f"Aligned {len(gt_words)} words.")
    return gt_words


def chunk_words_into_screens(words_data):
    screens = []
    current_screen = []

    def finalize_screen(screen_words):
        if not screen_words:
            return

        start_t = screen_words[0]["start"] - 0.1
        end_t = screen_words[-1]["end"] + 0.3
        speaker = screen_words[0]["speaker"]
        color = SPEAKER_CONFIG.get(speaker, SPEAKER_CONFIG["Default"])["color"]

        screens.append(
            {
                "words": screen_words,
                "start": max(0, start_t),
                "end": end_t,
                "color": color,
            }
        )

    for i, word in enumerate(words_data):
        current_screen.append(word)

        word_text = word["word"]
        is_break = False
        if len(current_screen) >= SUBTITLE_MAX_WORDS_PER_SCREEN:
            is_break = True
        elif word_text and word_text[-1] in [".", "?", "!", ","]:
            is_break = True
        elif i < len(words_data) - 1:
            next_w = words_data[i + 1]
            if next_w["speaker"] != word["speaker"]:
                is_break = True
            elif next_w["start"] - word["end"] > 0.8:
                is_break = True

        if is_break:
            finalize_screen(current_screen)
            current_screen = []

    if current_screen:
        finalize_screen(current_screen)

    return screens


def create_video_podcast():
    mp3_path, json_path, base_name = get_target_podcast_files()

    with open(json_path, "r", encoding="utf-8") as f:
        subtitles = json.load(f)

    whisper_cache = os.path.join(OUTPUT_DIR, f"{base_name}_whisper_cache.json")

    use_cache = False
    if os.path.exists(whisper_cache):
        cache_mtime = os.path.getmtime(whisper_cache)
        mp3_mtime = os.path.getmtime(mp3_path)
        use_cache = cache_mtime > mp3_mtime

    if use_cache:
        print(f"Using valid whisper cache: {whisper_cache}")
        with open(whisper_cache, "r", encoding="utf-8") as f:
            words_data = json.load(f)
    else:
        print("Whisper cache missing/outdated. Recomputing...")
        words_data = extract_word_timestamps(mp3_path, subtitles)
        with open(whisper_cache, "w", encoding="utf-8") as f:
            json.dump(words_data, f, ensure_ascii=False, indent=2)

    screens = chunk_words_into_screens(words_data)

    audio = AudioFileClip(mp3_path)
    total_duration = audio.duration

    print("Loading audio FFT array into RAM...")
    audio_fps = 22050
    audio_full_array = audio.to_soundarray(fps=audio_fps)
    if audio_full_array is not None and audio_full_array.ndim == 2:
        audio_full_array = audio_full_array.mean(axis=1)

    vis_chunk_size = 2048
    vis_window = np.hanning(vis_chunk_size)

    bg_img = Image.open(IMAGE_INPUT_PATH).convert("RGB")
    width, height = bg_img.size
    if width % 2 != 0:
        width -= 1
    if height % 2 != 0:
        height -= 1
    bg_img = bg_img.crop((0, 0, width, height))

    try:
        font = ImageFont.truetype(r"C:\Windows\Fonts\arial.ttf", SUBTITLE_FONT_SIZE)
    except Exception:
        font = ImageFont.load_default()

    smooth_bars = np.zeros(VIS_BAR_COUNT)
    shape_window = 1.0 - np.linspace(-1, 1, VIS_BAR_COUNT) ** 2 * 0.4

    def make_frame(t):
        nonlocal smooth_bars

        img = bg_img.copy()
        draw = ImageDraw.Draw(img)

        color_highlight = "#1B365D"
        color_text = "#F5F5DC"

        start_idx = int(t * audio_fps)
        end_idx = start_idx + vis_chunk_size

        if end_idx <= len(audio_full_array):
            segment = audio_full_array[start_idx:end_idx] * vis_window
            fft_data = np.abs(np.fft.rfft(segment))

            half_count = math.ceil(VIS_BAR_COUNT / 2)
            bins = calculate_log_bins(fft_data, audio_fps, vis_chunk_size, half_count, 80, 4000)

            db_bins = 20 * np.log10(bins + 1e-6)
            min_db = -25
            max_db = 25
            norm_half = np.clip((db_bins - min_db) / (max_db - min_db), 0, 1)
            norm_half = norm_half ** 1.2

            current_bars = np.zeros(VIS_BAR_COUNT)
            if VIS_BAR_COUNT % 2 == 0:
                current_bars[:half_count] = norm_half[::-1]
                current_bars[half_count:] = norm_half
            else:
                current_bars[:half_count] = norm_half[::-1]
                current_bars[half_count:] = norm_half[1:]

            current_bars = current_bars * shape_window
            smooth_factor = 0.7
            smooth_bars = smooth_bars + smooth_factor * (current_bars - smooth_bars)

            total_vis_w = VIS_BAR_COUNT * VIS_BAR_WIDTH + (VIS_BAR_COUNT - 1) * VIS_BAR_SPACING
            start_x_vis = (width - total_vis_w) / 2
            base_y_vis = height / 2 + VIS_Y_OFFSET

            for value in smooth_bars:
                bar_h = max(value * VIS_MAX_HEIGHT, VIS_BAR_WIDTH)
                vis_box = [
                    start_x_vis,
                    base_y_vis - bar_h / 2,
                    start_x_vis + VIS_BAR_WIDTH,
                    base_y_vis + bar_h / 2,
                ]
                radius_bar = VIS_BAR_WIDTH // 2

                try:
                    draw.rounded_rectangle(vis_box, radius=radius_bar, fill=color_highlight)
                except AttributeError:
                    draw.rectangle(vis_box, fill=color_highlight)

                start_x_vis += VIS_BAR_WIDTH + VIS_BAR_SPACING

        active_screen = None
        for sc in screens:
            if sc["start"] <= t <= sc["end"]:
                active_screen = sc
                break

        if not active_screen:
            return np.array(img)

        max_box_width = int(width * 0.8)
        space_w = draw.textlength(" ", font=font)

        lines = []
        current_line = []
        current_w = 0

        for word_info in active_screen["words"]:
            word_w = draw.textlength(word_info["word"], font=font)
            if current_w + space_w + word_w > max_box_width and current_line:
                lines.append(current_line)
                current_line = [word_info]
                current_w = word_w
            else:
                current_line.append(word_info)
                current_w += space_w + word_w if current_w > 0 else word_w

        if current_line:
            lines.append(current_line)

        line_h = SUBTITLE_FONT_SIZE + 5
        line_spacing = 15
        total_h = len(lines) * line_h + (len(lines) - 1) * line_spacing
        start_y = (height - total_h) / 2 + SUBTITLE_Y_OFFSET

        flat_words = []
        y_cursor = start_y
        for line_idx, line in enumerate(lines):
            line_width = (
                sum(draw.textlength(w["word"], font=font) for w in line)
                + space_w * (len(line) - 1)
            )
            x_cursor = (width - line_width) / 2

            for word_info in line:
                word_w = draw.textlength(word_info["word"], font=font)
                flat_words.append(
                    {
                        "word": word_info["word"],
                        "start": word_info["start"],
                        "end": word_info["end"],
                        "x": x_cursor,
                        "y": y_cursor,
                        "w": word_w,
                        "h": line_h,
                        "line_idx": line_idx,
                    }
                )
                x_cursor += word_w + space_w

            y_cursor += line_h + line_spacing

        line_highlights = {}
        for i, w in enumerate(flat_words):
            line_idx = w["line_idx"]
            if line_idx not in line_highlights:
                line_highlights[line_idx] = {
                    "L": w["x"],
                    "R": w["x"],
                    "y": w["y"],
                    "h": w["h"],
                    "has_passed": False,
                }

            if t > w["end"]:
                line_highlights[line_idx]["R"] = w["x"] + w["w"]
                line_highlights[line_idx]["has_passed"] = True
            elif w["start"] <= t <= w["end"]:
                progress = (t - w["start"]) / max(0.001, w["end"] - w["start"])
                line_highlights[line_idx]["R"] = w["x"] + w["w"] * progress
                line_highlights[line_idx]["has_passed"] = True
                break
            elif t < w["start"]:
                if i > 0:
                    prev_w = flat_words[i - 1]
                    if prev_w["line_idx"] == line_idx and prev_w["end"] < t:
                        progress = (t - prev_w["end"]) / max(0.001, w["start"] - prev_w["end"])
                        r_prev = prev_w["x"] + prev_w["w"]
                        r_next = w["x"]
                        line_highlights[line_idx]["R"] = r_prev + progress * (r_next - r_prev)
                        line_highlights[line_idx]["has_passed"] = True
                break

        pad_x, pad_y = 12, 6
        for block in line_highlights.values():
            if block["has_passed"] and block["R"] > block["L"]:
                box_coords = [
                    block["L"] - pad_x,
                    block["y"] - pad_y,
                    block["R"] + pad_x,
                    block["y"] + block["h"] + pad_y,
                ]
                try:
                    draw.rounded_rectangle(box_coords, radius=12, fill=color_highlight)
                except AttributeError:
                    draw.rectangle(box_coords, fill=color_highlight)

        for w in flat_words:
            for dx, dy in [(-1, -1), (1, -1), (-1, 1), (1, 1)]:
                draw.text((w["x"] + dx, w["y"] + dy), w["word"], font=font, fill="black")
            draw.text((w["x"], w["y"]), w["word"], font=font, fill=color_text)

        return np.array(img)

    print("Rendering composite video...")
    video = VideoClip(make_frame, duration=total_duration)
    video = video.with_audio(audio)

    if TESTING_MODE:
        video = video.subclipped(0, min(TESTING_DURATION_SEC, total_duration))
        out_file = os.path.join(OUTPUT_DIR, f"{base_name}_Preview_Test.mp4")
    else:
        out_file = os.path.join(OUTPUT_DIR, f"{base_name}_Final_Video.mp4")

    print(f"Exporting: {out_file}")
    video.write_videofile(
        out_file,
        fps=24,
        codec="libx264",
        audio_codec="aac",
        threads=4,
        ffmpeg_params=["-pix_fmt", "yuv420p"],
        logger=None,
    )


if __name__ == "__main__":
    create_video_podcast()
