# Project History Building: English Podcast Video Generator

Tài liệu này đóng vai trò như một kho lưu trữ lịch sử phát triển (History Building) của dư án `make_video_with_image`. Nó sẽ ghi nhận lại toàn bộ tiến trình thiết kế, các quyết định kiến trúc quan trọng, và các tính năng đã được hoàn thiện qua từng giai đoạn.

---

## 🟢 PHASE 1: Podcast Audio & Training Data Pipeline
**Status:** Đã hoàn thành (*Ngày 24/02/2026 - 11:15*)

Mục tiêu của Giai đoạn 1 là tự động hóa khâu sản xuất kịch bản và diễn hoạt âm thanh chất lượng cao, đồng thời xây dựng một hệ thống thu thập dữ liệu (Data Harvesting) ngầm để phục vụ huấn luyện mô hình AI Voice Cloning.

### 1.1. Kiến Trúc Lõi (Core Architecture)
Hệ thống xử lý kịch bản và âm thanh bao gồm 2 module chính được kết nối tuần tự:
- **`podcast_generator.py`**: Chịu trách nhiệm khởi tạo kịch bản từ LLM (Gemini 2.5 Flash), định tuyến thành dữ liệu JSON.
- **`kokoro_tts.py`**: Khối động cơ nhận JSON và kết xuất âm thanh Text-To-Speech thông qua mô hình Kokoro-82M.

### 1.2. Tính Năng Đã Hoàn Thiện (Features Done)

#### A. Dual-Text Architecture (Kịch bản Kép)
- **Thiết kế**: Prompt hệ thống yêu cầu LLM chia tách một câu thoại thành 2 định dạng:
  - `text_display`: Văn bản sạch (Dùng cho phụ đề, ebook, màn hình hiển thị).
  - `text_tts`: Văn bản đạo diễn chứa các thẻ paralinguistics và dấu ngắt câu (`[word](+2)`, `...`, `,`) nhằm thao túng trực tiếp nhịp điệu của máy đọc Kokoro.

#### B. Nâng cấp Engine Âm Thanh (Kokoro TTS Tuning)
- **Auto-Trim Silence**: Khắc phục lỗi cơ hữu của các máy TTS (thường để dư khoảng lặng đầu cuối) bằng cách triển khai thuật toán `detect_leading_silence` của `pydub`. Máy tự động cắt gọt khoảng lặng thừa và duy trì một nhịp thở hoàn hảo `100ms` giữa các câu thoại.
- **Speed Mapping**: Lập bản đồ tốc độ phát thanh tùy chỉnh (Alex: `1.0`, Sarah: `0.85`), giúp hội thoại trở nên tự nhiên.
- **Subtitles & Phonemes Extraction**: Tự động đo lường thời gian mili-giây (`start`, `end`) và xuất toàn bộ hệ thống siêu dữ liệu âm vị (Phonemes) của từng từ vào tệp `subtitles.json`.

#### C. AI Dataset Harvesting (Trại Dữ liệu Huấn luyện AI)
- **Tự động trích xuất vớt vát dữ liệu ngầm**: Trong lúc rèn đúc ra file MP3 tổng, máy trích xuất các dải âm lẻ tẻ và text sạch tương ứng vào hệ thống thư mục theo quy chuẩn Machine Learning.
- **Cấu trúc lưu trữ thư mục**:
  ```text
  data/
   ├── {Tên_Nhân_Vật}/
   │    └── {Ngày_Giờ}_{Tên_Topic}/
   │           ├── alex_1.wav (Audio wav ngắn gọn)
   │           └── alex_1.txt (Transcript text đi kèm)
  ```
- **Metadata CSV File**: Khởi tạo tự động tệp `dataset_metadata.csv` sử dụng đường dẫn ảo (ví dụ: `data/Alex/20260224_...`), tương thích 100% với chuẩn **LJSpeech Format** để có thể cắm trực tiếp vào phần mềm train TTS hoặc VITS.

---

## 🟡 PHASE 2: Video Timeline & Visual Rendering (Trình Bày Hình Ảnh & Âm Thanh)
**Status:** Đã hoàn thành

Mục tiêu của Giai đoạn 2 là kết nối Dữ liệu Kịch bản, mốc Thời gian Ảo với Engine Đồ họa nhằm kết xuất một Video Audio-Podcast mượt mà, chuyên nghiệp với hiệu ứng thời gian thực. Bỏ qua hoàn toàn các giới hạn nặng nề của MoviePy cũ.

### 2.1. Kiến Trúc Lõi (Core Architecture)
- **`video_renderer.py`**: Trái tim của toàn bộ quy trình thị giác. Sử dụng cơ cấu vẽ tay "Frame by Frame" bằng `PIL (Pillow)` kết hợp tính toán mảng của `Numpy`, kết thúc bằng việc đẩy luồng sang CPU Encoder (`libx264`) với chuẩn nén tối đa tương thích 100% mọi trình phát video.

### 2.2. Các Đột Phá Kỹ Thuật (Key Technical Features)

#### A. Thuật Toán Đồng Bộ Âm Thanh Tuyệt Đối (DTW Speech Alignment)
- Whisper AI bản thân có độ trễ và tỷ lệ rớt chữ (đặc biệt khi đọc nhanh, dính âm hoặc nuốt từ như "and", "the"). 
- **Giải pháp**: Xây dựng thuật toán **Dynamic Time Warping (DTW)** sử dụng `difflib.SequenceMatcher`. So khớp chuỗi mốc thời gian chập chờn của Whisper với 100% văn bản Ground-Truth (Kịch bản gốc siêu sạch chứa đầy đủ số liệu và dấu câu).
- **Linear Interpolation (Nội Suy Tuyến Tính)**: Nếu phát hiện Whisper bỏ sót từ, hệ thống tự động bám đuổi khoảng trống thời gian và chèn các mốc thời gian nhân tạo (Fake Timestamps) vá hoàn hảo lỗ hổng. **Kết quả: Cứu sống toàn bộ 100% văn bản, không mất bất cứ một kí tự nào.**

#### B. Động Cơ Karaoke Tích Lũy (Accumulated Caterpillar Line-Based)
- Bỏ qua TextClip truyền thống, tự thiết kế cấu trúc Word-Wrap chữ khớp sát màn hình.
- **Hiệu ứng Nhấn chữ (Highlighter)**: Sinh ra duy nhất một khối Khung Hình Ruy-Băng dãn dài ra bọc lấy từng chữ khi đến nhịp hát. Khung này KHÔNG bị đứt đoạn giữa các chữ (không bị lồi lõm góc viền). Chữ nào đọc rồi khung sẽ đóng băng nền (Lưu vết) lấp kín toàn bộ câu. Text nằm lọt trong vùng highlight sẽ luôn giữ viền đen stroke mượt mà, độ tương phản tuyệt đối mang âm hưởng Podcast chuyên nghiệp.

#### C. Hệ Thống Dải Sóng Âm (Symmetric Voice-Memo Visualizer)
- Tạm biệt các chóp sóng âm vô trí nhấp nháy điên loạn. Bộ Visualizer được viết bằng Toán học Đỉnh cao:
  - Phân tích khối âm thanh bằng **FFT (Fast Fourier Transform)**, ánh xạ theo dải Logarithmic (tương tự đồ thị Amply chuyên dụng) nhạy bén với từng biên độ từ `-25dB đến +25dB`.
  - **Symmetric Pod Waveform**: Rã hình cột Sóng thành dạng con Nhộng (Capsule), mọc nẩy đối xứng lên trên và xuống dưới tâm màn hình giống hệt biểu tượng Apple Voice Memos. Bọc thêm dải Parabol làm Phồng to các dải âm thanh giọng nói ở giữa và thóp nhọn dàn ra dải Treble mỏng ở 2 biên.
  - **Trọng lực Ảo (EMA Smoothing - Gravity Fall)**: Khi nhân vật ngừng lấy hơi, các thanh EQ không bao giờ sụp biến mất đột ngột mà được kìm giữ bởi lực quán tính (`factor=0.7`). Sóng rơi tà tà làm trải nghiệm mắt nhìn mịn như nhung trên màn hình tần số quét cao.

#### D. Vá Các Lỗi Nền Tảng (Bug Fixes & Hardware Failsafes)
- Khắc phục lỗi Rendering phần cứng sinh ra "Màn hình trắng xóa" (White/Grey Screen Issue).
- **Nguyên nhân**: Thuật nén YUV420P MP4 bắt buộc chiều rộng và chiều cao khung hình phải là số chẵn (`Divisible by 2`); nhưng tấm ảnh nền ban đầu có số lẻ (`1183x720`).
- **Giải quyết**: Trình Render tự động nhận diện, cắt gọt đi 1 pixel lẻ ngay điểm chốt để đưa thông số MP4 về Form chẵn mà không làm ảnh hưởng ảnh nền. Cho phép luồng nén Libx264 qua mặt bộ phân tích MP4 của Windows một cách dễ dàng, đạt độ tương thích thiết bị hoàn chỉnh.

---

