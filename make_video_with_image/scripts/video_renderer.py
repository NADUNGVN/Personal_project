import os
import json
import math
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from moviepy import AudioFileClip, VideoClip
from faster_whisper import WhisperModel

# ================= GLOBAL CONFIGURATION =================
INPUT_DIR = "input"
OUTPUT_DIR = "output"
IMAGE_DIR = os.path.join(INPUT_DIR, "image")
IMAGE_INPUT_PATH = os.path.join(IMAGE_DIR, "image_input.png")

# ================= CẤU HÌNH SUBTITLE (PHỤ ĐỀ) & WHISPER =================
SUBTITLE_FONT_SIZE = 30                # Kích thước chữ vừa vặn nhất cho không gian rộng (Tự động word-wrap nếu vượt lề)
SUBTITLE_Y_OFFSET = -250                # Điều chỉnh trục Y. Âm = nâng lên, Dương = hạ xuống. 
SUBTITLE_MAX_WORDS_PER_SCREEN = 12     # SỐ CHỮ TỐI ĐA trên 1 cái nháy (Nhiều quá thì rối mắt)

# ================= CẤU HÌNH VISUALIZER SÓNG ÂM =================
VIS_Y_OFFSET = -100                # Căn chỉnh trục Y cho Sóng âm (Đẩy xuống giữa/dưới)
VIS_BAR_COUNT = 35               # Số lượng cột sóng
VIS_BAR_WIDTH = 7                # Bề ngang mỗi cột
VIS_BAR_SPACING = 3               # Khoảng cách giữa các cột
VIS_MAX_HEIGHT = 150              # Chiều cao nẩy lên tối đa của sóng

TESTING_MODE = False                   # Đặt = True để render chỉ 20s xem trước!
TESTING_DURATION_SEC = 60

# Tùy chỉnh màu Highlight lúc đọc tới Karaoke
SPEAKER_CONFIG = {
    "Sarah": {"color": "#FFE333"},  # Yellow
    "Alex":  {"color": "#00FFFF"},  # Cyan
}
# ========================================================

def calculate_log_bins(fft_data, sample_rate, chunk_size, num_bins, min_fq, max_fq):
    """Chia phổ âm FFT thành số lượng Bar theo hình chóp Logarithmic (EQ mượt)"""
    freqs = np.fft.rfftfreq(chunk_size, 1.0 / sample_rate)
    valid_indices = np.where((freqs >= min_fq) & (freqs <= max_fq))[0]
    if len(valid_indices) == 0:
        return np.zeros(num_bins)
        
    valid_fft = fft_data[valid_indices]
    valid_freqs = freqs[valid_indices]
    
    log_edges = np.geomspace(min_fq, max_fq, num_bins + 1)
    bins = np.zeros(num_bins)
    
    for i in range(num_bins):
        idx = np.where((valid_freqs >= log_edges[i]) & (valid_freqs < log_edges[i+1]))[0]
        if len(idx) > 0:
            bins[i] = np.mean(valid_fft[idx])
        else:
            bins[i] = 0
            
    return bins

def get_latest_podcast_files():
    mp3_files = [f for f in os.listdir(OUTPUT_DIR) if f.endswith("_podcast.mp3")]
    if not mp3_files:
        raise FileNotFoundError("Không tìm thấy tệp MP3 nào!")
    latest_mp3 = max(mp3_files, key=lambda x: os.path.getmtime(os.path.join(OUTPUT_DIR, x)))
    base_name = latest_mp3.replace("_podcast.mp3", "")
    return (
        os.path.join(OUTPUT_DIR, latest_mp3), 
        os.path.join(OUTPUT_DIR, f"{base_name}_subtitles.json"), 
        base_name
    )

def extract_word_timestamps(audio_path, subtitles):
    """Sử dụng Faster-Whisper đỉnh cao để dò tìm theo Từng Từ (Word-level timestamps) và Khớp với Text Gốc"""
    import re
    import difflib
    
    print("Khởi động AI Faster-Whisper dò khung thời gian...")
    model = WhisperModel("base.en", device="cuda", compute_type="float16")
    segments, info = model.transcribe(audio_path, word_timestamps=True)
    
    print("Đang cắn sóng âm để nhận diện Từng Từ...")
    w_words = []
    for segment in segments:
        for word in segment.words:
            w_words.append({
                "word": word.word.strip(),
                "start": float(word.start),
                "end": float(word.end)
            })
            
    # Xây dựng Ground Truth rành mạch từ file JSON kịch bản (Bảo vệ 100% text không mất chữ)
    gt_words = []
    for sub in subtitles:
        speaker = sub.get("speaker", "Alex")
        text = sub.get("text", "")
        # Tách chữ nhưng giữ lại dấu phẩy, chấm... (Các từ có nghĩa)
        words = re.findall(r'\S+', text)
        for w in words:
            gt_words.append({
                "word": w,
                "speaker": speaker,
                "start": sub.get("start_time_sec", 0.0),
                "end": sub.get("end_time_sec", 0.0)
            })
            
    # Sử dụng SequenceMatcher để KHỚP (Alignment) AI Text với Ground Truth
    def clean_word(txt):
        return re.sub(r'[^a-zA-Z0-9]', '', txt).lower()
        
    gt_texts = [clean_word(x["word"]) for x in gt_words]
    w_texts = [clean_word(x["word"]) for x in w_words]
    
    matcher = difflib.SequenceMatcher(None, gt_texts, w_texts)
    
    for match in matcher.get_matching_blocks():
        for i in range(match.size):
            gt_idx = match.a + i
            w_idx = match.b + i
            if gt_texts[gt_idx] and w_texts[w_idx]: # Bỏ qua chữ rỗng do xoá kí tự đặc biệt
                gt_words[gt_idx]["start"] = w_words[w_idx]["start"]
                gt_words[gt_idx]["end"] = w_words[w_idx]["end"]
                gt_words[gt_idx]["matched"] = True
                
    # Nội suy (Interpolate) các chữ bị Whisper bỏ quên / nhận diện sai
    for i in range(len(gt_words)):
        if not gt_words[i].get("matched"):
            # Tìm mốc thời gian của từ (đã khớp) gần nhất bên trái
            left_t = None
            for j in range(i-1, -1, -1):
                if gt_words[j].get("matched"):
                    left_t = gt_words[j]["end"]
                    break
            # Tìm mốc thời gian của từ (đã khớp) gần nhất bên phải
            right_t = None
            for j in range(i+1, len(gt_words)):
                if gt_words[j].get("matched"):
                    right_t = gt_words[j]["start"]
                    break
                    
            if left_t is None: left_t = gt_words[i]["start"]
            if right_t is None: right_t = gt_words[i]["end"]
            
            # Tránh lỗi đè ngược thời gian (Ví dụ 2 chữ sát vách nhau)
            if right_t < left_t: right_t = left_t + 0.1
            
            # Liếc xem có bao nhiêu chữ đang cùng bị kẹt (Bị miss liên tiếp tạo thành lỗ hổng)
            k_start = i
            while k_start > 0 and not gt_words[k_start-1].get("matched"):
                k_start -= 1
            k_end = i
            while k_end < len(gt_words)-1 and not gt_words[k_end+1].get("matched"):
                k_end += 1
                
            k_len = k_end - k_start + 1
            idx_in_hole = i - k_start
            
            # Chia đều khoảng thời gian trống cho các chữ bị lấp
            step = (right_t - left_t) / (k_len + 1)
            
            gt_words[i]["start"] = left_t + step * (idx_in_hole + 1)
            gt_words[i]["end"] = gt_words[i]["start"] + step * 0.8
            
    print(f"Hoàn tất đồng bộ {len(gt_words)} từ! (Đã vá các lỗ hổng của Whisper)")
    return gt_words

def chunk_words_into_screens(words_data):
    """Xếp các Từ vào từng Nhóm Màn Hình (Tối đa X chữ, tự rã nhóm nếu hết câu hoặc có dấu)"""
    screens = []
    current_screen = []
    
    def finalize_screen(screen_words):
        if not screen_words: return
        # Tính gộp thời gian hiển thị màn hình đó (Buff thêm 1 tí chớp nháy ở đầu cuối cho xịn)
        start_t = screen_words[0]["start"] - 0.1
        end_t = screen_words[-1]["end"] + 0.3 # 0.3s delay để mắt xem kịp
        # Hút lấy màu của người nói
        speaker = screen_words[0]["speaker"]
        color = SPEAKER_CONFIG.get(speaker, SPEAKER_CONFIG["Alex"])["color"]
        
        screens.append({
            "words": screen_words,
            "start": max(0, start_t),
            "end": end_t,
            "color": color
        })

    for i, w in enumerate(words_data):
        current_screen.append(w)
        
        # Các DẤU HIỆU để Chốt 1 luồng chữ (Kết thúc Screen để chuyển qua cụm khác):
        # 1. Đạt giới hạn chữ mong muốn
        # 2. Người nói đổi 
        # 3. Dấu chấm, hỏi, phẩy
        # 4. Có khoảng lặng mảng > 0.8s tới từ tiếp theo
        word_text = w["word"]
        
        is_break = False
        if len(current_screen) >= SUBTITLE_MAX_WORDS_PER_SCREEN:
            is_break = True
        elif word_text[-1] in [".", "?", "!", ","]:
            is_break = True
        elif i < len(words_data) - 1:
            next_w = words_data[i+1]
            if next_w["speaker"] != w["speaker"]:
                is_break = True
            elif next_w["start"] - w["end"] > 0.8:
                is_break = True
                
        if is_break:
            finalize_screen(current_screen)
            current_screen = []
            
    if current_screen:
        finalize_screen(current_screen)
        
    return screens

def create_video_podcast():
    mp3_path, json_path, base_name = get_latest_podcast_files()
    
    with open(json_path, 'r', encoding='utf-8') as f:
        subtitles = json.load(f)
        
    # 1. Ứng dụng WHISPER lấy Timestamp chuẩn xác từng Miliseconds
    # (Để tăng tốc, cache nó lại nếu đã có)
    whisper_cache = os.path.join(OUTPUT_DIR, f"{base_name}_whisper_cache.json")
    if os.path.exists(whisper_cache):
        print(f"Tìm thấy Whisper cache, tải lên cho lẹ: {whisper_cache}")
        with open(whisper_cache, 'r', encoding='utf-8') as f:
            words_data = json.load(f)
    else:
        words_data = extract_word_timestamps(mp3_path, subtitles)
        with open(whisper_cache, 'w', encoding='utf-8') as f:
            json.dump(words_data, f, ensure_ascii=False, indent=2)
            
    # Xếp vô các Khuôn Hình Karaoke (Screens)
    screens = chunk_words_into_screens(words_data)
    
    # 2. Xây dựng ENGINE VẼ CHỮ PIL-Based thay thế MoviePy lỗi thời
    audio = AudioFileClip(mp3_path)
    total_duration = audio.duration
    
    # 3. Nạp array âm thanh vĩnh viễn vào RAM để Visualizer quét siêu tốc mà không giật
    print("Nạp khối âm thanh FFT (Tần số lấy mẫu 22.050Hz) vào RAM...")
    AUDIO_FPS = 22050
    audio_full_array = audio.to_soundarray(fps=AUDIO_FPS)
    if audio_full_array is not None and audio_full_array.ndim == 2:
        audio_full_array = audio_full_array.mean(axis=1) # Gom Stereo thành Mono để dễ đọc sóng
    VIS_CHUNK_SIZE = 2048
    vis_window = np.hanning(VIS_CHUNK_SIZE)
    
    bg_img = Image.open(IMAGE_INPUT_PATH).convert("RGB")
    W, H = bg_img.size
    # Ép chiều rộng và chiều cao phải là số chẵn (Bắt buộc đối với yuv420p MP4)
    if W % 2 != 0: W -= 1
    if H % 2 != 0: H -= 1
    bg_img = bg_img.crop((0, 0, W, H))
    
    try:
        # Dùng arial thường (mỏng) thay vì arialbd (bold)
        font = ImageFont.truetype(r"C:\Windows\Fonts\arial.ttf", SUBTITLE_FONT_SIZE)
    except:
        font = ImageFont.load_default()

    # KHỞI TẠO BỘ NHỚ LƯU VẾT SÓNG ÂM (Gravity Fall Smoothing)
    smooth_bars = np.zeros(VIS_BAR_COUNT)
    
    # Khuôn Parabol nhẹ: Ép sóng âm phồng ở giữa (1.0) và thon dần ra mép (0.6)
    # Không ép về 0 như trước để mép viền vẫn hoạt động cực cháy
    shape_window = 1.0 - np.linspace(-1, 1, VIS_BAR_COUNT)**2 * 0.4

    def make_frame(t):
        nonlocal smooth_bars
        # Frame nền tĩnh
        img = bg_img.copy()
        draw = ImageDraw.Draw(img)
        
        # 1. VẼ THUẬT TOÁN SÓNG ÂM VISUALIZER NHẤP NHÁY
        # Dùng chung tông màu sang trọng với Highlight
        color_highlight = "#1B365D" # Xanh đậm tệp với mọi Highlight
        color_text = "#F5F5DC"      # Màu kem cho toàn bộ chữ
        
        start_idx = int(t * AUDIO_FPS)
        end_idx = start_idx + VIS_CHUNK_SIZE
        
        if end_idx <= len(audio_full_array):
            segment = audio_full_array[start_idx:end_idx] * vis_window
            # Lấy FFT thực tế mà KHÔNG chia cho chunk_size để biên độ to rõ ràng
            fft_data = np.abs(np.fft.rfft(segment))
            
            # Chỉ lấy Bass và Mid (Vùng giọng nói cực mượt: 80Hz - 4000Hz)
            half_count = math.ceil(VIS_BAR_COUNT / 2)
            bins = calculate_log_bins(fft_data, AUDIO_FPS, VIS_CHUNK_SIZE, half_count, 80, 4000)
            
            db_bins = 20 * np.log10(bins + 1e-6)
            # Ngưỡng Decibel thực tế của Audio: Im lặng ~ -30dB, nói ~ +25dB
            min_db = -25  
            max_db = 25
            norm_half = np.clip((db_bins - min_db) / (max_db - min_db), 0, 1)
            
            # Tăng độ nẩy (Linear hơn nhưng giữ chất Pop)
            norm_half = norm_half ** 1.2
            
            # DÀN DỮ LIỆU ĐỐI XỨNG (Symmetric mapping): Treble ở mép, Bass/Mid ở giữa
            current_bars = np.zeros(VIS_BAR_COUNT)
            if VIS_BAR_COUNT % 2 == 0:
                current_bars[:half_count] = norm_half[::-1]
                current_bars[half_count:] = norm_half
            else:
                current_bars[:half_count] = norm_half[::-1]
                current_bars[half_count:] = norm_half[1:]
                
            # Ép khối sóng âm thon gọn 2 đầu chuẩn Voice Memo nhưng biên vẫn nẩy!
            current_bars = current_bars * shape_window
            
            # THUẬT TOÁN EMA SMOOTHING (Sóng rơi mượt mà có trọng lượng)
            # Factor = 0.7 cho độ giật nhạy theo giọng nói cực kì chi tiết!
            smooth_factor = 0.7   
            smooth_bars = smooth_bars + smooth_factor * (current_bars - smooth_bars)
            
            norm_bins = smooth_bars
            
            # Dàn trải các thanh Sóng Âm (EQ Bars) ra trục chính giữa màn hình (Nằm dưới cụm Text)
            total_vis_w = VIS_BAR_COUNT * VIS_BAR_WIDTH + (VIS_BAR_COUNT - 1) * VIS_BAR_SPACING
            start_x_vis = (W - total_vis_w) / 2
            base_y_vis = H / 2 + VIS_Y_OFFSET
            
            for nb in norm_bins:
                bar_h = nb * VIS_MAX_HEIGHT
                if bar_h < VIS_BAR_WIDTH: bar_h = VIS_BAR_WIDTH # Đảm bảo chiều cao tối thiểu bằng chiều rộng để nó luôn là 1 hình tròn nhỏ khi im lặng
                
                # PHONG CÁCH MỚI: Symmetric Waveform (Đối xứng tâm trên/dưới) như Voice Memo
                # Cột Sóng sẽ mọc vươn từ GIỮA (base_y_vis) dãn đều lên trên và xuống dưới
                vis_box = [start_x_vis, base_y_vis - bar_h / 2, start_x_vis + VIS_BAR_WIDTH, base_y_vis + bar_h / 2]
                
                # Bo tròn tối đa 2 đầu (Capsule Shape)
                radius_bar = VIS_BAR_WIDTH // 2
                
                try:
                    draw.rounded_rectangle(vis_box, radius=radius_bar, fill=color_highlight)
                except AttributeError:
                    draw.rectangle(vis_box, fill=color_highlight)
                    
                start_x_vis += VIS_BAR_WIDTH + VIS_BAR_SPACING

        # 2. TÌM VÀ CĂN CHỮ KARAOKE TRÊN TRỤC THỜI GIAN
        active_screen = None
        for sc in screens:
            if sc["start"] <= t <= sc["end"]:
                active_screen = sc
                break
                
        if not active_screen:
            return np.array(img) # Đã vẽ xong Visualizer mộc rồi, nếu không có chữ thì Return luôn ảnh sóng âm đang nhấp nháy này!
            
        # Tạm thời cất tính năng hút màu theo người nói (color_highlight = active_screen["color"])
        
        # THUẬT TOÁN XUỐNG DÒNG (WORD-WRAP) siêu việt:
        max_box_width = int(W * 0.8) # Giới hạn chữ không vượt quá 80% lề màn hình
        space_w = draw.textlength(" ", font=font)
        
        lines = []
        curr_line = []
        curr_w = 0
        
        for w_info in active_screen["words"]:
            word_w = draw.textlength(w_info["word"], font=font)
            if curr_w + space_w + word_w > max_box_width and curr_line:
                lines.append(curr_line)
                curr_line = [w_info]
                curr_w = word_w
            else:
                curr_line.append(w_info)
                curr_w += space_w + word_w if curr_w > 0 else word_w
        if curr_line:
            lines.append(curr_line)
            
        # TÍNH TOÁN TỌA ĐỘ CHO TỪNG TỪ
        line_h = SUBTITLE_FONT_SIZE + 5
        line_spacing = 15
        total_h = len(lines) * line_h + (len(lines) - 1) * line_spacing
        start_y = (H - total_h) / 2 + SUBTITLE_Y_OFFSET
        
        flat_words = []
        y_cursor = start_y
        for l_idx, line in enumerate(lines):
            tw = sum(draw.textlength(w["word"], font=font) for w in line) + space_w * (len(line) - 1)
            x_cursor = (W - tw) / 2
            for w_info in line:
                w_w = draw.textlength(w_info["word"], font=font)
                flat_words.append({
                    "word": w_info["word"], "start": w_info["start"], "end": w_info["end"],
                    "x": x_cursor, "y": y_cursor, "w": w_w, "h": line_h, "line_idx": l_idx
                })
                x_cursor += w_w + space_w
            y_cursor += line_h + line_spacing

        # THUẬT TOÁN HIGHLIGHT LIỀN MẠCH TỪNG DÒNG (CONTINUOUS LINE-BASED)
        # Khung sinh ra là DUY NHẤT 1 Khối cho mỗi dòng. Khung sẽ dãn dính liền không đứt đoạn.
        line_highlights = {}
        active_idx = -1
        
        for i, w in enumerate(flat_words):
            l_idx = w["line_idx"]
            if l_idx not in line_highlights:
                # Tạo hạt nhân ghim điểm L ở phía TRÁI sát vách chữ đầu tiên của dòng
                line_highlights[l_idx] = {"L": w["x"], "R": w["x"], "y": w["y"], "h": w["h"], "has_passed": False}
                
            if t > w["end"]:
                # Từ này đã qua -> Kéo thẳng R về cuối chữ định vị
                line_highlights[l_idx]["R"] = w["x"] + w["w"]
                line_highlights[l_idx]["has_passed"] = True
                active_idx = i
            elif w["start"] <= t <= w["end"]:
                # Đang hát ngay từ này -> Mép R trượt giãn dần từ trái sang phải
                progress = (t - w["start"]) / max(0.001, w["end"] - w["start"])
                line_highlights[l_idx]["R"] = w["x"] + w["w"] * progress
                line_highlights[l_idx]["has_passed"] = True
                active_idx = i
                break
            elif t < w["start"]:
                # Chưa tới từ này -> Kiểm tra KHOẢNG TRỐNG (Gap) với chữ đứng trước nó
                if i > 0:
                    prev_w = flat_words[i-1]
                    if prev_w["line_idx"] == l_idx and prev_w["end"] < t:
                        # Điền kín khoảng trống mượt mà dính liền chữ cũ và chữ mới
                        progress = (t - prev_w["end"]) / max(0.001, w["start"] - prev_w["end"])
                        R_prev = prev_w["x"] + prev_w["w"]
                        R_next = w["x"] 
                        line_highlights[l_idx]["R"] = R_prev + progress * (R_next - R_prev)
                        line_highlights[l_idx]["has_passed"] = True
                break

        pad_x = 12
        pad_y = 6
        
        # 1. VẼ CÁC KHUNG HIGHLIGHT 
        # Rất tuyệt: Sẽ chỉ có tối đa 1 Khung duy nhất trên mỗi dòng (Biến mất lỗi bo tròn giữa chừng)
        for l_idx, blk in line_highlights.items():
            if blk["has_passed"] and blk["R"] > blk["L"]:
                box_coords = [blk["L"] - pad_x, blk["y"] - pad_y, blk["R"] + pad_x, blk["y"] + blk["h"] + pad_y]
                try:
                    draw.rounded_rectangle(box_coords, radius=12, fill=color_highlight)
                except AttributeError:
                    draw.rectangle(box_coords, fill=color_highlight)

        # 2. VẼ CHỮ ÁP VÀO
        for i, w in enumerate(flat_words):
            # Toàn bộ chữ từ đầu đến cuối đều giữ nguyên 1 màu Kem #F5F5DC
            # và KHÔNG CÒN BỊ ĐỔI MÀU kể cả khi Highlight nháy qua.
            
            # Vẫn giữ viền Stroke 1px để chữ nổi bật thanh lịch trên cả nền ảnh lẫn nền Highlight Xanh đậm
            for dx, dy in [(-1,-1), (1,-1), (-1,1), (1,1)]:
                draw.text((w["x"]+dx, w["y"]+dy), w["word"], font=font, fill="black")
                
            draw.text((w["x"], w["y"]), w["word"], font=font, fill=color_text)

        return np.array(img)

    print("Baking Master Composite Video bằng ENGINE VẼ Chữ Mới (PIL -> NVenc)...")
    video = VideoClip(make_frame, duration=total_duration)
    video = video.with_audio(audio)
    
    if TESTING_MODE:
        video = video.subclipped(0, min(TESTING_DURATION_SEC, total_duration))
        out_file = os.path.join(OUTPUT_DIR, f"{base_name}_Preview_Test.mp4")
    else:
        out_file = os.path.join(OUTPUT_DIR, f"{base_name}_Final_Video.mp4")
        
    print(f"Bắt đầu quy trình CPU Encoding Siêu Tương Thích sang: {out_file}")
    # Xuất ra bằng CPU đa luồng để cứu nguy tính tương thích
    video.write_videofile(
        out_file, 
        fps=24, 
        codec="libx264", 
        audio_codec="aac",
        threads=4, # Kéo 4 lõi CPU cày để thay thế VGA
        ffmpeg_params=["-pix_fmt", "yuv420p"] # Ép chuẩn màu mượt trên mọi hệ thống/Tivi
    )
if __name__ == "__main__":
    create_video_podcast()
