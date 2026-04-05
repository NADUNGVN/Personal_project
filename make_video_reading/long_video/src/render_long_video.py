import os
import argparse
import subprocess
import math
import difflib
import re
from pathlib import Path
from datetime import datetime

from faster_whisper import WhisperModel
from PIL import Image, ImageDraw, ImageFont
import numpy as np

try:
    from moviepy.video.io.VideoFileClip import VideoFileClip
    from moviepy.video.VideoClip import VideoClip
    from moviepy.audio.io.AudioFileClip import AudioFileClip
except ImportError:
    try:
        from moviepy import VideoFileClip, AudioFileClip, VideoClip
    except ImportError:
        from moviepy.editor import VideoFileClip, AudioFileClip, VideoClip

# =========================================================================
# VIDEO LAYOUT & COLORS (1920x1080)
# =========================================================================

VIDEO_WIDTH = 1920
VIDEO_HEIGHT = 1080

BG_COLOR = (255, 255, 255)       
TEXT_INACTIVE_COLOR = (50, 50, 50, 255)  
TEXT_ACTIVE_COLOR = (255, 255, 255, 255) 
HIGHLIGHT_BG_COLOR = (139, 0, 0, 255)    

FONT_PATH = "C:/Windows/Fonts/arialbd.ttf"
TITLE_FONT_PATH = "C:/Windows/Fonts/impact.ttf" 

SUB_W = 1600
SUB_H = 450
SUB_X = (VIDEO_WIDTH - SUB_W) // 2 
# Khách yêu cầu: Kéo thả khung Subtitle trúng ngay tâm Giữa Màn Hình (Vertical Center)
SUB_Y = (VIDEO_HEIGHT - SUB_H) // 2 - 50 # Khoảng Y = 265 (Ngay giữa chính diện)

AVATAR_MAX_W = 750
AVATAR_MAX_H = 650                  

WAVE_TOTAL_W = 800
WAVE_TOTAL_H = 150
WAVE_X = AVATAR_MAX_W + 150         
WAVE_Y = VIDEO_HEIGHT - WAVE_TOTAL_H - 100 

SYNC_OFFSET = 0.12

# =========================================================================
# HÀM PHÂN TÍCH ÂM THANH (WAVE BAR)
# =========================================================================
def _decode_audio_mono(audio_path: Path, sample_rate: int) -> np.ndarray:
    print(">> Đang bóc tách Tần Số mảng âm thanh...")
    command = [
        "ffmpeg", "-v", "error", "-i", str(audio_path),
        "-vn", "-ac", "1", "-ar", str(sample_rate), "-f", "s16le", "-"
    ]
    result = subprocess.run(command, check=True, capture_output=True)
    samples = np.frombuffer(result.stdout, dtype=np.int16).astype(np.float32)
    return samples / 32768.0

def _build_band_index_groups(sample_rate: int, fft_size: int, band_count: int, min_freq: float, max_freq: float) -> list[np.ndarray]:
    frequencies = np.fft.rfftfreq(fft_size, d=1.0 / sample_rate)
    edges = np.geomspace(min_freq, max_freq, num=band_count + 1)
    groups = []
    for index in range(band_count):
        mask = np.where((frequencies >= edges[index]) & (frequencies < edges[index + 1]))[0]
        if mask.size == 0:
            target = (edges[index] + edges[index + 1]) / 2.0
            nearest = int(np.argmin(np.abs(frequencies - target)))
            mask = np.array([nearest], dtype=np.int32)
        groups.append(mask)
    return groups

def _compute_visualizer_levels(audio_samples: np.ndarray, sample_rate: int, fps: int, duration_seconds: float, band_count: int = 15) -> np.ndarray:
    print(">> Đang nội suy Mức độ Cường độ Nhạc (FFT Array)...")
    frame_count = max(1, int(math.ceil(duration_seconds * fps)))
    fft_size = 4096
    half_window = fft_size // 2
    window = np.hanning(fft_size).astype(np.float32)
    padded = np.pad(audio_samples, (half_window, half_window))
    groups = _build_band_index_groups(
        sample_rate=sample_rate, fft_size=fft_size, band_count=band_count, min_freq=65.0, max_freq=7200.0
    )

    band_energy = np.zeros((frame_count, band_count), dtype=np.float32)
    envelopes = np.zeros(frame_count, dtype=np.float32)
    samples_per_frame = sample_rate / float(fps)

    for frame_index in range(frame_count):
        center = int(round(frame_index * samples_per_frame))
        segment = padded[center : center + fft_size]
        if segment.shape[0] < fft_size:
            segment = np.pad(segment, (0, fft_size - segment.shape[0]))

        segment = segment.astype(np.float32, copy=False)
        envelopes[frame_index] = float(np.sqrt(np.mean(segment * segment) + 1e-8))
        spectrum = np.abs(np.fft.rfft(segment * window)).astype(np.float32)

        for group_index, group in enumerate(groups):
            values = spectrum[group]
            band_energy[frame_index, group_index] = float(np.sqrt(np.mean(values * values) + 1e-8))

    band_scale = np.percentile(band_energy, 95, axis=0)
    band_scale = np.where(band_scale > 1e-6, band_scale, 1.0)
    envelope_scale = float(np.percentile(envelopes, 95))
    if envelope_scale <= 1e-6: envelope_scale = 1.0

    band_norm = np.clip(band_energy / band_scale, 0.0, 1.0) ** 0.90
    envelope_norm = np.clip(envelopes / envelope_scale, 0.0, 1.0) ** 0.75

    shape = 1.06 - 0.14 * np.abs(np.linspace(-1.0, 1.0, band_count, dtype=np.float32))
    targets = np.clip(0.05 + (band_norm * 0.72 + envelope_norm[:, None] * 0.38) * shape, 0.0, 1.0)

    smoothed = np.zeros_like(targets)
    previous = np.zeros(band_count, dtype=np.float32)
    attack = 0.34
    release = 0.12

    for frame_index in range(frame_count):
        target = targets[frame_index]
        rising = target > previous
        previous = np.where(rising, previous + attack * (target - previous), previous + release * (target - previous))
        smoothed[frame_index] = previous

    return np.concatenate([smoothed[:, ::-1], smoothed], axis=1)

# =========================================================================

def sync_whisper_to_text(whisper_words, source_text):
    print(">> Đang áp dụng cơ chế đồng bộ Difflib (Ép khung chữ Gốc theo Audio)...")
    cleaned_source = re.sub(r'\[---.*?---\]', '', source_text)
    
    source_words = [w for w in cleaned_source.split() if w]
    ai_texts = [w['word'].strip().lower() for w in whisper_words]
    source_words_lower = [w.lower() for w in source_words]
    
    matcher = difflib.SequenceMatcher(None, ai_texts, source_words_lower)
    synced_data = []
    
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'equal':
            for index in range(i2-i1):
                synced_data.append({
                    'word': source_words[j1 + index],
                    'start': whisper_words[i1 + index]['start'],
                    'end': whisper_words[i1 + index]['end']
                })
        elif tag == 'replace' or tag == 'insert':
            start_t = whisper_words[max(0, i1-1)]['end'] if i1 == 0 else whisper_words[i1]['start'] if i1 < len(whisper_words) else whisper_words[-1]['end']
            end_t = whisper_words[i2-1]['end'] if i2 > 0 and i2 <= len(whisper_words) else whisper_words[-1]['end']
            
            num_words = j2 - j1
            if num_words > 0:
                duration_per_word = max(0.01, (end_t - start_t) / num_words)
                for index in range(num_words):
                    synced_data.append({
                        'word': source_words[j1 + index],
                        'start': start_t + index * duration_per_word,
                        'end': start_t + (index + 1) * duration_per_word
                    })
    return synced_data

def get_whisper_timings(audio_path, source_text_data=None):
    print(">> Đang phân tích Audio bóc băng thời gian Whisper...")
    device = "cuda" if os.environ.get("CUDA_VISIBLE_DEVICES") != "-1" else "cpu"
    compute_type = "float16" if device == "cuda" else "int8"
    whisper_model = WhisperModel("large-v3", device=device, compute_type=compute_type)
    
    segments, _ = whisper_model.transcribe(str(audio_path), word_timestamps=True)
    all_words = []
    for s in segments:
        if s.words:
            for w in s.words:
                all_words.append({'word': w.word.strip(), 'start': w.start, 'end': w.end})
                
    if source_text_data is not None and len(source_text_data.strip()) > 0:
        return sync_whisper_to_text(all_words, source_text_data)
        
    return all_words

def chunk_words_into_screens(words_list, max_words=9):
    print(">> Đang phân bổ khối hình (Chunking)...")
    screens = []
    current_screen = []
    prev_end = 0.0
    
    for w in words_list:
        text = w['word']
        gap = w['start'] - prev_end
        
        if len(current_screen) > 0 and gap >= 0.8:
            screens.append(current_screen)
            current_screen = []
            
        current_screen.append(w)
        prev_end = w['end']
        
        if len(current_screen) >= max_words or text.endswith(('.', '?', '!', ';')):
            screens.append(current_screen)
            current_screen = []

    if current_screen:
        screens.append(current_screen)
        
    return screens

def load_font(size, is_title=False):
    import os
    primary_paths = ["C:/Windows/Fonts/impact.ttf"] if is_title else [
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/segoeuib.ttf", 
        "C:/Windows/Fonts/calibrib.ttf"
    ]
    for path in primary_paths:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
    print("⚠️ CẢNH BÁO: KHÔNG TÌM THẤY FONT CHỮ TO TOÀN MÀN HÌNH, CHỮ SẼ RẤT BÉ!")
    return ImageFont.load_default()

def create_screen_layouts(screens):
    print(">> Đang vẽ Khung Layout Đồ họa Tĩnh...")
    base_font_size = 95
    line_spacing = 35
    font = load_font(base_font_size)
    layouts = []
    
    for screen_idx, screen_words in enumerate(screens):
        if not screen_words: continue
        
        for i in range(len(screen_words)):
            screen_words[i]['start'] += SYNC_OFFSET
            screen_words[i]['end'] += SYNC_OFFSET
            if i < len(screen_words) - 1:
                next_start = screen_words[i+1]['start'] + SYNC_OFFSET
                gap = next_start - screen_words[i]['end']
                if not screen_words[i]['word'].endswith(('.', '?', '!')) and gap < 0.6:
                    screen_words[i]['end'] = next_start
        
        t_start = screen_words[0]['start']
        t_end = screen_words[-1]['end'] 
        
        img_inactive = Image.new("RGBA", (SUB_W, SUB_H), (0,0,0,0))
        draw_inactive = ImageDraw.Draw(img_inactive)
        
        lines = []
        c_line = []
        
        def get_w(text):
            bb = draw_inactive.textbbox((0,0), text, font=font)
            return bb[2] - bb[0]
            
        def get_h(text):
            bb = draw_inactive.textbbox((0,0), "Agy"+text, font=font)
            return bb[3] - bb[1]
            
        max_text_w = SUB_W - 50 
        
        for w_dict in screen_words:
            w_text = w_dict['word']
            test_line = " ".join([d['word'] for d in c_line] + [w_text])
            if get_w(test_line) <= max_text_w:
                c_line.append(w_dict)
            else:
                lines.append(c_line)
                c_line = [w_dict]
        if c_line:
            lines.append(c_line)
            
        base_h = get_h("Ag")
        total_h = len(lines) * base_h + max(0, len(lines)-1) * line_spacing
        start_y = (SUB_H - total_h) // 2
        
        space_w = get_w(" ")
        word_render_data = [] 
        
        curr_y = start_y
        for line in lines:
            line_str = " ".join([d['word'] for d in line])
            line_w = get_w(line_str)
            curr_x = (SUB_W - line_w) // 2 
            
            for w_dict in line:
                ww = get_w(w_dict['word'])
                draw_inactive.text((curr_x, curr_y), w_dict['word'], font=font, fill=TEXT_INACTIVE_COLOR)
                word_render_data.append({
                    'text': w_dict['word'],
                    'start_t': w_dict['start'],
                    'end_t': w_dict['end'],
                    'x1': curr_x,
                    'y1': curr_y,
                    'x2': curr_x + ww,
                    'y2': curr_y + base_h
                })
                curr_x += ww + space_w
            curr_y += base_h + line_spacing
            
        layouts.append({
            't_start': t_start,
            't_end': t_end,
            't_start_render': t_start,
            't_end_render': t_end,
            'img_inactive': img_inactive,
            'words': word_render_data
        })
        
    for i in range(1, len(layouts)):
        prev = layouts[i-1]
        curr = layouts[i]
        gap = curr['t_start'] - prev['t_end']
        if gap < 1.0: 
            mid = (prev['t_end'] + curr['t_start']) / 2.0
            prev['t_end_render'] = mid
            curr['t_start_render'] = mid
        else: 
            prev['t_end_render'] = prev['t_end'] + 0.5
            curr['t_start_render'] = curr['t_start'] - 0.5
            
    if layouts:
        layouts[0]['t_start_render'] = max(0.0, layouts[0]['t_start'] - 0.5)
        layouts[-1]['t_end_render'] = layouts[-1]['t_end'] + 0.5
        
    return layouts, font

def maintain_aspect_ratio_avatar(image_path, max_w, max_h):
    try:
        img = Image.open(image_path).convert("RGBA")
        img.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)
        return img
    except Exception as e:
        print(f"Lỗi ảnh: {e}")
        return Image.new("RGBA", (400, 400), (200,200,200,255))
        
def create_video_processor(avatar_path, audio_path, text_data, output_mp4):
    print(">> Đang khởi động bàn ghép NVENC...")
    
    audio_clip = AudioFileClip(str(audio_path))
    duration = audio_clip.duration
    target_fps = 30
    
    sample_rate = 22050
    audio_samples = _decode_audio_mono(audio_path, sample_rate)
    wave_levels = _compute_visualizer_levels(audio_samples, sample_rate, target_fps, duration, band_count=15)
    bar_count = wave_levels.shape[1]
    gap = 10
    bar_width = int((WAVE_TOTAL_W - (bar_count-1)*gap) / bar_count)
    if bar_width < 2: bar_width = 8
    
    actual_wave_w = bar_count * bar_width + (bar_count - 1) * gap
    WAVE_START_X = WAVE_X + (WAVE_TOTAL_W - actual_wave_w) // 2

    raw_words = get_whisper_timings(audio_path, source_text_data=text_data)
    screens_data = chunk_words_into_screens(raw_words)
    screen_layouts, active_font = create_screen_layouts(screens_data)
    
    canvas_base = Image.new("RGB", (VIDEO_WIDTH, VIDEO_HEIGHT), BG_COLOR)
    
    draw_canvas = ImageDraw.Draw(canvas_base)
    title_font = load_font(75, is_title=True)
    av_x = 80
    draw_canvas.text((av_x, 70), "Easy Slow English Listening", font=title_font, fill=(0, 0, 0)) 
    
    avatar_img = maintain_aspect_ratio_avatar(avatar_path, AVATAR_MAX_W, AVATAR_MAX_H)
    av_y = VIDEO_HEIGHT - avatar_img.height - 20 
    canvas_base.paste(avatar_img, (av_x, av_y), mask=avatar_img)

    def make_frame(t):
        frame = canvas_base.copy()
        d_frame = ImageDraw.Draw(frame)
        
        f_idx = int(t * target_fps)
        if f_idx >= wave_levels.shape[0]: f_idx = wave_levels.shape[0] - 1
        
        levels_at_t = wave_levels[f_idx]
        rad = max(2, bar_width // 2)
        for b_idx, level in enumerate(levels_at_t):
            bar_bh = max(rad * 2 + 2, int(round(level * WAVE_TOTAL_H))) 
            l = WAVE_START_X + b_idx * (bar_width + gap)
            r = l + bar_width
            b = WAVE_Y + WAVE_TOTAL_H
            t = b - bar_bh
            
            # LOẠI BỎ THAM SỐ Outline vì Pillow bị khuyết tật toán học không gian khi viền hộp quá hẹp
            # Thiết kế Viền Đen thủ công bằng Lớp Màng Đen ẩn bên dưới:
            d_frame.rounded_rectangle([l-2, t-2, r+2, b], radius=rad+2, fill=(0, 0, 0))
            d_frame.rectangle([l-2, b - rad, r+2, b], fill=(0, 0, 0))
            
            # Phủ Lõi ruột Trắng (chừa lại chính xác 2px viền cực sắc và chắc chắn không bao giờ bị Crash màn hình)
            d_frame.rounded_rectangle([l, t, r, b], radius=rad, fill=(245, 245, 245))
            d_frame.rectangle([l, b - rad, r, b], fill=(245, 245, 245))

        active_screen = None
        for sc in screen_layouts:
            if sc['t_start_render'] <= t < sc['t_end_render']:
                active_screen = sc
                break
                
        if active_screen:
            sub_canvas = active_screen['img_inactive'].copy()
            d_sub = ImageDraw.Draw(sub_canvas)
            
            for w in active_screen['words']:
                if w['start_t'] <= t <= w['end_t']:
                    pad_x = 25
                    pad_y = 15
                    box_rect = [w['x1'] - pad_x, w['y1'] - pad_y, w['x2'] + pad_x, w['y2'] + pad_y + 10]
                    d_sub.rounded_rectangle(box_rect, radius=25, fill=HIGHLIGHT_BG_COLOR)
                    d_sub.text((w['x1'], w['y1']), w['text'], font=active_font, fill=TEXT_ACTIVE_COLOR)
                    
            frame.paste(sub_canvas, (SUB_X, SUB_Y), mask=sub_canvas)

        return np.array(frame)

    video = VideoClip(make_frame, duration=duration)
    video = video.with_audio(audio_clip)

    temp_audio = f"TEMP_{os.path.basename(output_mp4)}.m4a"
    try:
        video.write_videofile(
            str(output_mp4),
            fps=30,
            codec="h264_nvenc",
            preset="p4",
            audio_codec="aac",
            temp_audiofile=temp_audio,
            ffmpeg_params=["-pix_fmt", "yuv420p"]
        )
    except Exception as e:
        print(f"Bị kẹt NVENC ({e}), Trả về CPU chậm lụi (libx264)...")
        video.write_videofile(
            str(output_mp4),
            fps=30,
            codec="libx264",
            preset="ultrafast",
            audio_codec="aac",
            temp_audiofile=temp_audio,
            ffmpeg_params=["-pix_fmt", "yuv420p"]
        )

def main():
    parser = argparse.ArgumentParser(description="Mega Long Video Renderer Engine (Interactive & Argparse)")
    
    parser.add_argument("--audio", required=False, type=str, help="Đường dẫn đến file Audio MP3/WAV")
    parser.add_argument("--text", required=False, type=str, default=None, help="Đường dẫn đến file Text chuẩn (nếu có)")
    
    default_avatar = r"d:\work\Personal_project\make_video_reading\long_video\img\Gemini_Generated_Image_bna1hsbna1hsbna1.png"
    parser.add_argument("--image", required=False, type=str, default=default_avatar, help="Đường dẫn ảnh Avatar rỗng nền")
    
    default_output = r"d:\work\Personal_project\make_video_reading\long_video\output\FinalVideo_{}.mp4".format(datetime.now().strftime('%H%M%S'))
    parser.add_argument("--output", required=False, type=str, default=default_output, help="Đường dẫn file MP4 xuất ra")
    
    args = parser.parse_args()
    
    # 1. Cơ chế Interactive Hỏi - Đáp 
    audio_val = args.audio
    if not audio_val:
        audio_val = input("🎙️  Nhập đường dẫn tuyệt đối của Mẫu AUDIO/VOICE (Mặc định bỏ trống để thoát): ").strip()
        if not audio_val:
            print("Đã hủy quá trình render do chưa cung cấp nguồn Audio.")
            return

    text_val = args.text
    if text_val is None:
        text_val = input("📝 Nhập đường dẫn của File TEXT kịch bản (Bấm Enter để bỏ qua & dùng AI Whisper bóc băng): ").strip()
    
    audio_val = audio_val.replace('"', '').replace("'", "")
    audio_path = Path(audio_val).resolve()
    
    if not audio_path.exists():
        print(f"❌ KHÔNG TÌM THẤY FILE AUDIO: {audio_path}")
        return

    text_data = None
    if text_val:
        text_val = text_val.replace('"', '').replace("'", "")
        text_path = Path(text_val).resolve()
        if text_path.exists():
            with open(text_path, 'r', encoding='utf-8') as f:
                text_data = f.read()
        else:
            print(f"⚠️ Cảnh báo: File text bị lỗi hoặc không tồn tại '{text_val}'. Hệ thống sẽ bỏ qua bước Difflib đồng bộ chữ.")

    print(f"===========================================================")
    print(f"🎬 KÍCH HOẠT QUY TRÌNH KẾT XUẤT VIDEO LONG FORM NHÀO BỘT")
    print(f"► Audio Input : {audio_path}")
    print(f"► Image Avatar: {args.image}")
    print(f"► Text Diff   : {'SỬ DỤNG' if text_data else 'BỎ QUA (DÙNG NGUYÊN BẢN WHISPER THUẦN TÚY)'}")
    print(f"► MP4 Output  : {args.output}")
    print(f"===========================================================")
    
    create_video_processor(args.image, audio_path, text_data, args.output)

if __name__ == "__main__":
    main()
