import re

def process_dynamic_captions(text, max_words_per_screen=9, max_chars_per_line=30):
    """
    Thuật toán chia nhỏ văn xuôi thành các khối Caption chuẩn Tiktok/Reels/Shorts
    dựa trên nghiên cứu hình ảnh mẫu (1 khối chứa tối đa 2 dòng, chữ to, dễ nhìn).
    """
    
    # 1. Tách thô theo các dấu câu tự nhiên (Ngắt hơi)
    # Kỹ thuật bóc tách bằng Regex giữ nguyên các dấu câu đi kèm.
    raw_phrases = re.split(r'(?<=[.,?!;])\s+', text.strip())
    
    screens = []
    
    for phrase in raw_phrases:
        if not phrase: continue
            
        words = phrase.split()
        
        # 2. Nếu khối chữ quá dài (lớn hơn số từ tối đa cho 1 màn hình), cắt bớt
        while len(words) > 0:
            chunk = words[:max_words_per_screen]
            words = words[max_words_per_screen:]
            
            # Khối `chunk` đang chứa mảng từ (ví dụ: 8 từ)
            # 3. Phân bổ xuống dòng bên trong 1 khối (Chia làm tối đa 2 dòng nếu dài quá)
            
            line1 = []
            line2 = []
            current_len = 0
            
            for w in chunk:
                # Nếu độ dài dòng 1 đã vượt quá max character của 1 dòng -> Đẩy chàn xuống dòng 2
                if current_len + len(w) > max_chars_per_line and len(line1) > 0:
                    line2.append(w)
                else:
                    line1.append(w)
                    current_len += len(w) + 1 # +1 cho dấu cách
            
            # Ráp lại khối hoàn chỉnh
            if line2:
                screens.append(" ".join(line1) + "\n" + " ".join(line2))
            else:
                screens.append(" ".join(line1))

    return screens

if __name__ == "__main__":
    # Chuỗi text giả định bạn lấy được từ AI hoặc Whisper
    sample_text = "If I tell you that you can start speaking English confidently by practicing only 10 minutes a day, it may sound too simple to be true. Maybe you are thinking right now that learning English takes years of hard work."
    
    print("=" * 50)
    print("VĂN BẢN GỐC:")
    print(sample_text)
    print("=" * 50)
    
    screens = process_dynamic_captions(sample_text)
    
    print("\n[ KẾT QUẢ CẮT CHUNK CAPTION LÊN MÀN HÌNH ]\n")
    for i, screen in enumerate(screens, 1):
        print(f"--- Màn hình {i} ---")
        print(screen)
        print()
