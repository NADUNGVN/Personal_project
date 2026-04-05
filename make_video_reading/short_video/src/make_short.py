import os
import subprocess
import json
from PIL import Image, ImageDraw, ImageFont

def get_video_duration(file_path):
    cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_format", file_path
    ]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    info = json.loads(result.stdout)
    return float(info['format']['duration'])

def create_text_image(title_text, body_text, output_png_path, video_width=1080):
    bg_color = (0, 0, 0, 0)
    font_color = (255, 255, 255, 255)

    base_font_path = "C:/Windows/Fonts/arial.ttf"
    title_font_path = "C:/Windows/Fonts/arialbd.ttf"
    
    try:
        title_font = ImageFont.truetype(title_font_path, 49)  # Kích thước Title (giảm thêm 1/4 từ 65)
        body_font = ImageFont.truetype(base_font_path, 38)    # Kích thước Body Text (giảm thêm 1/4 từ 50)
    except IOError:
        title_font = ImageFont.load_default()
        body_font = ImageFont.load_default()

    def get_text_size(font, text):
        if hasattr(font, 'getbbox'):
            bbox = font.getbbox(text)
            return bbox[2] - bbox[0], bbox[3] - bbox[1]
        else:
            return font.getsize(text)

    # Nếu text là mảng văn xuôi dài chưa xuống dòng (ít hơn 5 dòng gộp), ta tự tạo cấu trúc ngắt đoạn (Stanza)
    # Tự động thay thế dấu "." và "?" bằng khoảng trống ngắt dòng lớn
    lines_in_text = body_text.splitlines()
    if len(lines_in_text) <= 5 and len(body_text) > 150: 
        body_text = body_text.replace('. ', '.\n\n')
        body_text = body_text.replace('? ', '?\n\n')

    wrapped_lines = []
    max_text_width = 700  # Thu hẹp lại để chữ ngắn hơn và dàn đều trên nhiều dòng hơn (như Output 1)
    
    # Word wrap
    for raw_line in body_text.splitlines():
        if not raw_line.strip():
            wrapped_lines.append("")
            continue
            
        words = raw_line.split()
        current_line = ""
        for word in words:
            test_line = current_line + " " + word if current_line else word
            w, _ = get_text_size(body_font, test_line)
            if w <= max_text_width:
                current_line = test_line
            else:
                wrapped_lines.append(current_line)
                current_line = word
        if current_line:
            wrapped_lines.append(current_line)

    title_w, title_h = get_text_size(title_font, title_text)
    
    line_spacing = 20
    paragraph_spacing = 60 # Khoảng cách giữa các khổ chữ lớn
    
    body_height = 0
    for line in wrapped_lines:
        if not line.strip():
            body_height += paragraph_spacing
            continue
        _, h = get_text_size(body_font, line)
        body_height += h if h > 0 else 50
        body_height += line_spacing

    # Lược bỏ padding của Image để tránh bị cắt chữ khi render FFmpeg
    padding_top_bottom = 0 
    title_margin_bottom = 150  # Khoảng cách xa thân bài để nhấn mạnh Title
    
    image_height = padding_top_bottom * 2 + title_h + title_margin_bottom + body_height

    img = Image.new('RGBA', (video_width, int(image_height)), bg_color)
    draw = ImageDraw.Draw(img)
    
    current_y = padding_top_bottom
    
    # Vẽ Title
    draw.text(((video_width - title_w) / 2, current_y), title_text, font=title_font, fill=font_color)
    current_y += title_h + title_margin_bottom
    
    # Vẽ Body
    for line in wrapped_lines:
        if not line.strip():
            current_y += paragraph_spacing
            continue
            
        w, h = get_text_size(body_font, line)
        draw.text(((video_width - w) / 2, current_y), line, font=body_font, fill=font_color)
        current_y += (h if h > 0 else 50) + line_spacing

    img.save(output_png_path)
    return image_height

def render_ffmpeg(overlay_png, duration, is_static, output_video, sample_video, h_image):
    video_width, video_height = 1080, 1920
    
    if is_static:
        # Giữa màn hình hoàn hảo vì Image không còn padding rác
        expr_y = f"(H-{h_image})/2"
    else:
        # Bắt đầu ngay giữa màn (H/2), kết thúc khi dòng cuối cùng nằm giữa màn (H/2 - h_image)
        expr_y = f"H/2-t*({h_image}/{duration})"

    cmd = [
        "ffmpeg", "-y",
        "-hide_banner", "-loglevel", "error", "-nostats",
        "-i", sample_video, 
        "-f", "lavfi", "-i", f"color=c=#0B0404:s={video_width}x{video_height}:r=30", 
        "-i", overlay_png, 
        "-filter_complex", 
        f"[1:v][2:v]overlay=x=(W-w)/2:y='{expr_y}'[v_over]; "
        f"[v_over]drawbox=x=0:y=0:w={video_width}:h=100:color=black:t=fill, "
        f"drawbox=x=0:y={video_height-100}:w={video_width}:h=100:color=black:t=fill[v_out]; "
        f"[0:a]volume='if(lt(t,2.5),1,0)':eval=frame[a_out]",
        "-map", "[v_out]",       
        "-map", "[a_out]",       
        "-c:v", "h264_nvenc", "-preset", "p4", "-cq", "18", "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-t", str(duration),
        output_video
    ]
    
    print(f"\n[FFmpeg] Rendering {output_video} (Duration: {duration}s, Static: {is_static})...")
    subprocess.run(cmd, check=True)
    print(f"-> Đã render xong {output_video}")

# File now serves only as an imported module for run_workflow.py
