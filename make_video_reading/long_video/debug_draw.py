from PIL import Image, ImageDraw, ImageFont

def test_draw():
    # Kích thước khung
    SUB_W = 1600
    SUB_H = 450
    TEXT_INACTIVE_COLOR = (50, 50, 50) 
    HIGHLIGHT_BG_COLOR = (139, 0, 0)
    TEXT_ACTIVE_COLOR = (255, 255, 255)
    
    # 1. Vẽ Sub Canvas
    img_inactive = Image.new("RGBA", (SUB_W, SUB_H), (0,0,0,0))
    d_inactive = ImageDraw.Draw(img_inactive)
    
    try: font = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", 95)
    except: font = ImageFont.load_default()
    
    d_inactive.text((90, 94), "Many", font=font, fill=TEXT_INACTIVE_COLOR)
    d_inactive.text((359, 94), "English", font=font, fill=TEXT_INACTIVE_COLOR)
    
    sub_canvas = img_inactive.copy()
    d_sub = ImageDraw.Draw(sub_canvas)
    
    # Vẽ highlight cho chữ "Many"
    w1_x = 90
    w1_y = 94
    w1_text = "Many"
    bb = d_sub.textbbox((0,0), w1_text, font=font)
    ww = bb[2] - bb[0]
    base_h = bb[3] - bb[1]
    
    pad_x = 25; pad_y = 15
    box_rect = [w1_x - pad_x, w1_y - pad_y, w1_x + ww + pad_x, w1_y + base_h + pad_y + 10]
    d_sub.rounded_rectangle(box_rect, radius=25, fill=HIGHLIGHT_BG_COLOR)
    d_sub.text((w1_x, w1_y), w1_text, font=font, fill=TEXT_ACTIVE_COLOR)
    
    # 2. Paste lên Khung Trắng
    frame = Image.new("RGB", (1920, 1080), (255, 255, 255))
    frame.paste(sub_canvas, (160, 300), mask=sub_canvas)
    
    frame.save(r"d:\work\Personal_project\make_video_reading\long_video\output\debug_frame.png")

if __name__ == '__main__':
    test_draw()
