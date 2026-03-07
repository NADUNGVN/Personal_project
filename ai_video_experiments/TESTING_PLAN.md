# 🧪 Kế Hoạch Thử Nghiệm Model AI Video (Lip-Sync & Gestures)

Dự án này (`ai_video_experiments`) được thiết lập nhằm mục đích nghiên cứu, đánh giá, và tìm ra model AI tối ưu nhất để sinh chuyển động từ ảnh tĩnh (Avatar) kết hợp với âm thanh (Audio).

Mục tiêu cốt lõi: Nâng cấp trải nghiệm hình ảnh cho MC ảo với khả năng:
1. **Nhép miệng (Lip-sync)** khớp xác thực với file âm thanh (Audio-driven).
2. **Cử chỉ tự nhiên (Gestures & Body Movements)** bao gồm gật đầu, vung tay, đung đưa người một cách phức tạp và có hồn.

---

## 💻 1. Thông Số Phần Cứng Hiện Tại & Thách Thức
*Lưu ý: Việc lựa chọn model phụ thuộc rất lớn vào sức mạnh tính toán thực tế.*
- **GPU:** NVIDIA GeForce RTX 5060 Laptop (VRAM: **8GB**)
- **CPU:** AMD Ryzen 9 8945HX (16 Cores, 32 Threads)
- **RAM:** 16 GB
- **Thách thức:** Với mức VRAM 8GB, cỗ máy của bạn đã chạm tới "tiêu chuẩn vàng tối thiểu" để chạy các model sinh video họ Diffusion (Hallo2, V-Express) và Pytorch3D (Mimic-Talk). Tuy nhiên, 8GB vẫn là mức khá sít sao cho các video độ phân giải cao hoặc render batch lớn, nên chúng ta vẫn cần phải ép dùng các kỹ thuật tối ưu bộ nhớ (như `xformers`, `cpu_offload` hoặc giảm `batch_size`) để tránh lỗi CUDA Out of Memory (OOM). Tốc độ render sẽ ở mức khá.

---

## 🎯 2. Đánh Giá Sơ Bộ Các Model Mục Tiêu

### Nhóm 1: Nhép Miệng Tương Tác Mặt (Lip-Sync Focus)
| Model | Năm Ra Mắt | Công Nghệ Lõi | Ưu Điểm | Nhược Điểm đối với VRAM 8GB |
|-------|------------|---------------|----------|-------------|
| **SadTalker** | 2023 | GAN (2D/3D Hybrid) | Rất nhẹ, siêu mượt. Chạy trên 8GB VRAM sẽ có tốc độ chóng mặt. | Hình ảnh có lúc bị mờ (blurry), đầu chuyển động như búp bê 3D cứng ngắc. Không có tay. |
| **LivePortrait** | 2024 | Video-driven / Landmark | Tốc độ kết xuất SIÊU TỐT. Ảnh cực kì sắc nét, không bị bóp méo hình gốc. | Bản chất cần Video người thật điều khiển. Khó kết hợp từ file Audio thuần nên phải qua môi giới. |
| **V-Express** | 2024 | Diffusion-based | Chất lượng ảnh đỉnh, điều khiển biểu cảm theo ảnh cực kỳ tốt. Khớp nhịp nói. | Với 8GB VRAM chạy ổn định, nhưng tốc độ render vẫn khá chậm so với GAN. Cần setup chuẩn. |
| **Hallo / Hallo2 / Hallo3** | 2024 - 2025 | Diffusion-based | Cực kì mạnh mẽ, video ra tới 4K. Bản Hallo3 mới nhất (CVPR 2025) mang lại chuyển động đầu cổ xuất sắc. | Rất nặng. Cần giới hạn độ phân giải hoặc chạy với patch rút gọn. Thời gian render vẫn sẽ khá dài cho video 20 phút. |
| **EchoMimic V2** | 2024 | Diffusion-based | Mới ra mắt cuối 2024, sinh chuyển động mượt, tự nhiên, xử lý background tốt. | Đòi hỏi tài nguyên phần cứng lớn tương đương họ Hallo/V-Express. |
| **EMO / EMO2** | 2024 - 2025 | Diffusion-based | Sản phẩm của Alibaba (Đầu 2025 cho bản EMO2). Hát và nói siêu mượt, rất có hồn. | Thường không công bố full source code hoặc rất khó setup cục bộ (thường xài qua cloud). |
| **GenFaceTalk** | 2024 - 2025 | Diffusion / NeRF | Nhấn mạnh vào tính biểu cảm và duy trì chi tiết khuôn mặt sắc nét. | Cần cài đặt hệ thống phụ thuộc phức tạp, ngốn VRAM nếu batch_size cao. |

### Nhóm 2: Cử Chỉ Và Chuyển Động Cơ Thể Dạng Phức Tạp (Gestures & Body Movements)
Đây là tầng nâng cao. Avatar cần có vung tay, đung đưa người "thông minh" đồng bộ với nhịp thở âm thanh.
| Model | Năm Ra Mắt | Công Nghệ Lõi | Ưu Điểm | Nhược Điểm đối với VRAM 8GB |
|-------|------------|---------------|----------|-------------|
| **Mimic-Talk** | 2024 | Expressive Full Avatar | Model đi tiên phong cho phép ghép cả khuôn mặt giàu biểu cảm VÀ thân thể theo một nhịp chung mượt mà. | Đã khả thi với 8GB VRAM. Tuy nhiên setup thư viện Pytorch3D khá chua và dễ đụng độ môi trường. |
| **Audio2Gestures / Audio2Photoreal** | 2021 - 2024 | Audio -> Skeleton -> Face | Sinh khung xương theo giọng điệu tự nhiên. Dành cho công nghiệp VR/3D. | Kỹ thuật quá phức tạp với 2D. Tốn thêm 1 bước trung gian làm pipeline bị kềnh càng. |
| **OmniAvatar** | 2023 - 2025 | Geometry-Guided / Adaptive Body | Phiên bản 2025 hứa hẹn tạo video avatar điều khiển cả body animation cực kỳ thông minh thích ứng với audio. | Đương nhiên sẽ cực kì nặng và bộ source code có thể vướng nhiều thư viện 3D kén card màn hình. |

---

## 🛠 3. Lộ Trình Triển Khai & Test (Execution Plan)

> **Luật Tối Thượng:** Cách ly môi trường (Anaconda hoặc Python Venv). Các Model AI này chứa các phiên bản PyTorch và CUDA cực kỳ chéo ngoe với nhau, cài chung thư mục sẽ phá huỷ hệ thống cũ!

### Bước 1: Chuẩn Bị Data Chuẩn (Baseline Dataset)
Tạo chung 1 thư mục `data_test`:
- Nguồn: 1 Ảnh thật đẹp (MC ảo), có hở tay và ngực.
- Đích: 1 File audio `.wav` khoảng 15 giây (Giọng rõ).

### Bước 2: Test Nhóm An Toàn (Khảo sát Tốc độ)
* **Start với SadTalker**: Cực tốt trên 8GB VRAM. Chạy thử nghiệm để benchmark pipeline *Audio -> Head Motion*. Đánh giá xem nó render mất bao nhiêu giây cứng với RTX 5060 8GB.
* **Nghiên cứu nối ghép LivePortrait**: Tìm source code cho phép "Audio-driven LivePortrait".

### Bước 3: Đụng Độ Nhóm Hạng Nặng (Kiểm tra Sinh Tử VRAM 8GB)
* Setup **V-Express** và **Hallo2**: 8GB là đủ để vượt qua bài test. Chỉ cần chú ý bật xformers. Chèn đoạn 15 giây âm thanh và ghi nhận log phần cứng chạy mất bao nhiêu thời gian. Ghi nhận đỉnh (peak) VRAM usage.

### Bước 4: Test Body Movement (Khó nhất)
* Build môi trường cho **Mimic-Talk**. Đánh giá mức độ lệch khung hình tay với đoạn nói nhanh/chậm và vẻ mặt.

---

## 📝 4. Cần Bạn Xác Nhận Phản Hồi (User Action Required)
1. **Dung lượng Ổ Cứng**: Các thư viện Pytorch, Diffusion và Checkpoints nặng cho 5 mô hình này sẽ **ngốn khoảng 40GB - 60GB dung lượng SSD**. Bạn cần check xem ổ `D:\` có đủ chỗ trống chưa.
2. **Kỳ Vọng Render trên 8GB VRAM**: Với 8GB VRAM, chúng ta CÓ THỂ chạy được toàn bộ các model trên. Tuy nhiên, thời gian render cho video dài hàng tiếng vẫn mệt mỏi. Halo2 và V-Express độ phân giải cao vẫn chiếm nhiều thời gian kết xuất video.
3. Chúng ta có thể "khô máu" thử nghiệm từ đầu bảng xuống cuối bảng.

Bạn muốn bắt đầu thiết lập môi trường Anaconda (Venv) cho **Mimic-Talk** (model có vung tay/body toàn diện) đầu tiên, hay bắt đầu với **Hallo2/V-Express** (chất lượng khuôn mặt tuyệt đối)?
