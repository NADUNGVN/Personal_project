# SocialHarvester - Step 2: Image-to-Dialogue Video

## 1. Mục tiêu
- Xây dựng hệ thống tạo video hội thoại từ **1 ảnh đầu vào**.
- Nhân vật trong ảnh cần:
  - Chuyển động tự nhiên (idle motion, biểu cảm nhẹ, cử động cơ thể).
  - Nói chuyện qua lại theo kịch bản (A/B turn-taking).
  - Khớp giữa giọng nói, khẩu hình (lip-sync), subtitle và nhạc nền.
- Đầu ra hướng đến video ngắn dạng social (9:16 hoặc 16:9), ưu tiên chất lượng ổn định và dễ mở rộng.

## 2. Phạm vi Step 2
- Đầu vào chính: 1 ảnh + script hội thoại.
- Đầu ra chính: 1 file video đã render + metadata/timeline phục vụ review.
- Không bao gồm:
  - Tạo script bằng LLM (có thể thêm Step 2.1 sau).
  - Tự động tạo background scene phức tạp đa camera.
  - Huấn luyện model từ đầu.

## 3. Định nghĩa thành công
- Nhân vật nhìn “đang sống”, không bị cứng hình.
- Người xem có thể nhận ra rõ:
  - Ai đang nói.
  - Nội dung nói.
  - Nhịp nói chuyện có tương tác.
- Video không bị vỡ hình/vỡ âm, subtitle khớp thời gian.

## 4. Input contract (bắt buộc)
### 4.1 Input files
- `image_input`:
  - Định dạng: `.png` / `.jpg`
  - Độ phân giải khuyến nghị: >= 1280 px cạnh dài
  - Có tối đa 2 nhân vật trong khung (phiên bản đầu).
- `script.json`:
  - Chứa danh sách lượt nói và speaker.
  - Cho phép set pause, emotion, emphasis.
- `config.yaml` (tùy chọn):
  - Chọn model, style, fps, output ratio.

### 4.2 Mẫu `script.json`
```json
{
  "project_id": "video_project_35",
  "language": "en",
  "speakers": [
    {"id": "A", "voice": "female_1"},
    {"id": "B", "voice": "male_1"}
  ],
  "turns": [
    {"speaker": "A", "text": "Have you ever said I'll do it tomorrow?", "pause_after_ms": 300},
    {"speaker": "B", "text": "And tomorrow never comes.", "pause_after_ms": 250}
  ],
  "bgm": {"enabled": true, "ducking_db": -12}
}
```

## 5. Output contract (bắt buộc)
- `final_video.mp4` (H.264 + AAC)
- `subtitles/final.srt`
- `audio/dialogue_mix.wav`
- `timeline/timeline.json` (thời gian từng turn, cue, animation event)
- `reports/qc_report.json` (chỉ số chất lượng)
- `manifest.json` (tổng hợp tất cả artifacts)

## 6. Thiết kế output để quản lý dễ dàng
```text
output/
  projects/
    <project_id>/
      input/
      assets/
        characters/
        background/
      audio/
        tts_raw/
        processed/
      motion/
        char_A/
        char_B/
      subtitles/
      timeline/
      render/
        final_video.mp4
      reports/
      manifest.json
```

## 7. Pipeline kỹ thuật để xây dựng
### 7.1 Preprocess ảnh
- Face detect + character detect.
- Tách nhân vật (segmentation): ưu tiên `SAM2`/`RobustVideoMatting`/`U2Net`.
- Tạo layer:
  - Foreground character A
  - Foreground character B
  - Background clean plate (inpaint nếu cần)

### 7.2 Voice generation (TTS)
- Mục tiêu: 2 giọng khác nhau, rõ chữ, ổn định cao độ.
- Kỹ thuật gợi ý:
  - `Kokoro TTS` (nếu đã có trong project), hoặc `XTTSv2`.
  - Post-process: loudness normalize (target LUFS), denoise nhẹ.
- Output:
  - `audio/tts_raw/<speaker>/<turn_id>.wav`
  - `audio/processed/dialogue_aligned.wav`

### 7.3 Dialogue timing + interaction engine
- Lập lịch turn theo script:
  - Speaker đang nói = active.
  - Speaker còn lại = listen state (blink/nod).
- Chèn pause tự nhiên giữa câu.
- Có module `interaction planner`:
  - Tạo event: `look_at`, `nod`, `smile`, `idle_shift`.

### 7.4 Lip-sync và facial animation
- Mục tiêu: miệng khớp phát âm, mắt/chớp mắt tự nhiên.
- Kỹ thuật gợi ý:
  - Lip-sync: `Wav2Lip` (ổn định, dễ triển khai).
  - Face motion: `LivePortrait` hoặc `SadTalker` cho head motion nhẹ.
- Quy tắc:
  - Không để “speaking face” đứng yên khi có âm thanh.
  - Non-speaking character vẫn có motion nhẹ (không đứng hình).

### 7.5 Compositing và render
- Dùng `ffmpeg`/`moviepy`:
  - Ghép layer nhân vật + background.
  - Add subtitle burn-in hoặc file rời.
  - Mix dialogue + bgm + sidechain ducking.
- Render presets:
  - 1080p, 30fps, CRF 18-23 (tùy profile).

### 7.6 Subtitle và transcript
- Nguồn:
  - Từ script gốc (ưu tiên)
  - Hoặc ASR verify để đối soát.
- Format:
  - `.srt` cho player
  - Optional burn-in cho social.

## 8. Yêu cầu chất lượng (Quality gates)
- Lip-sync:
  - Lệch môi-âm thanh <= 120ms (mục tiêu <= 80ms).
- Audio:
  - Âm lượng integrated: -16 LUFS +/- 2 (social).
  - Peak <= -1 dBTP.
- Visual:
  - Không flicker lớn, không artifact mặt/miệng nghiêm trọng.
- Timeline:
  - 100% turn có timestamp hợp lệ.
- Output:
  - Video play được trên player phổ biến (VLC, browser, mobile).

## 9. Yêu cầu phi chức năng
- Chạy được trên Windows (venv của project).
- Có cơ chế fallback:
  - Nếu segmentation lỗi -> báo lỗi rõ + stop.
  - Nếu subtitle auto fail -> vẫn xuất video không subtitle.
- Logging đầy đủ:
  - Bất kỳ bước fail đều có stacktrace + error code.
- Khả năng mở rộng:
  - Từ 2 speaker lên N speaker (mốc version sau).

## 10. Kiến trúc code đề nghị
```text
src/
  step2_generate/
    cli.py
    pipeline.py
    preprocess.py
    tts_engine.py
    timing_engine.py
    lip_sync.py
    compositor.py
    subtitles.py
    qc.py
    io_schema.py
```

## 11. CLI yêu cầu
```bash
python -m src.step2_generate.cli \
  --image "input/scene.png" \
  --script "input/script.json" \
  --project-id "video_project_35" \
  --ratio "16:9" \
  --fps 30
```

## 12. Danh sách kỹ thuật mong muốn có
- Character segmentation từ ảnh tĩnh.
- Multi-speaker TTS có profile giọng.
- Turn-based interaction planner.
- Lip-sync theo từng speaker.
- Idle motion + reaction motion cho speaker không nói.
- Auto subtitle từ script + burn-in option.
- Audio mixing (dialogue + bgm + ducking).
- QC report và manifest để audit kết quả.

## 13. Tiêu chí nghiệm thu (Acceptance criteria)
- Có thể tạo ra 1 video 20-60s từ 1 ảnh + script.
- 2 nhân vật thay phiên nói, không bị “frozen face”.
- Subtitle khớp nội dung và mốc thời gian.
- Folder output đầy đủ theo cấu trúc đã định nghĩa.
- Có `qc_report.json` và `manifest.json`.

## 14. Rủi ro và giải pháp
- Rủi ro: lip-sync kém khi audio TTS không rõ.
  - Giải pháp: normalize/denoise TTS trước lip-sync.
- Rủi ro: mặt/hàm bị artifact khi chuyển động mạnh.
  - Giải pháp: giới hạn mức motion, ưu tiên motion nhẹ.
- Rủi ro: render chậm.
  - Giải pháp: cache intermediate artifacts theo project_id.

## 15. Lộ trình triển khai đề xuất
1. MVP:
   - 1 ảnh, 2 speaker, subtitle, output 1080p.
2. Enhanced:
   - Reaction system, camera move nhẹ, style presets.
3. Production:
   - Batch mode, dashboard QC, retry/fallback thông minh.
