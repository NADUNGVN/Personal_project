import os
import sys
import time
from pathlib import Path
from generate_content import generate_motivational_script
from make_short import create_text_image, render_ffmpeg, get_video_duration

def run_pipeline(topic):
    print("="*60)
    print("   🚀 HỆ THỐNG SINH VIDEO LUYỆN ĐỌC TỰ ĐỘNG KHÉP KÍN   ")
    print("="*60)
    
    # Bước 1: Lựa chọn Mode đầu tiên để định hướng Gen Text
    print("\n[BƯỚC 1] Lựa chọn định dạng xuất Video")
    print("1. Video TĨNH (Static) - Nội dung ít (~80 chữ), đứng im hoàn hảo giữa màn hình")
    print("2. Video CUỘN (Scrolling) - Nội dung dài (~250 chữ), cuộn chậm từ dưới lên")
    choice = input("\nVui lòng chọn (1 hoặc 2) [Mặc định chạy 2 nếu để trống]: ").strip()
    if choice != "1":
        choice = "2"
    
    # Bước 2: Lựa chọn Nguồn Nội Dung
    print("\n[BƯỚC 2] Chọn nguồn sản xuất Nội Dung")
    print("1. Chạy AI Tự Động (Viết kịch bản theo Chủ đề hoặc Random)")
    print("2. Nhập thủ công (Copy & Paste đoạn text của riêng bạn vào)")
    source_choice = input("\nVui lòng chọn (1 hoặc 2) [Mặc định chạy 1 nếu để trống]: ").strip()
    
    if source_choice == "2":
        # Chế độ tự nhập
        print("\n[BƯỚC 3] NHẬP VĂN BẢN")
        print("-> Paste nội dung của bạn vào bên dưới.")
        print("-> Khuyên dùng: Mỗi câu Enter xuống dòng để layout đẹp hơn.")
        print("-> KHI ĐÃ NHẬP XONG: Gõ chữ 'END' ở một dòng mới hoàn toàn và nhấn Enter để kết thúc.")
        
        lines = []
        while True:
            try:
                line = input()
                if line.strip() == "END":
                    break
                lines.append(line)
            except EOFError:
                break
        
        body_text = "\n".join(lines)
        title = "Speak fast and clear!"
        
        if not body_text.strip():
            print("\n❌ LỖI: Cần cung cấp nội dung chữ.")
            return
            
        print("\n✅ Đã lưu văn bản tự nhập!")
        print(f"  - Đoạn text: {len(body_text)} ký tự")
    
    else:
        # Chế độ AI
        print(f"\n[BƯỚC 3] Dùng AI OpenRouter sinh kịch bản (Chế độ {choice})...")
        title, body_text = generate_motivational_script(topic, choice)
        
        # Ép cứng Title thành "Speak fast and clear!" theo yêu cầu
        title = "Speak fast and clear!"
        
        if not title or not body_text:
            print("\n❌ LỖI: Không thể tạo được kịch bản. Vui lòng kiểm tra lại API Key.")
            return
            
        print("\n✅ Đã lấy thành công bản nháp Luyện Đọc từ AI!")
        print(f"  - Đoạn text: {len(body_text)} ký tự")

    # Xác định thư mục chuẩn theo kiến trúc mới (src -> output)
    src_dir = Path(__file__).resolve().parent
    base_dir = src_dir.parent
    output_dir = base_dir / "output"
    output_dir.mkdir(exist_ok=True)
    
    # Khai báo file Tạm và Vị trí Nguồn Âm thanh
    png_path = output_dir / "temp_workflow.png"
    sample_video = base_dir.parent / "data_analytic" / "8UPhoDi2-NU.mp4"
    
    # 4. Sinh Ảnh (Stanza Word Wrap)
    print("\n[BƯỚC 4] Vẽ bố cục Text Image (Word Wrap, Phân Stanza)...")
    image_height = create_text_image(title, body_text, str(png_path))
    print(f"✅ Đã kết xuất ảnh text_overlay trung gian (Cao {image_height}px, Độ dài text: {len(body_text.split())} từ)")
    
    # Gắn ID độc nhất cho Tên Video dựa theo thời gian xuất xưởng
    out_video = output_dir / f"video_reading_{int(time.time())}.mp4"
    
    try:
        sample_path_str = str(sample_video)
        out_video_str = str(out_video)
        png_path_str = str(png_path)
        
        print(f"\n[BƯỚC 5] Gọi FFmpeg render video...")
        
        if choice == "1":
            print("\nĐang Render Video TĨNH (Nền đỏ sậm, che viền đen - Kèm âm giới thiệu 2.5s)...")
            render_ffmpeg(png_path_str, duration=15, is_static=True, output_video=out_video_str, sample_video=sample_path_str, h_image=image_height)
        else:
            print("\nĐang Render Video CUỘN (Nền đỏ sậm, che viền đen - Kèm âm giới thiệu 2.5s)...")
            word_count = len(body_text.split())
            optimal_duration = max(20, int(word_count * 0.3) + 15)
            # Bắt đầu tại H/2, di chuyển lên từ từ
            render_ffmpeg(png_path_str, duration=optimal_duration, is_static=False, output_video=out_video_str, sample_video=sample_path_str, h_image=image_height)
        
        print("\n" + "="*60)
        print(f"🎉 HOÀN TẤT THÀNH CÔNG! VIDEO ĐÃ SẴN SÀNG TẠI:\n -> {out_video_str}")
        print("="*60 + "\n")
        
        # Tự động dọn dẹp file tạm (Cleanup)
        if png_path.exists():
            png_path.unlink()
            
    except Exception as e:
        print(f"\n❌ LỖI trong quá trình Render FFmpeg: {e}")

if __name__ == "__main__":
    topic_arg = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else ""
    run_pipeline(topic_arg)
