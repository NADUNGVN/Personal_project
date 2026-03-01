import os
import sys
import json
import fitz  # PyMuPDF
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

# --- CONFIGURATION ---
INPUT_DIR = "input"
TOPICS_FILE = os.path.join(INPUT_DIR, "topics.txt")
PDF_DIR = os.path.join(INPUT_DIR, "pdf_content")
CURRENT_PDF_FILE = os.path.join(INPUT_DIR, "current_pdf.txt")

# Read dynamic output directory if it exists, otherwise default to "output"
CURRENT_OUT_DIR_FILE = os.path.join(INPUT_DIR, "current_output_dir.txt")
if os.path.exists(CURRENT_OUT_DIR_FILE):
    with open(CURRENT_OUT_DIR_FILE, "r", encoding="utf-8") as f:
        OUTPUT_DIR = f.read().strip()
else:
    OUTPUT_DIR = "output"
    
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(INPUT_DIR, exist_ok=True)
os.makedirs(PDF_DIR, exist_ok=True)


def generate_script_from_pdf(topic_name: str, pdf_text: str) -> dict:
    prompt = f"""You are an expert scriptwriter for a professional, 20-minute ESL podcast called "English Podcast Everyday".
Your goal is to write a highly detailed, engaging, and LONG script about "{topic_name}", based strictly on the provided source material.

SOURCE MATERIAL (Raw Transcript/Notes):
---
{pdf_text[:15000]} # Limiting just in case of massive PDFs
---

Hosts: Alex (Male, analytical, explains grammar) and Sarah (Female, enthusiastic, provides vivid examples).
CRITICAL: You MUST replace any existing hosts in the source material (like Max and Mia) with Alex and Sarah.

VOICE CASTING FOR ROLEPLAYS:
When you create a dialogue/roleplay with new characters, you MUST use ONLY these names to ensure our TTS engine can assigned them voices properly:
- "Michael" (Male Adult)
- "Nicole" (Female Adult)
- "Adam" (Male Adult)
- "Sky" (Female Adult)
If there are two characters in a roleplay, you could name them "Michael" and "Nicole", for example. DO NOT up make random names like "Dominic" or "Lila".

CRITICAL INSTRUCTION FOR LENGTH:
This is a full-length podcast. You MUST write a comprehensive, long-form script. 
- Expand on every explanation. 
- Include natural banter, filler words (e.g., "Right", "Exactly", "Tell me about it", "Oh, wow").
- The script should have at least 80-100 dialogue turns in total.

The structure must strictly follow the "Max & Mia Golden Podcast Formula" with extreme detail, adapting deeply to the theme "{topic_name}":

1. [Intro & The Setup]
   - Create a catchy heading name. Extended welcome. Natural banter between the hosts leading into the theme "{topic_name}". Spark the listener's interest.
   
2. [Act 1: Sub-topic 1 - Vocabulary & Breakdown]
   - Invent a creative heading name. The hosts introduce 3-4 advanced B2/C1 phrases, idioms, or a specific grammar point related to a common scenario of "{topic_name}". Explain the literal meanings or mental images behind them.
3. [AUDIO #1: Character A & Character B]
   - Invent a creative heading name. A LONG, hyper-realistic roleplay (at least 15 dialogue turns) between two new characters naturally applying the vocabulary discussed.
4. [MAX & MIA — Post-Audio Commentary 1]
   - Invent a creative heading name. Alex and Sarah dissect the roleplay, pointing out EXACTLY why the B2/C1 phrases worked so well in context.

5. [Act 2: Sub-topic 2 - Vocabulary & Breakdown]
   - Invent a creative heading name. Pivot to a contrasting, more complex, or completely different scenario related to "{topic_name}". Teach a new set of advanced phrases.
6. [AUDIO #2: Character C & Character D]
   - Invent a creative heading name. Another LONG, realistic roleplay (at least 15 dialogue turns) applying the new set of vocabulary.
7. [MAX & MIA — Post-Audio Commentary 2]
   - Invent a creative heading name. Dissect the second roleplay. Emphasize the emotional tone and natural speech patterns.

8. [Act 3: The Final Polish / Practice Challenge]
   - Invent a creative heading name. Design a highly interactive, fun segment. This could be a 3rd audio roleplay, a "Boring vs. Brilliant" phrase upgrade game, or a "fix the mistake" challenge, perfectly tailored to "{topic_name}".
   
9. [Outro & Call to Action]
   - Invent a creative heading name. A lightning-fast recap of the key vocabulary. Give the listeners a homework challenge to answer in the comments. Warm sign-off.

OUTPUT CONSTRAINT:
You MUST output ONLY a valid JSON object. No markdown formatting.
CRITICAL JSON ESCAPING: If any character speaks a quote, you MUST escape it (e.g., "Then he said \\"hello\\" to me"). Do NOT use unescaped double quotes inside the string fields. Failure to do so will break the JSON parser.

CRITICAL DIRECTING GUIDE FOR TTS (text_tts vs text_display):
For EVERY dialogue and EVERY heading, you must generate BOTH fields:
1. `text_display`: Clean, grammatically correct text. This will be printed in the PDF E-book and on the YouTube screen.
2. `text_tts`: Text tailored specifically for the Kokoro TTS engine to make it sound natural and emotive. Apply these rules ONLY to `text_tts`:
   - PUNCTUATION FOR PACING: Use commas `,`, ellipses `...`, or dashes `—` frequently mid-sentence to force the AI to pause and sound like it's thinking. Use `!` for excitement and `?` for rising intonation.
   - STRESS CONTROL: Use `[word](-1)` to de-stress filler words (make them spoken lighter/faster). Examples: `[just](-1)`, `[like](-1)`, `[oh](-1)`.
   - EMPHASIS: Use `[word](+2)` to emphasize important words (spoken louder/slower). Examples: `[really](+2)`, `[exhausting](+2)`.

CRITICAL: SPOKEN HEADINGS
Headings in this podcast are NOT just silent text. They MUST be spoken by one of the hosts (usually Alex) to act as a smooth transition into the next segment.
HOWEVER, there is ONE STRICT EXCEPTION:
- The VERY FIRST heading (1. Intro & The Setup) MUST NOT be spoken. Both `speaker` and `text_tts` MUST be an empty string `""` for the Intro heading. The opening speech must happen in the `dialogue` block immediately following it.
- Furthermore, the very first person to speak in the `dialogue` block right after the Intro heading MUST ALWAYS be Alex. He is the one who opens the show.
For EVERY OTHER `type: "heading"` (Act 1, Act 2, etc.), you MUST invent:
- A catchy, creative title for `text_display` (e.g. "Mastering the Chaos: 3 Must-Know Phrases").
- A `speaker` to read the heading (e.g., "Alex").
- A natural introductory transition phrase for `text_tts` (e.g., "[Alright](-1)... moving on to our first segment! Let's dive straight into how you can [master](+2) the chaos.").

Schema:
{{
  "title": "English Podcast Everyday - {topic_name}",
  "script": [
    {{"type": "heading", "speaker": "", "text_display": "Creative Title For Intro", "text_tts": ""}},
    {{"type": "dialogue", "speaker": "Alex", "text_display": "Welcome back to...", "text_tts": "[Welcome](+2) back to..."}},
    {{"type": "heading", "speaker": "Alex", "text_display": "Act 1: Title", "text_tts": "Alright, moving on to our first segment..."}}
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
        print(f"\nError parsing JSON from API response.")
        if 'text' in locals():
            print(f"--- RAW RESPONSE START ---")
            print(text[:500] + "\n...\n" + text[-500:])
            print(f"--- RAW RESPONSE END ---")
        else:
            print("No text received.")
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

def process_pdf(pdf_path: str, topic_name: str):
    print(f"\n[{topic_name}] Extracting text from PDF template...")
    doc = fitz.open(pdf_path)
    pdf_text = ""
    for page in doc:
        pdf_text += page.get_text() + "\n"

    print(f"[{topic_name}] Calling API via OpenRouter to generate script based on PDF template length: {len(pdf_text)} chars...")
    json_data = generate_script_from_pdf(topic_name, pdf_text)
    
    # Create safe filename based on topic
    safe_topic_name = "".join([c for c in topic_name if c.isalnum() or c==' ']).rstrip().replace(" ", "_")
    
    # Save JSON
    json_filename = os.path.join(OUTPUT_DIR, f"{safe_topic_name}_script.json")
    with open(json_filename, "w", encoding="utf-8") as f:
        json.dump(json_data, f, ensure_ascii=False, indent=2)
    print(f"[{topic_name}] JSON saved to {json_filename}")
    
    # Save PDF (E-book style)
    pdf_filename = os.path.join(OUTPUT_DIR, f"{safe_topic_name}_script.pdf")
    create_pdf_from_json(json_data, pdf_filename)
    print(f"[{topic_name}] PDF saved to {pdf_filename} (E-book Style)")

def main():
    if not os.path.exists(CURRENT_PDF_FILE):
        print("No current_pdf.txt found. Please run make_youtube_video.py first to specify a PDF.")
        sys.exit(1)

    if not os.path.exists(TOPICS_FILE):
        print("No topics.txt found. Please run make_youtube_video.py first to specify a topic.")
        sys.exit(1)

    with open(CURRENT_PDF_FILE, "r", encoding="utf-8") as f:
        pdf_path = f.read().strip()

    with open(TOPICS_FILE, "r", encoding="utf-8") as f:
        topic_name = f.read().strip()

    if not pdf_path or not os.path.exists(pdf_path):
        print(f"[{pdf_path}] not found or invalid.")
        sys.exit(1)

    if not topic_name:
        print("Topic is empty.")
        sys.exit(1)

    process_pdf(pdf_path, topic_name)
    print("\nPDF and Topic processed successfully!")

if __name__ == "__main__":
    main()
