# Mục Tiêu Sản Xuất Short Video (Theo Mẫu Reel 1437556281494266)

## 1. Phân tích mẫu tham chiếu
Nguồn phân tích:
- [manifest.json](D:/work/Personal_project/make_short_video_youtube/output/facebook/1437556281494266/metadata/manifest.json)
- [1437556281494266.info.json](D:/work/Personal_project/make_short_video_youtube/output/facebook/1437556281494266/metadata/1437556281494266.info.json)
- [1437556281494266.mp4](D:/work/Personal_project/make_short_video_youtube/output/facebook/1437556281494266/media/1437556281494266.mp4)

Đặc trưng kỹ thuật:
- Tỷ lệ khung hình: `9:16` (dọc).
- Độ phân giải: `1440x2560`.
- Độ dài: `~28.93s`.
- Âm thanh: `AAC`, tốc độ nói khoảng `120 WPM` (58 từ/28.9s).

Đặc trưng bố cục:
- Bố cục 2 tầng cố định:
  - Tầng trên: ảnh minh họa chủ đề (dạng collage comic), tiêu đề song ngữ.
  - Tầng dưới: đoạn text tiếng Anh + đoạn dịch tiếng Việt.
- Chuyển động chính: karaoke highlight theo từng từ/cụm từ trên đoạn tiếng Anh.
- Chuyển động nền rất ít (gần như ảnh tĩnh + lớp highlight động).

Đặc trưng nội dung:
- Chủ đề học tiếng Anh theo ngữ cảnh đời sống (`The Brave Firefighter`).
- 1 voice đọc đoạn tiếng Anh ngắn, rõ, tốc độ trung bình.
- Mục tiêu giáo dục: từ vựng + hiểu nội dung + song ngữ.


## 2. Kết luận về “dạng video” cần sản xuất
Để tạo video giống mẫu này, pipeline cần ưu tiên:
- `Nội dung` ngắn, súc tích, phù hợp nghe trong 25-35 giây.
- `TTS + đồng bộ từ` chính xác (word-level timestamps).
- `Bố cục chuẩn hóa` (template cố định để scale số lượng video).
- `Dữ liệu song ngữ` (EN chính + VI phụ).

Không cần:
- Motion character phức tạp.
- Camera move nặng.
- Nhiều scene cinematic.


## 3. Quy trình sản xuất đề xuất (chia giai đoạn)

## Giai đoạn 0: Planning & Input
Input:
- Topic hoặc niche (`firefighter`, `doctor`, `daily routine`, ...).
- Mức độ tiếng Anh (`A2/B1/B2`).
- Độ dài target (`25-35s`).

Output:
- `production_request.json` chứa cấu hình video.

## Giai đoạn 1: Sinh dữ liệu nội dung bằng API (LLM)
Mục tiêu:
- Tạo nội dung mới theo topic nhưng giữ format “short educational reel”.

Output chuẩn đề xuất:
```json
{
  "topic": "The Brave Firefighter",
  "title_en": "THE BRAVE FIREFIGHTER",
  "title_vi": "CHÚ LÍNH CỨU HỎA DŨNG CẢM",
  "text_en": "Firefighters are real-life heroes ...",
  "text_vi": "Lính cứu hỏa là những người hùng ...",
  "hashtags": ["#tienganhmoingay", "#hoctienganh", "#firefighter"],
  "difficulty": "A2-B1",
  "target_duration_sec": 30
}
```

Ràng buộc nội dung:
- `text_en`: 45-70 từ.
- Câu ngắn, dễ nghe, chủ đề rõ.
- `text_vi`: dịch tự nhiên, nghĩa sát.
- Tránh câu quá dài gây lệch karaoke.

## Giai đoạn 2: Tạo audio narration
Input:
- `text_en`.

Output:
- `audio.mp3` (hoặc `audio.wav`) giọng rõ, tốc độ ổn định.

Yêu cầu:
- Loudness mục tiêu: khoảng `-16 LUFS` cho social.
- Không clipping.

## Giai đoạn 3: Căn chỉnh thời gian từ (forced alignment)
Input:
- `audio`.
- `text_en`.

Output:
- `word_timings.csv/json` (word, start, end).

Ghi chú:
- Có thể dùng luồng giống [create_karaoke_video.py](D:/work/Personal_project/make_short_video_youtube/src/create_karaoke_video.py) (Whisper + chỉnh tay nếu cần).
- Với production số lượng lớn, nên có auto-pass và chỉ mở manual editor khi confidence thấp.

## Giai đoạn 4: Tạo asset hình ảnh
Input:
- `topic`, `title_en/title_vi`.

Output:
- `top_image.png` (ảnh minh họa ở tầng trên).
- Tuỳ chọn: logo, icon, watermark.

Nguồn:
- Tự vẽ AI image theo prompt.
- Hoặc thư viện ảnh/chibi cố định theo chủ đề.

## Giai đoạn 5: Render video template
Input:
- `top_image.png`
- `audio`
- `text_en`, `text_vi`, `title_en`, `title_vi`
- `word_timings`

Output:
- `final.mp4` (9:16, 1080x1920 hoặc 1440x2560).

Template render:
- Top zone: ảnh + tiêu đề.
- Bottom zone: đoạn EN/VI.
- Overlay highlight theo timestamps.

## Giai đoạn 6: QC tự động
Checklist:
- Video play được.
- Duration trong ngưỡng 25-35s.
- Có audio.
- Subtitle highlight không lệch lớn (`<=120ms`).
- Không tràn chữ khỏi khung.

Output:
- `qc_report.json`.

## Giai đoạn 7: Đóng gói dữ liệu và publish-ready
Output:
- `manifest.json`.
- `final.mp4`.
- `content.json` (nội dung gốc).
- `timings.csv`.


## 4. Tinh chỉnh từ podcast_generator.py cho mục tiêu hiện tại
File tham chiếu:
- [podcast_generator.py](D:/work/Personal_project/make_video_with_image/scripts/podcast_generator.py)

Có thể tái dùng trực tiếp:
- Luồng gọi API qua OpenRouter (`OpenAI(base_url=...)`).
- Cơ chế retry + validate JSON.
- Cách build prompt và kiểm tra output schema.

Cần thay đổi lớn:
- Từ `9 segment podcast dài` -> `1 short script duy nhất`.
- Bỏ format multi-speaker phức tạp.
- Bỏ PDF pipeline.
- Thêm trường song ngữ (`title_vi`, `text_vi`).
- Thêm kiểm tra độ dài target theo giây (ước lượng theo WPM).

Schema mới nên dùng cho short:
```json
{
  "topic": "...",
  "title_en": "...",
  "title_vi": "...",
  "text_en": "...",
  "text_vi": "...",
  "difficulty": "A2-B1",
  "hashtags": []
}
```


## 5. Kiến trúc code đề xuất cho mục tiêu “sản xuất hàng loạt”
```text
make_short_video_youtube/
  src/
    pipeline/
      step1_generate_content.py
      step2_generate_audio.py
      step3_align_words.py
      step4_build_assets.py
      step5_render_video.py
      step6_qc.py
      run_pipeline.py
  templates/
    reel_layout_v1.json
  output/
    short_video/<topic_slug>/<project_id>/...
```

Nguyên tắc:
- Mỗi bước ghi output trung gian rõ ràng.
- Bước sau đọc output bước trước, dễ debug và rerun từng bước.


## 6. Định dạng output chuẩn để dễ quản lý
```text
output/
  short_video/
    <topic_slug>/
      <project_id>/
        01_content/
          content.json
        02_audio/
          audio.mp3
        03_alignment/
          word_timings.csv
        04_assets/
          top_image.png
        05_render/
          final.mp4
        06_qc/
          qc_report.json
        manifest.json
```


## 7. Đề xuất chiến lược triển khai thực tế
MVP (ưu tiên làm ngay):
1. Tạo `step1_generate_content.py` (từ topic -> content.json song ngữ).
2. Dùng TTS hiện có để tạo audio.
3. Tái dùng renderer hiện tại để xuất video template.
4. Thêm QC cơ bản + manifest.

Phase 2:
1. Auto tạo top image theo prompt chủ đề.
2. Tinh chỉnh karaoke offset tự động theo giọng.
3. Batch mode tạo nhiều video từ danh sách topic.

Phase 3:
1. A/B test hook mở đầu.
2. Tự tối ưu độ dài câu theo retention.
3. Dashboard theo dõi hiệu suất nội dung.


## 8. Quy tắc nội dung để giữ chất lượng đồng đều
- Mỗi reel chỉ tập trung 1 chủ đề nhỏ.
- 1 đoạn EN duy nhất, tránh nhảy ý.
- Dịch VI rõ, không quá “dịch word-by-word”.
- Ưu tiên từ vựng hữu ích đời sống.
- Kết thúc bằng 1 câu truyền cảm hứng hoặc CTA nhẹ.
