import os
import json
import random
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI

def load_env():
    # Load .env từ thư mục project hiện tại (hoặc thư mục cha)
    current_dir = Path(__file__).parent.resolve()
    env_paths = [
        current_dir / ".env",
        current_dir.parent / ".env",
        current_dir.parent.parent / ".env",
        current_dir.parent.parent.parent / ".env",     # D:\work\Personal_project
        current_dir.parent.parent.parent.parent / ".env"
    ]
    for env_path in env_paths:
        if env_path.exists():
            load_dotenv(dotenv_path=env_path)
            break

def generate_motivational_script(topic, mode="2"):
    load_env()
    
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        print("LỖI: Missing OPENROUTER_API_KEY. Add it to your .env file.")
        return None, None

    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=api_key,
    )

    # Nếu người dùng bỏ trống Topic, AI tự động "tung xúc xắc" chọn một chủ đề học tiếng Anh thực tế
    if not topic or not topic.strip():
        themes = [
            "A relaxing Sunday morning", 
            "The challenge of learning a new language", 
            "Why I love taking walks in the park", 
            "Making mistakes and learning from them", 
            "My favorite childhood memory",
            "How to stay healthy and active",
            "A funny misunderstanding",
            "The importance of good friends",
            "A trip to the grocery store",
            "Navigating a rainy day",
            "My morning coffee routine"
        ]
        topic = random.choice(themes)
        print(f"[Auto] Random mode activated! Selected theme: '{topic}'")

    # Dynamic Length Constraint based on Layout Mode
    if mode == "1": # Static
        length_constraint = "short and concise, around 60-80 words. It MUST easily fit on a single screen"
    else: # Scrolling
        length_constraint = "an expanded and rich storytelling passage, around 200-250 words"

    # Prompt mới: Thiết lập word count linh hoạt theo chế độ di chuyển
    system_instruction = f"""You are an expert English teacher creating engaging reading practice content for A2-B1 learners.

REQUIREMENTS:
1. ONLY return valid JSON without markdown.
2. The JSON schema must contain exactly this key:
- "body_text": Produce a continuous English passage ({length_constraint}). It MUST be relatable, easy-to-read, using general and common everyday vocabulary (A2-B1 level). Avoid overly complex idioms or advanced grammar. It should be storytelling or reflection, ideally continuous without bullet points or emojis. Perfect for an English learner to practice reading aloud smoothly.
"""
    
    prompt = f"Write an engaging English reading practice story about: {topic}"
    
    print(f"Đang gọi OpenRouter (google/gemini-2.5-flash) tạo đoạn đọc hiểu chủ đề: '{topic}'...")
    try:
        response = client.chat.completions.create(
            model="google/gemini-2.5-flash",
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.7,
        )
        
        raw_text = response.choices[0].message.content or "{}"
        
        if raw_text.strip().startswith("```json"):
            raw_text = raw_text.strip()[7:-3].strip()
        elif raw_text.strip().startswith("```"):
            raw_text = raw_text.strip()[3:-3].strip()
            
        data = json.loads(raw_text)
        return "Speak fast and clear!", data.get("body_text", "")

    except Exception as e:
        print(f"Lỗi khi gọi API qua OpenRouter OpenAI Client: {e}")
        return None, None
