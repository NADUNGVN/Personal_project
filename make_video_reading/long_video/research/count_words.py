import os
from pathlib import Path
from faster_whisper import WhisperModel

def analyze_video_word_count(video_path):
    print("=" * 60)
    print("🔬 CÔNG CỤ NGHIÊN CỨU SỐ LƯỢNG TỪ VỰNG TỪ VIDEO MẪU")
    print("=" * 60)

    # 1. Khởi tạo Faster Whisper Models giống chuẩn của bạn
    print("\n[1/3] Đang tải mô hình Whisper AI (large-v3)...")
    device = "cuda" if os.environ.get("CUDA_VISIBLE_DEVICES") != "-1" else "cpu"
    compute_type = "float16" if device == "cuda" else "int8"
    
    try:
        whisper_model = WhisperModel("large-v3", device=device, compute_type=compute_type)
        print(f"✅ Đã tải xong WhisperModel (Device: {device}, Compute: {compute_type})")
    except Exception as e:
        print(f"❌ Lỗi khởi tạo mô hình: {e}")
        return

    # 2. Xử lý bóc tách âm thanh
    print(f"\n[2/3] Đang nhúng file và đếm từ vựng: {os.path.basename(video_path)} ...")
    try:
        # word_timestamps=True bắt buộc để nó đếm list từng chữ rành mạch
        segments, info = whisper_model.transcribe(video_path, word_timestamps=True)
        
        all_words = []
        transcript_text = ""
        prev_end = 0.0
        
        for segment in segments:
            # 1. Tính toán khoảng lặng (Gap) giữa kết thúc câu trước và bắt đầu câu này
            gap = segment.start - prev_end
            
            # 2. Xử lý logic xuống dòng dựa trên Silence Gap
            if prev_end > 0.0:
                # Nếu người nói nghỉ lấy hơi hoặc ngập ngừng hơn 0.8 giây -> Xuống dòng tạo khổ mới
                if gap >= 0.8:
                    transcript_text += "\n\n"
                else:
                    transcript_text += " "
                    
            transcript_text += segment.text.strip()
            prev_end = segment.end
            
            # Ghi nhận từ vựng
            if segment.words:
                for w in segment.words:
                    all_words.append({
                        'word': w.word.strip(),
                        'start': w.start,
                        'end': w.end
                    })

        # Môi giới xuống dòng thông minh sau dấu Phẩy, dấu Chấm
        transcript_text = transcript_text.replace(", ", ",\n").replace(". ", ".\n").replace("? ", "?\n").replace("! ", "!\n")
        
        total_words = len(all_words)
        total_duration = info.duration

        print(f"\n✅ Đã Tách Thành Công!")
        print("-" * 40)
        print(f"📊 THỐNG KÊ KẾT QUẢ:")
        print(f"- Tổng số từ (Word Count): {total_words} từ")
        print(f"- Thời lượng video     : {total_duration:.2f} giây")
        if total_duration > 0:
            print(f"- Tốc độ đọc trung bình: {total_words / total_duration:.2f} từ/giây")
        print("-" * 40)

        # 3. Lưu kết quả ra file Text để bạn xem nghiên cứu
        output_dir = Path(__file__).resolve().parent / "output"
        output_dir.mkdir(parents=True, exist_ok=True)
        
        transcript_path = output_dir / "transcript_result.txt"
        with open(transcript_path, "w", encoding="utf-8") as f:
            f.write(f"Tổng số từ: {total_words}\n")
            f.write(f"Thời lượng: {total_duration:.2f} giây\n")
            f.write("=" * 40 + "\n\n")
            f.write("NỘI DUNG BÓC BĂNG:\n")
            f.write(transcript_text.strip())
            
        print(f"\n[3/3] Đã lưu bản nháp văn xuôi vào: {transcript_path}")

    except Exception as e:
        print(f"\n❌ Lỗi trong quá trình bóc băng: {e}")

if __name__ == "__main__":
    vid_path = input("\nNhập đường dẫn tuyệt đối CỦA FILE VIDEO MP4 MẪU: ").strip(' "\'')
    if not os.path.exists(vid_path):
        print("❌ File không tồn tại! Vui lòng kiểm tra lại đường dẫn.")
    else:
        analyze_video_word_count(vid_path)
