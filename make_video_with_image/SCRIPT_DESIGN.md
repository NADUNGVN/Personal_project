# 📜 Script Generation Design — Multi-Step Pipeline

Tài liệu kỹ thuật mô tả thiết kế quy trình tạo kịch bản podcast theo phương pháp **Multi-Step Generation** với **Full-Context Chain**.

---

## Nguyên Tắc Thiết Kế

1. **Bỏ PDF input** — Chỉ cần tên topic duy nhất làm đầu vào
2. **9 phân đoạn**, mỗi phân đoạn = 1 API call riêng biệt
3. **Full-Context Forwarding**: Mỗi step nhận **TOÀN BỘ kịch bản đã sinh** từ tất cả step trước (dạng text sạch `text_display`) → LLM hiểu trọn vẹn mạch truyện, không bị đứt gãy
4. **Merge** tất cả segment thành 1 file JSON chuẩn duy nhất (tương thích 100% với `kokoro_tts.py` và `video_renderer.py`)
5. **Validate + Retry**: Mỗi segment output được kiểm tra schema trước khi tiếp tục, retry tối đa 2 lần nếu lỗi

---

## Chuỗi Phụ Thuộc (Full-Context Chain)

```
Step 1: prompt(topic)                                          → segment_1
Step 2: prompt(topic, text_of[1])                              → segment_2
Step 3: prompt(topic, text_of[1,2])                            → segment_3
Step 4: prompt(topic, text_of[1,2,3])                          → segment_4
Step 5: prompt(topic, text_of[1,2,3,4])                        → segment_5
Step 6: prompt(topic, text_of[1,2,3,4,5])                      → segment_6
Step 7: prompt(topic, text_of[1,2,3,4,5,6])                    → segment_7
Step 8: prompt(topic, text_of[1,2,3,4,5,6,7])                  → segment_8
Step 9: prompt(topic, text_of[1,2,3,4,5,6,7,8])                → segment_9
```

**Context format**: Ghép `text_display` theo dạng:
```
[Heading: Tên phân đoạn]
Speaker: Nội dung dialogue...
Speaker: Nội dung dialogue...
```

---

## 9 Phân Đoạn Chi Tiết

### 1. Intro
| Thuộc tính | Giá trị |
|-----------|---------|
| Speaker | Alex + Sarah |
| Mục tiêu | Chào hỏi, trò chuyện vui vẻ ngắn, giới thiệu kênh, gợi mở chủ đề |
| Số lượt thoại | ~6–8 |
| Quy tắc đặc biệt | Heading MỨT ÂM (speaker="", text_tts=""). Alex PHẢI nói đầu tiên trong phần dialogue |

### Quy Tắc Heading (Áp dụng cho tất cả segment)

Mỗi heading item có 4 field quan trọng:

| Field | Mục đích | Nội dung |
|-------|---------|----------|
| `title` | **PDF ebook** (tiêu đề chương) | Ngắn gọn, tối đa 8 từ |
| `text_display` | **Karaoke video** (chữ chạy trên màn hình) | Câu dẫn chuyển đầy đủ của host |
| `text_tts` | **Kokoro TTS** (âm thanh) | Câu dẫn chuyển + markup nhấn giọng |
| `speaker` | Host nói | `"Alex"` hoặc `"Sarah"` |

**NGOẠI LỆ — Heading MỨT ÂM (Intro & Outro):**
- `speaker=""`, `text_tts=""`, `text_display` = same as `title`
- Không phát âm, không hiện karaoke
- Chỉ xuất hiện trong PDF
- Dialogue tiếp theo bắt đầu nói trực tiếp

### 2. Topic Introduction
| Thuộc tính | Giá trị |
|-----------|---------|
| Speaker | Alex + Sarah |
| Mục tiêu | Giới thiệu chủ đề hôm nay, dẫn dắt giải thích, dạy 3–4 vocabulary/phrases cốt lõi |
| Số lượt thoại | ~10–15 |
| Quy tắc | Heading có speaker đọc. Vocabulary phải tự nhiên, không liệt kê khô khan |

### 3. Audio #1 (Roleplay)
| Thuộc tính | Giá trị |
|-----------|---------|
| Speaker | Tùy biến — Michael+Nicole / Alex+Sarah / Adam+Sky |
| Mục tiêu | Roleplay/câu chuyện ứng dụng vocabulary đã dạy ở Step 2 |
| Số lượt thoại | ~15–20 |
| Quy tắc | Nhân vật PHẢI nằm trong danh sách Kokoro VOICE_MAP: Alex, Sarah, Michael, Nicole, Adam, Sky |

### 4. Analysis & Vocabulary Breakdown
| Thuộc tính | Giá trị |
|-----------|---------|
| Speaker | Alex + Sarah |
| Mục tiêu | Phân tích Audio #1, tháo banh vocabulary, phrasal verbs, idioms |
| Số lượt thoại | ~8–12 |
| Quy tắc | Tham chiếu trực tiếp đến câu nói trong Audio #1 |

### 5. Topic Part 2
| Thuộc tính | Giá trị |
|-----------|---------|
| Speaker | Alex + Sarah |
| Mục tiêu | Chuyển sang khía cạnh khác của topic, dạy vocabulary mới + common mistakes |
| Số lượt thoại | ~10–12 |
| Quy tắc | Không lặp vocabulary đã dạy ở Step 2 |

### 6. Audio #2 (Roleplay)
| Thuộc tính | Giá trị |
|-----------|---------|
| Speaker | Tùy biến — cặp nhân vật KHÁC với Audio #1 |
| Mục tiêu | Roleplay ứng dụng vocabulary mới từ Step 5 |
| Số lượt thoại | ~15–20 |
| Quy tắc | Phải dùng cặp nhân vật khác Audio #1 |

### 7. Analysis & Level Comparison
| Thuộc tính | Giá trị |
|-----------|---------|
| Speaker | Alex + Sarah |
| Mục tiêu | So sánh trình độ B1 vs B2, phân tích cách diễn đạt trong Audio #2 |
| Số lượt thoại | ~8–12 |
| Quy tắc | Chỉ ra sự khác biệt rõ ràng giữa cách nói B1 và B2 |

### 8. Episode Recap
| Thuộc tính | Giá trị |
|-----------|---------|
| Speaker | Alex + Sarah |
| Mục tiêu | Tóm tắt nhanh toàn bộ vocabulary + key points đã học |
| Số lượt thoại | ~6–8 |
| Quy tắc | Recap TOÀN BỘ episode, không bỏ sót phần nào |

### 9. Outro
| Thuộc tính | Giá trị |
|-----------|---------|
| Speaker | Alex + Sarah |
| Mục tiêu | Cảm ơn, CTA subscribe/like, tạm biệt |
| Số lượt thoại | ~4–6 |
| Quy tắc | Heading MỨT ÂM (speaker="", text_tts=""). Alex PHẢI nói đầu tiên trong phần dialogue. Không lặp lại nội dung Recap |

---

## JSON Output Schema (Mỗi Segment)

```json
{
  "segment_id": 2,
  "segment_name": "Topic Introduction",
  "script": [
    {
      "type": "heading",
      "speaker": "Alex",
      "title": "Understanding Healthy Habits",
      "text_display": "Alright, so today we're diving into something really exciting: healthy habits!",
      "text_tts": "[Alright](+2), so today we're diving into something [really](+2) exciting: [healthy habits](+2)!"
    },
    {
      "type": "dialogue",
      "speaker": "Sarah",
      "text_display": "Oh, I love this topic!",
      "text_tts": "Oh, I [love](+2) this topic!"
    }
  ]
}
```

## Merged JSON Output Schema (Cuối Cùng)

```json
{
  "title": "English Podcast Everyday - {Topic Name}",
  "script": [
    // Tất cả items từ 9 segments ghép nối tuần tự
  ]
}
```

---

## Voice Casting (Kokoro TTS)

| Tên nhân vật | Voice ID | Vai trò |
|-------------|----------|---------|
| Alex | `am_puck` | Host nam, phân tích, giải thích grammar |
| Sarah | `af_bella` | Host nữ, nhiệt tình, đưa ví dụ sinh động |
| Michael | `am_michael` | Roleplay nam 1 |
| Nicole | `af_nicole` | Roleplay nữ 1 |
| Adam | `am_adam` | Roleplay nam 2 |
| Sky | `af_sky` | Roleplay nữ 2 |

---

## LLM Output — JSON Schema Chi Tiết

### Output mỗi Segment (LLM trả về)

LLM phải trả về **strictly valid JSON** (không markdown wrapper) theo format sau:

```json
{
  "segment_id": 3,
  "segment_name": "Audio Conversation #1: Weekend Plans",
  "script": [
    {
      "type": "heading",
      "speaker": "Sarah",
      "title": "Audio Conversation #1: Weekend Plans",
      "text_display": "Alright everyone, now let's hear a real conversation! Listen closely for those key phrases. Here's a chat between Michael and Nicole!",
      "text_tts": "[Alright](+2) everyone, now let's hear a [real](+2) conversation! [Listen closely](+2) for those key phrases. Here's a chat between Michael and Nicole!"
    },
    {
      "type": "dialogue",
      "speaker": "Michael",
      "text_display": "Hey Nicole! Do you have any plans for the weekend?",
      "text_tts": "[Hey](+2) Nicole! Do you have any plans... for the [weekend](+2)?"
    }
  ]
}
```

### Chi tiết từng field

| Field | Type | Mô tả | Bắt buộc |
|-------|------|--------|----------|
| `type` | `"heading"` \| `"dialogue"` | Heading = tiêu đề phân đoạn. Dialogue = lượt thoại | ✅ |
| `speaker` | string | Tên nhân vật. `""` cho Intro/Outro heading (mute) | ✅ |
| `title` | string | Tiêu đề ngắn cho PDF (max 8 từ). **Chỉ heading** | ✅ (heading) |
| `text_display` | string | **Heading**: câu dẫn đầy đủ (hiện karaoke). **Dialogue**: nội dung thoại | ✅ |
| `text_tts` | string | Văn bản **đạo diễn** cho Kokoro TTS. Chứa markup điều khiển giọng đọc | ✅ |

### TTS Markup trong `text_tts`

| Markup | Ý nghĩa | Ví dụ |
|--------|---------|-------|
| `[word](+2)` | **Nhấn mạnh** — đọc to, chậm hơn | `[really](+2) important` |
| `[word](-1)` | **Giảm nhẹ** — đọc nhẹ, nhanh hơn (filler words) | `[just](-1) a minute` |
| `...` | Ngắt nghỉ dài — LLM đang "suy nghĩ" | `Well... I think so` |
| `—` | Ngắt nghỉ ngắn — chuyển ý | `Right — so here's the thing` |
| `,` | Dừng nhẹ tự nhiên | `Actually, I agree` |
| `!` | Giọng phấn khích | `That's amazing!` |
| `?` | Ngữ điệu lên | `Really?` |

### Quy tắc đặc biệt cho Heading

| Trường hợp | `speaker` | `text_tts` | Hành vi Kokoro |
|-----------|-----------|------------|----------------|
| **Intro heading** (segment 1) | `""` (rỗng) | `""` (rỗng) | ❌ KHÔNG phát âm. Chỉ ghi timestamp |
| **Outro heading** (segment 9) | `""` (rỗng) | `""` (rỗng) | ❌ KHÔNG phát âm. Chỉ ghi timestamp |
| **Heading thường** (segment 2–8) | Tên host | Câu dẫn chuyển đầy đủ | ✅ Phát âm bình thường |

---

## Data Flow: JSON → PDF Ebook

File `{topic}_script.json` (merged) → class `PDF(FPDF)` → `{topic}_script.pdf`

```
┌─────────────────────────────────────────────────────┐
│ JSON Script Array                                   │
│                                                     │
│  item.type == "heading"                             │
│  ├── Đọc: item["title"] ← tiêu đề ngắn cho PDF    │
│  ├── Font: Helvetica Bold 16pt                     │
│  ├── Nền: Xanh nhạt (#F0F5FA)                     │
│  └── Chữ: Xanh đậm (#143264)                      │
│                                                     │
│  item.type == "dialogue"                            │
│  ├── Đọc: item["speaker"] + item["text_display"]   │
│  ├── Format: "**Speaker:** Text nội dung"          │
│  ├── Font: Helvetica 12pt                          │
│  └── Chữ: Xám đậm (#2D2D2D)                      │
│                                                     │
│  ⚠️ KHÔNG dùng text_tts cho PDF                    │
│  ⚠️ Heading dùng "title", Dialogue dùng "text_display" │
└─────────────────────────────────────────────────────┘
```

**Lưu ý**: PDF hiện chỉ hỗ trợ Latin-1 (emoji/Unicode bị thay `?`). Đây là hạn chế đã biết.

---

## Data Flow: JSON → Kokoro TTS

File `{topic}_script.json` (merged) → `kokoro_tts.py` → `{topic}_podcast.mp3` + `{topic}_subtitles.json`

```
┌──────────────────────────────────────────────────────────────┐
│ kokoro_tts.py xử lý từng item trong script[]                │
│                                                              │
│ Bước 1: PHÂN LOẠI                                           │
│ ├── item.type + item.speaker → Tra VOICE_MAP                │
│ │   Alex → "am_puck", Sarah → "af_bella", ...               │
│ ├── item.speaker → Tra SPEED_MAP                            │
│ │   Alex → 1.0, Sarah → 0.85, ...                           │
│ └── Nếu heading đầu tiên (idx==1) hoặc speaker=="" → SKIP  │
│                                                              │
│ Bước 2: SINH ÂM THANH                                       │
│ ├── Input: item["text_tts"] ← văn bản có markup TTS         │
│ ├── Kokoro pipeline(text_tts, voice, speed)                  │
│ ├── Auto-trim silence đầu/cuối (threshold -45dB)            │
│ └── Thêm pause: 300ms (heading) hoặc 100ms (dialogue)      │
│                                                              │
│ Bước 3: TIMESTAMPING                                         │
│ ├── Đo duration_ms = len(turn_audio)                        │
│ ├── start_time = current_time_ms (tích lũy từ đầu)         │
│ ├── end_time = start_time + duration_ms                     │
│ └── Ghi vào subtitles[] với item["text_display"] ← chữ sạch│
│                                                              │
│ Bước 4: GHÉP NỐI                                            │
│ ├── final_audio += turn_audio                               │
│ └── current_time_ms += duration_ms                          │
└──────────────────────────────────────────────────────────────┘
```

### Bảng ánh xạ Field: JSON → Kokoro → Output

| JSON Field | Kokoro dùng để | Output cuối |
|-----------|---------------|-------------|
| `type` | Phân loại heading/dialogue, quyết định skip hay render | `subtitles.json` → `type` |
| `speaker` | Tra `VOICE_MAP` lấy giọng, `SPEED_MAP` lấy tốc độ | `subtitles.json` → `speaker` |
| `text_display` | ❌ KHÔNG dùng cho TTS | `subtitles.json` → `text` (dùng cho video karaoke) |
| `text_tts` | ✅ Input chính cho Kokoro render âm thanh | `subtitles.json` → `text_tts` (lưu lại để debug) |

### Output cuối của Kokoro

**`{topic}_podcast.mp3`** — File MP3 master ghép nối liên tục (~20 phút)

**`{topic}_subtitles.json`** — Mảng timestamp cho video renderer:
```json
[
  {
    "idx": 1,
    "type": "heading",
    "speaker": "",
    "text": "Welcome to English Podcast Everyday",
    "text_tts": "",
    "phonemes": "",
    "start_time_sec": 0.0,
    "end_time_sec": 0.0,
    "duration_sec": 0,
    "voice_used": "None"
  },
  {
    "idx": 2,
    "type": "dialogue",
    "speaker": "Alex",
    "text": "Hello everyone, and welcome back to another episode!",
    "text_tts": "[Hello](+2) everyone, and [welcome](+2) back...",
    "phonemes": "hɛloʊ ɛvɹiwʌn...",
    "start_time_sec": 0.0,
    "end_time_sec": 3.45,
    "duration_sec": 3.45,
    "voice_used": "am_puck"
  }
]
```

---

*Tài liệu này là phần thiết kế kỹ thuật của hệ thống tạo kịch bản podcast. Cập nhật lần cuối: 01/03/2026.*
