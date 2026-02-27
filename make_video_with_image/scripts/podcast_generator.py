import os
import sys
import json
from openai import OpenAI
from dotenv import load_dotenv
from fpdf import FPDF

# Load environment variables
load_dotenv(dotenv_path=r"d:\work\Personal_project\.env")

# Ensure API Key is available
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
if not OPENROUTER_API_KEY:
    print("Error: OPENROUTER_API_KEY not found in .env file.")
    sys.exit(1)

# Initialize OpenRouter Client
client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
)

# Define directories
INPUT_DIR = "input"
OUTPUT_DIR = "output"
TOPICS_FILE = os.path.join(INPUT_DIR, "topics.txt")

def setup_directories():
    """Create input and output directories if they do not exist."""
    os.makedirs(INPUT_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

def generate_script_from_topic(topic: str) -> dict:
    prompt = f"""You are an expert scriptwriter for a professional, 20-minute ESL podcast called "English Podcast Everyday".
Your goal is to write a highly detailed, engaging, and LONG script about "{topic}".
Hosts: Alex (Male, analytical, explains grammar) and Sarah (Female, enthusiastic, provides vivid examples).

CRITICAL INSTRUCTION FOR LENGTH:
This is a full-length podcast. You MUST write a comprehensive, long-form script. 
- Expand on every explanation. 
- Include natural banter, filler words (e.g., "Right", "Exactly", "Tell me about it", "Oh, wow").
- The script should have at least 80-100 dialogue turns in total.

The structure must exactly match this flow with extreme detail:
1. Heading: "Intro & The Setup"
   - Extended welcome. Discuss why native speakers rarely say "My week was good/bad" and the importance of painting a picture with words.
2. Heading: "Conversation 1 - The Bad Week"
   - A LONG roleplay (at least 15 turns) where Sarah had a terrible week. Use advanced B2/C1 vocabulary (e.g., shattered, swamped, piling up, a drag, snowed under). Include a story about a missed deadline and traffic.
3. Heading: "The Breakdown: Analyzing the Bad Week"
   - Alex and Sarah stop and dissect the roleplay. Explain the difference between ED and ING adjectives (e.g., stressful vs stressed). Explain the phrasal verbs used in deep detail (what does "piling up" literally mean?).
4. Heading: "Conversation 2 - The Winning Week"
   - A LONG roleplay (at least 15 turns) where Alex had an amazing week. Use vocabulary like (smooth sailing, on a roll, over the moon, paid off). Include a story about a successful presentation and a relaxing weekend.
5. Heading: "The Breakdown: Analyzing the Good Week"
   - Explain the idioms. Discuss the grammar: why we use Present Perfect Continuous for recent ongoing successes.
6. Heading: "Mini-Game: Boring vs. Brilliant"
   - Alex gives 3 "Boring" textbook sentences (e.g., "I am very tired", "I am busy"). Sarah upgrades them to "Brilliant" B2/C1 phrases (e.g., "Running on fumes", "Tied up"). Explain the mental image behind each phrase.
7. Heading: "Outro"
   - Quick recap, homework challenge for listeners, and sign-off.

OUTPUT CONSTRAINT:
You MUST output ONLY a valid JSON object. No markdown formatting.

CRITICAL DIRECTING GUIDE FOR TTS (text_tts vs text_display):
For every dialogue turn, you must generate TWO text fields:
1. `text_display`: Clean, grammatically correct text. This will be printed in the PDF E-book.
2. `text_tts`: Text tailored specifically for the Kokoro TTS engine to make it sound natural and emotive. Apply these rules ONLY to `text_tts`:
   - PUNCTUATION FOR PACING: Use commas `,`, ellipses `...`, or dashes `—` frequently mid-sentence to force the AI to pause and sound like it's thinking. Use `!` for excitement and `?` for rising intonation.
   - STRESS CONTROL: Use `[word](-1)` to de-stress filler words (make them spoken lighter/faster). Examples: `[just](-1)`, `[like](-1)`, `[oh](-1)`, `[well](-1)`.
   - EMPHASIS: Use `[word](+2)` to emphasize important words (spoken louder/slower). Examples: `[really](+2)`, `[exhausting](+2)`, `[huge](+2)`.
   Example: `"text_display": "Oh wow, I completely agree! My week was totally exhausting.", "text_tts": "[Oh](-1) wow, ... I [completely](+2) agree! My week was [totally](+2) exhausting."`

Schema:
{{
  "title": "English Podcast Everyday - {topic}",
  "script": [
    {{"type": "heading", "text_display": "Heading text"}},
    {{"type": "dialogue", "speaker": "Alex", "text_display": "Clean text for reading", "text_tts": "Text formatted with Kokoro rules for speaking"}}
  ]
}}"""
    
    try:
        response = client.chat.completions.create(
            model="google/gemini-2.5-flash", # Use gemini-2.5-pro if you want even longer/better output
            messages=[
                {"role": "system", "content": "You are a helpful assistant that only outputs strictly valid JSON objects without markdown."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.7
        )
        
        text = response.choices[0].message.content.strip()
        
        # Strip potential markdown wrappers
        if text.startswith("```json"):
            text = text[7:]
        elif text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        return json.loads(text.strip())
    
    except Exception as e:
        print(f"Error parsing JSON from API response. Failed text snippet: {text if 'text' in locals() else 'No text'}")
        print(f"Exception: {e}")
        sys.exit(1)

# Custom E-book Style PDF
class PDF(FPDF):
    def header(self):
        # Optional: Add a simple stylish header across all pages
        self.set_font("helvetica", "I", 10)
        self.set_text_color(150, 150, 150)
        self.cell(0, 10, "English Podcast Everyday", new_x="LMARGIN", new_y="NEXT", align='R')
        self.ln(5)

    def chapter_title(self, title):
        self.set_font("helvetica", "B", 22)
        self.set_text_color(40, 40, 40)
        title_safe = title.encode('latin-1', 'replace').decode('latin-1')
        self.multi_cell(0, 15, title_safe, new_x="LMARGIN", new_y="NEXT", align='C')
        self.ln(10)

    def chapter_body(self, title, script):
        self.chapter_title(title)
        
        for item in script:
            if item.get("type") == "heading":
                # Beautiful Header Blocks with background
                self.ln(5)
                self.set_font("helvetica", "B", 16)
                self.set_fill_color(240, 245, 250)  # Light soothing blue-gray
                self.set_text_color(20, 50, 100)    # Deep contrast blue
                text = item.get("text_display", item.get("text", "")).encode('latin-1', 'replace').decode('latin-1')
                # A styled multi_cell block
                self.multi_cell(0, 12, f"  {text}", fill=True, new_x="LMARGIN", new_y="NEXT", align='L')
                self.ln(6)
            
            elif item.get("type") == "dialogue":
                speaker = item.get("speaker", "Unknown").encode('latin-1', 'replace').decode('latin-1')
                text = item.get("text_display", item.get("text", "")).encode('latin-1', 'replace').decode('latin-1')
                
                # E-book dialogue style: Inline markdown for bold speaker names
                self.set_font("helvetica", "", 12)
                self.set_text_color(45, 45, 45) # Soft dark grey, easy to read
                
                # We use markdown=True so we can bold the speaker name dynamically and let fpdf wrap text naturally
                formatted_text = f"**{speaker}:** {text}"
                self.multi_cell(0, 8, formatted_text, markdown=True, new_x="LMARGIN", new_y="NEXT")
                self.ln(3)

def create_pdf_from_json(json_data: dict, output_filename: str):
    pdf = PDF(orientation='P', unit='mm', format='A4')
    pdf.set_margins(left=20, top=20, right=20)
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=20)
    
    title = json_data.get("title", "Podcast Script")
    script = json_data.get("script", [])
    
    pdf.chapter_body(title, script)
    pdf.output(output_filename)

def process_topic(topic: str):
    print(f"\n[{topic}] Calling API via OpenRouter to generate LONG script...")
    json_data = generate_script_from_topic(topic)
    
    # Create safe filename based on topic
    safe_topic_name = "".join([c for c in topic if c.isalnum() or c==' ']).rstrip().replace(" ", "_")
    
    # Save JSON
    json_filename = os.path.join(OUTPUT_DIR, f"{safe_topic_name}_script.json")
    with open(json_filename, "w", encoding="utf-8") as f:
        json.dump(json_data, f, ensure_ascii=False, indent=2)
    print(f"[{topic}] JSON saved to {json_filename}")
    
    # Save PDF
    pdf_filename = os.path.join(OUTPUT_DIR, f"{safe_topic_name}_script.pdf")
    create_pdf_from_json(json_data, pdf_filename)
    print(f"[{topic}] PDF saved to {pdf_filename} (E-book Style)")

def main():
    setup_directories()
    
    with open(TOPICS_FILE, "r", encoding="utf-8") as f:
        topics = [line.strip() for line in f.readlines() if line.strip()]

    if not topics:
        print("No topics found in input/topics.txt. Please add some topics and try again.")
        sys.exit(0)

    print(f"Found {len(topics)} topics to process.")
    
    for topic in topics:
        process_topic(topic)
        
    print("\nAll topics processed successfully!")

if __name__ == "__main__":
    main()
