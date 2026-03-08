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
ALLOWED_SPEAKERS = ["Alex", "Sarah", "Michael", "Nicole", "Adam", "Sky", "Davis", "Emma"]

SYSTEM_PROMPT = """You are an expert scriptwriter for a professional ESL podcast called "English Podcast Everyday".
You write highly engaging, natural-sounding scripts for intermediate-to-advanced English learners.

Hosts: Alex (Male, analytical, explains grammar and vocabulary) and Sarah (Female, enthusiastic, provides vivid examples and encouragement).

VOICE CASTING FOR ROLEPLAYS:
When creating roleplay characters, you MUST ONLY use these names:
- "Michael" (Male Adult)
- "Nicole" (Female Adult)
- "Adam" (Male Adult)
- "Sky" (Female Adult)
DO NOT invent other names.

CRITICAL OUTPUT RULES:
1. Output ONLY valid JSON. No markdown, no extra text.
2. ESCAPE all quotes inside strings.
3. For EVERY item, generate ALL required fields.
4. For dialogue items, generate:
   - `text_display`: Clean, grammatically correct text for on-screen display and PDF.
   - `text_tts`: Text optimized for expressive speech:
     * Use punctuation to control pacing (, ... -)
     * Use occasional CAPS for emphasis on key words
     * Optional markup like [word](+2) / [word](-1) is allowed

CRITICAL HEADING RULES:
Every heading item (type="heading") MUST have:
- `title`: SHORT chapter title (max 8 words)
- `text_display`: Full spoken transition text
- `text_tts`: TTS-directed variant
- `speaker`: Usually Alex or Sarah

EXCEPTION - MUTE headings (Intro & Outro):
- Intro heading: speaker="", text_display=same as title, text_tts=""
- Outro heading: speaker="", text_display=same as title, text_tts=""

You are a helpful assistant that only outputs strictly valid JSON objects without markdown."""

SEGMENTS = [
    {
        "id": 1,
        "name": "Intro",
        "prompt_template": """Write Segment 1: INTRO for topic \"{topic}\".

RULES:
- First item MUST be a MUTE heading (speaker="", text_tts="").
- Second item MUST be a dialogue by Alex.
- Warm short opening between Alex and Sarah (6-8 turns).
- Tease today's topic \"{topic}\".

OUTPUT FORMAT:
{{
  "segment_id": 1,
  "segment_name": "Intro",
  "script": [
    {{"type": "heading", "speaker": "", "title": "Welcome to English Podcast Everyday", "text_display": "Welcome to English Podcast Everyday", "text_tts": ""}},
    {{"type": "dialogue", "speaker": "Alex", "text_display": "Hello everyone, welcome back!", "text_tts": "hello everyone... welcome back!"}}
  ]
}}""",
    },
    {
        "id": 2,
        "name": "Topic Introduction",
        "prompt_template": """Write Segment 2: TOPIC INTRODUCTION for \"{topic}\".

PREVIOUS SCRIPT:
---
{context}
---

RULES:
- Start with heading spoken by Alex.
- Explain why this topic matters.
- Teach 3-4 key expressions with examples.
- 10-15 dialogue turns.

OUTPUT: valid JSON with heading + dialogues.""",
    },
    {
        "id": 3,
        "name": "Audio Conversation #1",
        "prompt_template": """Write Segment 3: AUDIO CONVERSATION #1 for \"{topic}\".

PREVIOUS SCRIPT:
---
{context}
---

RULES:
- Start with heading spoken by Sarah.
- Then long realistic roleplay (15-20 turns).
- Use character names from: Michael, Nicole, Adam, Sky.
- One speaker B1, one speaker B2+.

OUTPUT: valid JSON only.""",
    },
    {
        "id": 4,
        "name": "Analysis & Vocabulary Breakdown",
        "prompt_template": """Write Segment 4: ANALYSIS for \"{topic}\".

PREVIOUS SCRIPT:
---
{context}
---

RULES:
- Start with heading spoken by Alex.
- Analyze phrases from Conversation #1.
- Explain B1 vs B2 language differences.
- 8-12 turns.

OUTPUT: valid JSON only.""",
    },
    {
        "id": 5,
        "name": "Topic Part 2",
        "prompt_template": """Write Segment 5: TOPIC PART 2 for \"{topic}\".

PREVIOUS SCRIPT:
---
{context}
---

RULES:
- Start with heading spoken by Sarah.
- Cover a new angle not repeated from earlier segments.
- Teach 3-4 new expressions.
- Show common learner mistakes and fixes.
- 10-12 turns.

OUTPUT: valid JSON only.""",
    },
    {
        "id": 6,
        "name": "Audio Conversation #2",
        "prompt_template": """Write Segment 6: AUDIO CONVERSATION #2 for \"{topic}\".

PREVIOUS SCRIPT:
---
{context}
---

RULES:
- Start with heading spoken by Alex.
- New roleplay (15-20 turns), different pair than conversation #1.
- Reuse vocabulary from Topic Part 2.

OUTPUT: valid JSON only.""",
    },
    {
        "id": 7,
        "name": "Analysis & Level Comparison",
        "prompt_template": """Write Segment 7: ANALYSIS & LEVEL COMPARISON for \"{topic}\".

PREVIOUS SCRIPT:
---
{context}
---

RULES:
- Start with heading spoken by Sarah.
- Compare B1 and B2 speaking patterns from conversation #2.
- 8-12 turns.

OUTPUT: valid JSON only.""",
    },
    {
        "id": 8,
        "name": "Episode Recap",
        "prompt_template": """Write Segment 8: RECAP for \"{topic}\".

PREVIOUS SCRIPT:
---
{context}
---

RULES:
- Start with heading spoken by Alex.
- Fast recap of key vocab and grammar from the full episode.
- 6-8 turns.
- No sign-off in this segment.

OUTPUT: valid JSON only.""",
    },
    {
        "id": 9,
        "name": "Outro",
        "prompt_template": """Write Segment 9: OUTRO for \"{topic}\".

PREVIOUS SCRIPT:
---
{context}
---

RULES:
- First item MUST be mute heading (speaker="", text_tts="").
- Second item MUST be dialogue from Alex.
- Warm sign-off, CTA, short ending (4-6 turns).

OUTPUT: valid JSON only.""",
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

    if segment_id in (1, 9):
        if first_item.get("speaker", "x") != "":
            errors.append("Intro/Outro heading speaker must be empty")
        if first_item.get("text_tts", "x") != "":
            errors.append("Intro/Outro heading text_tts must be empty")
        if len(script) > 1 and script[1].get("speaker") != "Alex":
            errors.append("First dialogue after mute heading must be Alex")

    for idx, item in enumerate(script):
        for field in ("type", "speaker", "text_display", "text_tts"):
            if field not in item:
                errors.append(f"Item {idx}: missing field '{field}'")
        if item.get("type") == "heading" and "title" not in item:
            errors.append(f"Item {idx}: heading missing 'title'")
        speaker = item.get("speaker", "")
        if speaker and speaker not in ALLOWED_SPEAKERS:
            errors.append(f"Item {idx}: unknown speaker '{speaker}'")

    return errors


def generate_segment(segment_config: Dict, topic: str, accumulated_text: str) -> Dict:
    prompt = segment_config["prompt_template"].format(
        topic=topic,
        context=accumulated_text if accumulated_text else "(No previous context)",
    )

    for attempt in range(1, MAX_RETRIES + 2):
        try:
            print(
                f"  [LLM] Segment {segment_config['id']} - {segment_config['name']} "
                f"(attempt {attempt})"
            )
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
                    f"{errors}\nPlease fix all issues and output valid JSON only."
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


def merge_segments(topic: str, segments: List[Dict]) -> Dict:
    merged_script: List[Dict] = []
    for seg in segments:
        merged_script.extend(seg.get("script", []))
    return {"title": f"English Podcast Everyday - {topic}", "script": merged_script}


def generate_full_script(topic: str) -> Dict:
    completed_segments: List[Dict] = []
    total = len(SEGMENTS)

    print("\n" + "=" * 60)
    print("  MULTI-STEP SCRIPT GENERATION")
    print(f"  Topic: {topic}")
    print(f"  Segments: {total}")
    print("=" * 60)

    for segment_config in SEGMENTS:
        print(
            f"\n  [{segment_config['id']}/{total}] "
            f"{segment_config['name']}"
        )
        accumulated_text = build_accumulated_text(completed_segments)
        start = time.time()
        segment_data = generate_segment(segment_config, topic, accumulated_text)
        elapsed = time.time() - start

        turns = len(
            [item for item in segment_data.get("script", []) if item.get("type") == "dialogue"]
        )
        print(f"  [OK] {segment_config['name']} - {turns} turns ({elapsed:.1f}s)")
        completed_segments.append(segment_data)

    merged = merge_segments(topic, completed_segments)
    total_turns = len([item for item in merged["script"] if item.get("type") == "dialogue"])
    total_headings = len([item for item in merged["script"] if item.get("type") == "heading"])
    print(f"\n  [Merge] Final script: {total_headings} headings + {total_turns} turns")
    return merged


class PDF(FPDF):
    def header(self):
        self.set_font("helvetica", "I", 10)
        self.set_text_color(150, 150, 150)
        self.cell(0, 10, "English Podcast Everyday", new_x="LMARGIN", new_y="NEXT", align="R")
        self.ln(5)

    def chapter_title(self, title: str):
        self.set_font("helvetica", "B", 22)
        self.set_text_color(40, 40, 40)
        title_safe = title.encode("latin-1", "replace").decode("latin-1")
        self.multi_cell(0, 15, title_safe, new_x="LMARGIN", new_y="NEXT", align="C")
        self.ln(10)

    def chapter_body(self, title: str, script: List[Dict]):
        self.chapter_title(title)

        for item in script:
            item_type = item.get("type")
            if item_type == "heading":
                self.ln(5)
                self.set_font("helvetica", "B", 16)
                self.set_fill_color(240, 245, 250)
                self.set_text_color(20, 50, 100)

                heading_text = item.get("title", item.get("text_display", ""))
                text = heading_text.encode("latin-1", "replace").decode("latin-1")
                self.multi_cell(0, 12, f"  {text}", fill=True, new_x="LMARGIN", new_y="NEXT", align="L")
                self.ln(3)

                speaker = item.get("speaker", "")
                transition = item.get("text_display", "")
                if speaker and transition and transition != heading_text:
                    speaker_safe = speaker.encode("latin-1", "replace").decode("latin-1")
                    trans_safe = transition.encode("latin-1", "replace").decode("latin-1")
                    self.set_font("helvetica", "", 12)
                    self.set_text_color(45, 45, 45)
                    self.multi_cell(
                        0,
                        8,
                        f"**{speaker_safe}:** {trans_safe}",
                        markdown=True,
                        new_x="LMARGIN",
                        new_y="NEXT",
                    )
                self.ln(3)

            elif item_type == "dialogue":
                speaker = item.get("speaker", "Unknown").encode("latin-1", "replace").decode("latin-1")
                text = item.get("text_display", "").encode("latin-1", "replace").decode("latin-1")
                self.set_font("helvetica", "", 12)
                self.set_text_color(45, 45, 45)
                self.multi_cell(
                    0,
                    8,
                    f"**{speaker}:** {text}",
                    markdown=True,
                    new_x="LMARGIN",
                    new_y="NEXT",
                )
                self.ln(3)


def create_pdf_from_json(json_data: Dict, output_filename: str):
    pdf = PDF(orientation="P", unit="mm", format="A4")
    pdf.set_margins(left=20, top=20, right=20)
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=20)

    title = json_data.get("title", "Podcast Script")
    script = json_data.get("script", [])
    pdf.chapter_body(title, script)
    pdf.output(output_filename)


def main():
    if not os.path.exists(TOPICS_FILE):
        print("No topics.txt found. Run make_youtube_video.py first.")
        sys.exit(1)

    with open(TOPICS_FILE, "r", encoding="utf-8") as f:
        topics = [line.strip() for line in f if line.strip()]

    if not topics:
        print("Topic is empty.")
        sys.exit(1)

    topic_name = topics[0]
    json_data = generate_full_script(topic_name)

    safe_topic_name = "".join([c for c in topic_name if c.isalnum() or c == " "]).rstrip().replace(" ", "_")
    json_filename = os.path.join(OUTPUT_DIR, f"{safe_topic_name}_script.json")
    with open(json_filename, "w", encoding="utf-8") as f:
        json.dump(json_data, f, ensure_ascii=False, indent=2)
    print(f"\n  [Save] JSON: {json_filename}")

    clean_pdf_name = "".join([c for c in topic_name if c.isalnum() or c == " "]).strip() or safe_topic_name
    pdf_filename = os.path.join(OUTPUT_DIR, f"{clean_pdf_name}.pdf")
    create_pdf_from_json(json_data, pdf_filename)
    print(f"  [Save] PDF: {pdf_filename}")

    print("\n" + "=" * 60)
    print("  Script generation complete")
    print("=" * 60)


if __name__ == "__main__":
    main()
