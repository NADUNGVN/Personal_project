import json
import os
import sys
import time
from typing import Dict, List

from dotenv import load_dotenv
from fpdf import FPDF
from openai import OpenAI

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INPUT_DIR = os.path.join(BASE_DIR, "input")
STORY_DETAILS_FILE = os.path.join(INPUT_DIR, "story_details.json")
TOPICS_FILE = os.path.join(INPUT_DIR, "topics.txt")
CURRENT_OUT_DIR_FILE = os.path.join(INPUT_DIR, "current_output_dir.txt")

# Support both <project>/.env and <workspace>/.env
for env_path in (
    os.path.join(BASE_DIR, ".env"),
    os.path.join(os.path.dirname(BASE_DIR), ".env"),
):
    if os.path.exists(env_path):
        load_dotenv(dotenv_path=env_path)
        break

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
if not OPENROUTER_API_KEY:
    print("Error: OPENROUTER_API_KEY not found in .env file.")
    sys.exit(1)

client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_API_KEY)

if os.path.exists(CURRENT_OUT_DIR_FILE):
    with open(CURRENT_OUT_DIR_FILE, "r", encoding="utf-8") as f:
        OUTPUT_DIR = f.read().strip()
else:
    OUTPUT_DIR = os.path.join(BASE_DIR, "output")

os.makedirs(INPUT_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

LLM_MODEL = "google/gemini-2.5-flash"
MAX_RETRIES = 2
ALLOWED_SPEAKERS = ["Davis"]

SYSTEM_PROMPT = """You are an expert storyteller and scriptwriter.
Your name is "Davis". You are a male storyteller who narrates fascinating folklore and stories from all over the world.
Your voice is expressive, warm, slightly dramatic, and deeply engaging. You know how to captivate an audience using pacing, pauses, and emotional delivery.

CRITICAL OUTPUT RULES:
1. Output ONLY valid JSON. No markdown, no extra text.
2. ESCAPE all quotes inside strings.
3. For EVERY item, generate ALL required fields.
4. For dialogue items (type="dialogue"), generate:
   - Use `text_display` for the grammatically correct text shown on screen/PDF.
   - Use `text_tts` for the text sent to the voice synthesizer.
     * Add "..." for natural pauses.
     * Use ALL CAPS for emphasized words.
     * IMPORTANT: Phonetically spell out foreign/non-English names using English syllables (e.g. "Giong" -> "Yong", "Nguyen" -> "Nwin").
   - `speaker`: "Davis"

CRITICAL HEADING RULES:
Every heading item (type="heading") MUST have:
- `title`: SHORT chapter title (max 8 words)
- `text_display`: Full spoken transition text
- `text_tts`: TTS-directed variant
- `speaker`: "Davis"

EXCEPTION - MUTE headings (Intro & Outro):
- Intro heading: speaker="", text_display=same as title, text_tts=""
- Outro heading: speaker="", text_display=same as title, text_tts=""

CRITICAL PRONUNCIATION RULE FOR `text_tts`:
VibeVoice lacks explicit phoneme support. You MUST use conversational English Phonetic Respelling for non-English names and terms in the `text_tts` field so the American AI voice pronounces them correctly.
For example, if the script has "Việt Nam", `text_display` should be "Việt Nam", but `text_tts` should be "Vee-et Nam". For "Gióng", `text_tts` should be "Zong" or "Jong". For "Hùng Vương", `text_tts` should be "Hung Voo-ong".

JSON OUTPUT GUIDELINES:
1. Every segment must be returned as a JSON object containing an array of script items.

You are a helpful assistant that only outputs strictly valid JSON objects without markdown."""

SEGMENTS = [
    {
        "id": 1,
        "name": "Intro",
        "prompt_template": """Write Segment 1: INTRO for the folklore story "{title}" originating from "{origin}".

RULES:
- First item MUST be a MUTE heading (speaker="", text_tts="", text_display="{title}").
- Second item MUST be a dialogue by Davis.
- Davis introduces himself ("Hi, I'm Davis...").
- Davis warmly welcomes the audience to a new storytelling session.
- Davis introduces the origin ("{origin}") and the title of today's story ("{title}").
- Create a sense of wonder and warmth.
- Use simple, descriptive, and engaging language.
- Speak directly to the listener (e.g., "Imagine, if you will...", "Now, my friends...").
- Keep sentences relatively short and well-paced for text-to-speech.
- Keep this intro relatively short and engaging (3-4 dialogue turns max).

OUTPUT FORMAT:
{{
  "segment_id": 1,
  "segment_name": "Intro",
  "script": [
    {{"type": "heading", "speaker": "", "title": "Intro", "text_display": "Intro", "text_tts": ""}},
    {{"type": "dialogue", "speaker": "Davis", "text_display": "Hello everyone, my name is Davis and welcome...", "text_tts": "hello everyone... my name is Davis, and welcome..."}}
  ]
}}""",
    },
    {
        "id": 2,
        "name": "Storytelling",
        "prompt_template": """Write Segment 2: STORYTELLING for "{title}".

STORY SYNOPSIS (DO NOT CHANGE THE CORE PLOT):
---
{synopsis}
---

RULES:
- Start with a heading spoken by Davis (e.g., "The Story of...").
- Davis narrates the ENTIRE story based on the synopsis provided.
- Tell it in a highly engaging, unique, and expressive way. Do not just read the synopsis like a textbook. Make it feel alive, like a mystical campfire tale!
- Break the story down into 10-15 dialogue chunks/turns so the pacing is excellent.
- Add dramatic pauses (...) and emphasis (CAPS) in the text_tts.
- The ONLY speaker is "Davis".

OUTPUT FORMAT:
{{
  "segment_id": 2,
  "segment_name": "Storytelling",
  "script": [
    {{"type": "heading", "speaker": "Davis", "title": "The Story of Saint Giong", "text_display": "Now, let me tell you the story...", "text_tts": "Now, let me tell you the story..."}},
    {{"type": "dialogue", "speaker": "Davis", "text_display": "Long ago, when Emperor Hung Vuong...", "text_tts": "Long ago... when Emperor Hung Vuong..."}}
  ]
}}""",
    },
    {
        "id": 3,
        "name": "Outro",
        "prompt_template": """Write Segment 3: OUTRO for "{title}".

PREVIOUS SCRIPT (FOR CONTEXT):
---
{context}
---

RULES:
- Start with a MUTE heading (speaker="", text_tts="", title="Outro").
- Davis gives a few closing thoughts on the moral or the feeling of the story (very brief).
- He gives sincere, emotional thanks to the audience.
- He calls to action: "If you enjoyed this tale, please subscribe and join me next time..."
- Keep it to 3-5 dialogue turns max.
- The ONLY speaker is "Davis".

OUTPUT FORMAT:
{{
  "segment_id": 3,
  "segment_name": "Outro",
  "script": [
    {{"type": "heading", "speaker": "", "title": "Outro", "text_display": "Outro", "text_tts": ""}},
    {{"type": "dialogue", "speaker": "Davis", "text_display": "What a fascinating tale...", "text_tts": "What a fascinating tale..."}}
  ]
}}""",
    },
]


def build_accumulated_text(completed_segments: List[Dict]) -> str:
    lines: List[str] = []
    for seg in completed_segments:
        for item in seg.get("script", []):
            item_type = item.get("type", "dialogue")
            speaker = item.get("speaker", "")
            text = item.get("text_display", "")
            if item_type == "heading":
                title = item.get("title", text)
                lines.append(f"\n[Heading: {title}]")
            elif speaker:
                lines.append(f"{speaker}: {text}")
            else:
                lines.append(text)
    return "\n".join(lines)


def validate_segment(segment_data: Dict, segment_config: Dict) -> List[str]:
    errors: List[str] = []
    segment_id = segment_config["id"]

    if not isinstance(segment_data, dict):
        return ["Output is not a JSON object"]

    script = segment_data.get("script", [])
    if not script:
        return ["Missing or empty 'script' array"]

    first_item = script[0]
    if first_item.get("type") != "heading":
        errors.append("First item must be heading")
    if "title" not in first_item:
        errors.append("Heading missing 'title'")

    if segment_id in (1, 3):
        if first_item.get("speaker", "x") != "":
            errors.append("Intro/Outro heading speaker must be empty")
        if first_item.get("text_tts", "x") != "":
            errors.append("Intro/Outro heading text_tts must be empty")
        if len(script) > 1 and script[1].get("speaker") != "Davis":
            errors.append("First dialogue after mute heading must be Davis")

    for idx, item in enumerate(script):
        for field in ("type", "speaker", "text_display", "text_tts"):
            if field not in item:
                errors.append(f"Item {idx}: missing field '{field}'")
        if item.get("type") == "heading" and "title" not in item:
            errors.append(f"Item {idx}: heading missing 'title'")
        speaker = item.get("speaker", "")
        if speaker and speaker not in ALLOWED_SPEAKERS:
            errors.append(f"Item {idx}: unknown speaker '{speaker}'. Only 'Davis' is allowed.")

    return errors


def generate_segment(segment_config: Dict, story_details: Dict, accumulated_text: str) -> Dict:
    title = story_details.get("title", "Unknown Story")
    origin = story_details.get("origin", "Unknown World")
    synopsis = story_details.get("synopsis", "No synopsis provided.")
    
    prompt = segment_config["prompt_template"].format(
        title=title,
        origin=origin,
        synopsis=synopsis,
        context=accumulated_text if accumulated_text else "(No previous context)",
    )

    for attempt in range(1, MAX_RETRIES + 2):
        try:
            print(f"  [LLM] Segment {segment_config['id']} - {segment_config['name']} (attempt {attempt})")
            response = client.chat.completions.create(
                model=LLM_MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.7,
            )

            text = response.choices[0].message.content.strip()
            if text.startswith("```json"):
                text = text[7:]
            elif text.startswith("```"):
                text = text[3:]
            if text.endswith("```"):
                text = text[:-3]

            segment_data = json.loads(text.strip())
            errors = validate_segment(segment_data, segment_config)
            if errors and attempt <= MAX_RETRIES:
                print(f"  [Warn] Validation failed: {errors}")
                prompt += (
                    "\n\nPREVIOUS ATTEMPT HAD ERRORS: "
                    f"{errors}\nPlease fix all issues and output valid JSON only. Remember, ONLY Davis is the speaker."
                )
                continue
            if errors:
                print(f"  [Warn] Validation warnings kept after retries: {errors}")
            return segment_data

        except json.JSONDecodeError as exc:
            print(f"  [Error] JSON parse failed: {exc}")
            if attempt > MAX_RETRIES:
                raise
        except Exception as exc:
            print(f"  [Error] API failed: {exc}")
            if attempt > MAX_RETRIES:
                raise
            time.sleep(5)

    raise RuntimeError("Failed to generate segment")


def merge_segments(title: str, segments: List[Dict]) -> Dict:
    merged_script: List[Dict] = []
    for seg in segments:
        merged_script.extend(seg.get("script", []))
    return {"title": f"The Folklore Collection - {title}", "script": merged_script}


def generate_full_script() -> Dict:
    if not os.path.exists(STORY_DETAILS_FILE):
        print("No story_details.json found. Run make_story_video.py first.")
        sys.exit(1)
        
    with open(STORY_DETAILS_FILE, "r", encoding="utf-8") as f:
        story_details = json.load(f)
        
    title = story_details.get("title", "Unknown Story")
    completed_segments: List[Dict] = []
    total = len(SEGMENTS)

    print("\n" + "=" * 60)
    print("  MULTI-STEP SCRIPT GENERATION (DAVIS STORYTELLING)")
    print(f"  Title: {title}")
    print(f"  Segments: {total}")
    print("=" * 60)

    for segment_config in SEGMENTS:
        print(f"\n  [{segment_config['id']}/{total}] {segment_config['name']}")
        accumulated_text = build_accumulated_text(completed_segments)
        start = time.time()
        segment_data = generate_segment(segment_config, story_details, accumulated_text)
        elapsed = time.time() - start

        turns = len([item for item in segment_data.get("script", []) if item.get("type") == "dialogue"])
        print(f"  [OK] {segment_config['name']} - {turns} turns ({elapsed:.1f}s)")
        completed_segments.append(segment_data)

    merged = merge_segments(title, completed_segments)
    total_turns = len([item for item in merged["script"] if item.get("type") == "dialogue"])
    total_headings = len([item for item in merged["script"] if item.get("type") == "heading"])
    print(f"\n  [Merge] Final script: {total_headings} headings + {total_turns} turns")
    return merged


def clean_text_for_pdf(text: str) -> str:
    replacements = {
        "“": '"', "”": '"', "‘": "'", "’": "'", "…": "...", "—": "-", "–": "-"
    }
    for k, v in replacements.items():
        text = text.replace(k, v)
    return text.encode("latin-1", "replace").decode("latin-1")


class PDF(FPDF):
    def header(self):
        self.set_font("helvetica", "I", 10)
        self.set_text_color(150, 150, 150)
        self.cell(0, 10, "The Folklore Collection (Voice: Davis)", new_x="LMARGIN", new_y="NEXT", align="R")
        self.ln(5)

    def chapter_title(self, title: str):
        self.set_font("helvetica", "B", 22)
        self.set_text_color(40, 40, 40)
        title_safe = clean_text_for_pdf(title)
        self.multi_cell(0, 15, title_safe, new_x="LMARGIN", new_y="NEXT", align="C")
        self.ln(10)

    def chapter_body(self, title: str, script: List[Dict]):
        self.chapter_title(title)

        accumulated_dialogue = []

        def flush_dialogue():
            if accumulated_dialogue:
                text = " ".join(accumulated_dialogue)
                text = clean_text_for_pdf(text)
                self.set_font("helvetica", "", 13)
                self.set_text_color(30, 30, 30)
                # FPDF multi_cell handles line wrapping automatically. 
                # Justify alignment is used without leading spaces to ensure a perfect block
                self.multi_cell(
                    0, 
                    7, 
                    text, 
                    align="J"
                )
                self.ln(5)
                accumulated_dialogue.clear()

        for item in script:
            item_type = item.get("type")
            if item_type == "heading":
                flush_dialogue()
                
                self.ln(5)
                self.set_font("helvetica", "B", 16)
                self.set_fill_color(240, 245, 250)
                self.set_text_color(20, 50, 100)

                heading_text = item.get("title", item.get("text_display", ""))
                safe_heading = clean_text_for_pdf(heading_text)
                self.multi_cell(0, 12, f"  {safe_heading}", fill=True, new_x="LMARGIN", new_y="NEXT", align="L")
                self.ln(3)

                # We DO NOT append transition text to the PDF output as requested.
                
            elif item_type == "dialogue":
                # Ensure we only use the clean text intended for display
                text = item.get("text_display", "")
                accumulated_dialogue.append(text.strip())

        flush_dialogue()


def create_pdf_from_json(json_data: Dict, output_filename: str):
    pdf = PDF(orientation="P", unit="mm", format="A4")
    pdf.set_margins(left=20, top=20, right=20)
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=20)

    title = json_data.get("title", "Story Script")
    script = json_data.get("script", [])
    pdf.chapter_body(title, script)
    pdf.output(output_filename)


def main():
    if not os.path.exists(STORY_DETAILS_FILE):
        print("No story_details.json found. Run make_story_video.py first.")
        sys.exit(1)
        
    with open(STORY_DETAILS_FILE, "r", encoding="utf-8") as f:
        story_details = json.load(f)

    title = story_details.get("title", "Unknown Story")
    json_data = generate_full_script()

    safe_topic_name = "".join([c for c in title if c.isalnum() or c == " "]).rstrip().replace(" ", "_")
    json_filename = os.path.join(OUTPUT_DIR, f"{safe_topic_name}_script.json")
    with open(json_filename, "w", encoding="utf-8") as f:
        json.dump(json_data, f, ensure_ascii=False, indent=2)
    print(f"\n  [Save] JSON: {json_filename}")

    clean_pdf_name = "".join([c for c in title if c.isalnum() or c == " "]).strip() or safe_topic_name
    pdf_filename = os.path.join(OUTPUT_DIR, f"{clean_pdf_name}.pdf")
    create_pdf_from_json(json_data, pdf_filename)
    print(f"  [Save] PDF: {pdf_filename}")

    print("\n" + "=" * 60)
    print("  Script generation complete")
    print("=" * 60)


if __name__ == "__main__":
    main()
