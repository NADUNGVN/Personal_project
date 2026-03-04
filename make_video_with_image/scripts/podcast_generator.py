import os
import sys
import json
import time
from openai import OpenAI
from dotenv import load_dotenv
from fpdf import FPDF

# Load environment variables
load_dotenv(dotenv_path=os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".env"))

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
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INPUT_DIR = os.path.join(BASE_DIR, "input")
TOPICS_FILE = os.path.join(INPUT_DIR, "topics.txt")

# Read dynamic output directory if it exists, otherwise default to "output"
CURRENT_OUT_DIR_FILE = os.path.join(INPUT_DIR, "current_output_dir.txt")
if os.path.exists(CURRENT_OUT_DIR_FILE):
    with open(CURRENT_OUT_DIR_FILE, "r", encoding="utf-8") as f:
        OUTPUT_DIR = f.read().strip()
else:
    OUTPUT_DIR = os.path.join(BASE_DIR, "output")
    
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(INPUT_DIR, exist_ok=True)

# ================= MODEL CONFIGURATION =================
LLM_MODEL = "google/gemini-2.5-flash"
MAX_RETRIES = 2
# =======================================================

# ================= VOICE CASTING (Sync with kokoro_tts.py) =================
ALLOWED_SPEAKERS = ["Alex", "Sarah", "Michael", "Nicole", "Adam", "Sky"]
# ===========================================================================

# ================= SYSTEM PROMPT (Shared across all segments) =================
SYSTEM_PROMPT = """You are an expert scriptwriter for a professional ESL podcast called "English Podcast Everyday".
You write highly engaging, natural-sounding scripts for intermediate-to-advanced English learners.

Hosts: Alex (Male, analytical, explains grammar and vocabulary) and Sarah (Female, enthusiastic, provides vivid examples and encouragement).

VOICE CASTING FOR ROLEPLAYS:
When creating roleplay characters, you MUST ONLY use these names (our TTS engine requires them):
- "Michael" (Male Adult)
- "Nicole" (Female Adult)
- "Adam" (Male Adult)
- "Sky" (Female Adult)
DO NOT invent other names.

CRITICAL OUTPUT RULES:
1. Output ONLY valid JSON. No markdown, no extra text.
2. ESCAPE all quotes inside strings (e.g., "Then he said \\"hello\\" to me").
3. For EVERY item, generate ALL required fields.
4. For dialogue items, generate:
   - `text_display`: Clean, grammatically correct text for on-screen karaoke display.
   - `text_tts`: Text with TTS directing markup for natural Kokoro speech:
     * Use `[word](+2)` to EMPHASIZE key words (spoken louder/slower)
     * Use `[word](-1)` to DE-STRESS filler words (spoken lighter/faster): [just](-1), [like](-1), [oh](-1)
     * Use commas `,`, ellipses `...`, dashes `—` for natural pacing/pauses
     * Use `!` for excitement, `?` for rising intonation

CRITICAL HEADING RULES:
Every heading item (type="heading") MUST have these fields:
- `title`: SHORT chapter title for PDF ebook (max 8 words). Examples: "Audio Conversation #1: Weekend Plans", "Episode Recap".
- `text_display`: The HOST's FULL spoken transition sentence. This text appears as karaoke on the video screen. Can be as long as needed.
- `text_tts`: TTS-directed version of text_display (with markup). Used for audio generation.
- `speaker`: The host who speaks the transition (usually "Alex" or "Sarah").

EXCEPTION — MUTE headings (Intro & Outro):
- Intro heading: speaker="", text_display=same as title, text_tts="" (no audio, no karaoke)
- Outro heading: speaker="", text_display=same as title, text_tts="" (no audio, no karaoke)
- After a mute heading, the NEXT dialogue item starts speaking immediately.

You are a helpful assistant that only outputs strictly valid JSON objects without markdown."""
# ==============================================================================

# ================= SEGMENT DEFINITIONS =================
SEGMENTS = [
    {
        "id": 1,
        "name": "Intro",
        "prompt_template": """Write Segment 1: INTRO for the podcast about "{topic}".

RULES:
- The FIRST item MUST be a MUTE heading: type="heading", speaker="" (empty), text_tts="" (empty), text_display=same as title.
- The SECOND item MUST be a dialogue from Alex. He opens the show.
- Write a warm, fun, short welcoming exchange between Alex and Sarah (~6-8 dialogue turns).
- They greet the audience, encourage subscribing, and naturally tease today's topic "{topic}".
- Keep it conversational and upbeat, like two best friends hosting together.

OUTPUT FORMAT:
{{
  "segment_id": 1,
  "segment_name": "Intro",
  "script": [
    {{"type": "heading", "speaker": "", "title": "Welcome to English Podcast Everyday", "text_display": "Welcome to English Podcast Everyday", "text_tts": ""}},
    {{"type": "dialogue", "speaker": "Alex", "text_display": "Hello everyone, and welcome back!", "text_tts": "[Hello](+2) everyone, and [welcome](+2) back!"}}
  ]
}}"""
    },
    {
        "id": 2,
        "name": "Topic Introduction",
        "prompt_template": """Write Segment 2: TOPIC INTRODUCTION for the podcast about "{topic}".

PREVIOUS SCRIPT SO FAR:
---
{context}
---

RULES:
- Start with a heading: title is a SHORT chapter name, text_display is Alex's full spoken transition into the topic, speaker="Alex".
- Alex and Sarah introduce today's topic "{topic}" in depth.
- They explain WHY this topic matters for English learners.
- Teach 3-4 key vocabulary words/phrases/idioms related to "{topic}". Explain each with examples and natural usage.
- Make explanations come alive with personal anecdotes and humor, NOT dry dictionary definitions.
- ~10-15 dialogue turns.

OUTPUT FORMAT:
{{
  "segment_id": 2,
  "segment_name": "Topic Introduction",
  "script": [
    {{"type": "heading", "speaker": "Alex", "title": "Understanding Healthy Habits", "text_display": "Alright, so today we're diving into something really exciting and super practical for your English journey: healthy habits!", "text_tts": "[Alright](+2), so today we're diving into something [really](+2) exciting and super practical for your English journey: [healthy habits](+2)!"}},
    {{"type": "dialogue", "speaker": "Sarah", "text_display": "...", "text_tts": "..."}}
  ]
}}"""
    },
    {
        "id": 3,
        "name": "Audio Conversation #1",
        "prompt_template": """Write Segment 3: AUDIO CONVERSATION #1 for the podcast about "{topic}".

PREVIOUS SCRIPT SO FAR:
---
{context}
---

RULES:
- Start with a heading: title is SHORT (e.g., "Audio Conversation #1: Wellness Goals"), text_display is Sarah's full introduction of the upcoming conversation, speaker="Sarah".
- Then write a LONG, hyper-realistic roleplay conversation (~15-20 dialogue turns) between two characters.
- Choose characters from: Michael, Nicole, Adam, Sky (pick any two, or use Alex and Sarah themselves if it fits better).
- The conversation must NATURALLY incorporate the vocabulary and phrases taught in the previous segment.
- One character should speak at B1 level (simpler sentences, occasional mistakes), the other at B2+ level (phrasal verbs, idioms, complex structures).
- Make the conversation feel like a real everyday interaction, with fillers, reactions, and natural flow.

OUTPUT FORMAT:
{{
  "segment_id": 3,
  "segment_name": "Audio Conversation #1: [Creative Subtitle]",
  "script": [
    {{"type": "heading", "speaker": "Sarah", "title": "Audio Conversation #1: Wellness Goals", "text_display": "Alright everyone, now let's hear a real conversation! Listen closely for those key phrases we just learned. Here's a chat between Michael and Nicole about their wellness goals!", "text_tts": "[Alright](+2) everyone, now let's hear a [real](+2) conversation! [Listen closely](+2) for those key phrases we [just](-1) learned. Here's a chat between Michael and Nicole about their [wellness](+2) goals!"}},
    {{"type": "dialogue", "speaker": "Michael", "text_display": "Hey Nicole! ...", "text_tts": "[Hey](+2) Nicole! ..."}}
  ]
}}"""
    },
    {
        "id": 4,
        "name": "Analysis & Vocabulary Breakdown",
        "prompt_template": """Write Segment 4: ANALYSIS & VOCABULARY BREAKDOWN for the podcast about "{topic}".

PREVIOUS SCRIPT SO FAR:
---
{context}
---

RULES:
- Start with a heading: title is SHORT (e.g., "Analysis & Vocabulary Breakdown"), text_display is Alex's full transition into analysis mode, speaker="Alex".
- Alex and Sarah analyze Audio Conversation #1 that just played.
- Reference SPECIFIC lines/phrases from the conversation (e.g., "Did you catch when Michael said '...'?").
- Break down phrasal verbs, idioms, and useful expressions used in the conversation.
- Explain B1 vs B2 differences they noticed.
- Give alternative ways to express the same ideas.
- ~8-12 dialogue turns.

OUTPUT FORMAT:
{{
  "segment_id": 4,
  "segment_name": "Analysis & Vocabulary Breakdown",
  "script": [
    {{"type": "heading", "speaker": "Alex", "title": "Analysis & Vocabulary Breakdown", "text_display": "Alright everyone, welcome back! That was a great conversation between Michael and Nicole. Now, let's break it down and unpack some of the fantastic language they used.", "text_tts": "[Alright](+2) everyone, welcome back! That was a [great](+2) conversation between Michael and Nicole. Now, let's [break it down](+2) and unpack some of the [fantastic](+2) language they used."}},
    {{"type": "dialogue", "speaker": "Sarah", "text_display": "...", "text_tts": "..."}}
  ]
}}"""
    },
    {
        "id": 5,
        "name": "Topic Part 2",
        "prompt_template": """Write Segment 5: TOPIC PART 2 for the podcast about "{topic}".

PREVIOUS SCRIPT SO FAR:
---
{context}
---

RULES:
- Start with a heading: title is SHORT, text_display is Sarah's full transition to the new angle, speaker="Sarah".
- Pivot to a DIFFERENT angle or sub-topic within "{topic}" that hasn't been covered yet.
- Teach 3-4 NEW vocabulary words/phrases (DO NOT repeat vocabulary from earlier segments).
- Include common mistakes that learners make when discussing this aspect.
- Show correct vs incorrect usage with clear examples.
- ~10-12 dialogue turns.

OUTPUT FORMAT:
{{
  "segment_id": 5,
  "segment_name": "Topic Part 2: [Creative Subtitle]",
  "script": [
    {{"type": "heading", "speaker": "Sarah", "title": "Environment & Social Influence", "text_display": "Now let's look at another really important side of this topic! Beyond personal discipline, how do our surroundings and relationships influence our healthy habits?", "text_tts": "Now let's look at another [really important](+2) side of this topic! Beyond personal discipline, how do our [surroundings](+2) and [relationships](+2) influence our healthy habits?"}},
    {{"type": "dialogue", "speaker": "Alex", "text_display": "...", "text_tts": "..."}}
  ]
}}"""
    },
    {
        "id": 6,
        "name": "Audio Conversation #2",
        "prompt_template": """Write Segment 6: AUDIO CONVERSATION #2 for the podcast about "{topic}".

PREVIOUS SCRIPT SO FAR:
---
{context}
---

RULES:
- Start with a heading: title is SHORT (e.g., "Audio Conversation #2: Fitness Journey"), text_display is Alex's full introduction, speaker="Alex".
- Write another LONG, realistic roleplay (~15-20 dialogue turns).
- Use a DIFFERENT pair of characters than Audio #1 (choose from: Michael, Nicole, Adam, Sky, Alex, Sarah).
- This conversation should incorporate the NEW vocabulary from Topic Part 2.
- Again, one speaker at B1 level, the other at B2+ level.
- Different scenario/setting from Audio #1 to keep things fresh.

OUTPUT FORMAT:
{{
  "segment_id": 6,
  "segment_name": "Audio Conversation #2: [Creative Subtitle]",
  "script": [
    {{"type": "heading", "speaker": "Alex", "title": "Audio Conversation #2: Fitness Journey", "text_display": "Alright everyone, let's hear another real-world example! This time, we have Adam and Sky discussing their fitness journeys. Listen out for those new phrases we just covered!", "text_tts": "[Alright](+2) everyone, let's hear another [real-world](+2) example! This time, we have Adam and Sky discussing their fitness journeys. Listen out for those [new phrases](+2) we [just](-1) covered!"}},
    {{"type": "dialogue", "speaker": "Adam", "text_display": "Hey Sky! ...", "text_tts": "[Hey](+2) Sky! ..."}}
  ]
}}"""
    },
    {
        "id": 7,
        "name": "Analysis & Level Comparison",
        "prompt_template": """Write Segment 7: ANALYSIS & LEVEL COMPARISON for the podcast about "{topic}".

PREVIOUS SCRIPT SO FAR:
---
{context}
---

RULES:
- Start with a heading: title is SHORT (e.g., "Analysis & Level Comparison"), text_display is Sarah's full transition, speaker="Sarah".
- Alex and Sarah dissect Audio Conversation #2.
- FOCUS on B1 vs B2 level comparison: point out specific phrases where one speaker used simpler language and the other used more advanced expressions.
- Highlight hedging language, softeners, idioms, and natural speech patterns from the B2 speaker.
- Point out common B1 errors (dropped articles, wrong prepositions, etc.) and how to fix them.
- ~8-12 dialogue turns.

OUTPUT FORMAT:
{{
  "segment_id": 7,
  "segment_name": "Analysis & Level Comparison",
  "script": [
    {{"type": "heading", "speaker": "Sarah", "title": "Analysis & Level Comparison", "text_display": "Great conversation! Now let's break it down and compare B1 and B2 level language!", "text_tts": "[Great](+2) conversation! Now let's [break it down](+2) and compare B1 and B2 level language!"}},
    {{"type": "dialogue", "speaker": "Alex", "text_display": "...", "text_tts": "..."}}
  ]
}}"""
    },
    {
        "id": 8,
        "name": "Episode Recap",
        "prompt_template": """Write Segment 8: EPISODE RECAP for the podcast about "{topic}".

PREVIOUS SCRIPT SO FAR:
---
{context}
---

RULES:
- Start with a heading: title is SHORT (e.g., "Episode Recap"), text_display is Alex's full transition, speaker="Alex".
- Alex and Sarah do a lightning-fast recap of EVERYTHING covered in this episode.
- Mention ALL key vocabulary, phrases, and grammar points taught throughout.
- Reference both audio conversations briefly.
- Give the listener a clear summary of what they should have learned.
- Keep it energetic and encouraging.
- ~6-8 dialogue turns.
- IMPORTANT: This segment is ONLY the recap. Do NOT include goodbye, thank you, CTA, or sign-off. Those belong in Segment 9 (Outro).

OUTPUT FORMAT:
{{
  "segment_id": 8,
  "segment_name": "Episode Recap",
  "script": [
    {{"type": "heading", "speaker": "Alex", "title": "Episode Recap", "text_display": "Alright everyone, let's do a quick recap of everything we covered in today's episode!", "text_tts": "Alright everyone, let's do a [quick recap](+2) of everything we covered in today's episode!"}},
    {{"type": "dialogue", "speaker": "Sarah", "text_display": "...", "text_tts": "..."}}
  ]
}}"""
    },
    {
        "id": 9,
        "name": "Outro",
        "prompt_template": """Write Segment 9: OUTRO for the podcast about "{topic}".

PREVIOUS SCRIPT SO FAR:
---
{context}
---

RULES:
- The FIRST item MUST be a MUTE heading: type="heading", speaker="" (empty), text_tts="" (empty), text_display=same as title. This heading is for the PDF only.
- The SECOND item MUST be a dialogue from Alex. He starts the sign-off.
- IMPORTANT: This segment is ONLY the sign-off. Do NOT recap vocabulary or repeat content from Segment 8.
- Warm, friendly goodbye from both Alex and Sarah.
- Thank listeners for tuning in.
- CTA: subscribe, like, leave a comment with topic suggestions.
- Encourage them to keep practicing English.
- End on a positive, uplifting note.
- ~4-6 dialogue turns. Keep it short and sweet.

OUTPUT FORMAT:
{{
  "segment_id": 9,
  "segment_name": "Outro",
  "script": [
    {{"type": "heading", "speaker": "", "title": "Outro", "text_display": "Outro", "text_tts": ""}},
    {{"type": "dialogue", "speaker": "Alex", "text_display": "Well, that brings us to the end of today's episode!", "text_tts": "Well, that brings us to the [end](+2) of today's episode!"}}
  ]
}}"""
    },
]
# =======================================================


def build_accumulated_text(completed_segments: list) -> str:
    """Ghép text_display từ tất cả segment đã hoàn thành thành chuỗi context sạch."""
    lines = []
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


def validate_segment(segment_data: dict, segment_config: dict) -> list:
    """Validate segment JSON. Returns list of error messages (empty = OK)."""
    errors = []
    segment_id = segment_config["id"]
    
    if not isinstance(segment_data, dict):
        errors.append("Output is not a JSON object")
        return errors
    
    script = segment_data.get("script", [])
    if not script:
        errors.append("Missing or empty 'script' array")
        return errors
    
    # Check first item is heading
    first_item = script[0]
    if first_item.get("type") != "heading":
        errors.append("First item must be type='heading'")
    
    # Heading must have 'title' field
    if "title" not in first_item:
        errors.append("Heading is missing 'title' field")
    
    # Intro segment: heading must be muted
    if segment_id == 1:
        if first_item.get("speaker", "x") != "":
            errors.append("Intro heading speaker must be empty string")
        if first_item.get("text_tts", "x") != "":
            errors.append("Intro heading text_tts must be empty string")
        # Second item must be Alex
        if len(script) > 1 and script[1].get("speaker") != "Alex":
            errors.append("First dialogue after Intro heading must be from Alex")
    
    # Outro segment: heading must be muted
    if segment_id == 9:
        if first_item.get("speaker", "x") != "":
            errors.append("Outro heading speaker must be empty string")
        if first_item.get("text_tts", "x") != "":
            errors.append("Outro heading text_tts must be empty string")
        # Second item must be Alex
        if len(script) > 1 and script[1].get("speaker") != "Alex":
            errors.append("First dialogue after Outro heading must be from Alex")
    
    # Check all items have required fields
    for i, item in enumerate(script):
        for field in ["type", "speaker", "text_display", "text_tts"]:
            if field not in item:
                errors.append(f"Item {i}: missing field '{field}'")
        
        # Heading items must have 'title'
        if item.get("type") == "heading" and "title" not in item:
            errors.append(f"Item {i}: heading missing 'title' field")
        
        # Check speaker is valid
        speaker = item.get("speaker", "")
        if speaker and speaker not in ALLOWED_SPEAKERS:
            errors.append(f"Item {i}: unknown speaker '{speaker}'. Allowed: {ALLOWED_SPEAKERS}")
    
    return errors


def generate_segment(segment_config: dict, topic: str, accumulated_text: str) -> dict:
    """Generate a single segment via LLM API with retry."""
    segment_id = segment_config["id"]
    segment_name = segment_config["name"]
    
    # Build prompt
    prompt = segment_config["prompt_template"].format(
        topic=topic,
        context=accumulated_text if accumulated_text else "(This is the first segment, no previous context.)"
    )
    
    for attempt in range(1, MAX_RETRIES + 2):  # attempt 1, 2, 3 (1 + 2 retries)
        try:
            print(f"  🔄 Calling LLM for Segment {segment_id}: {segment_name} (attempt {attempt})...")
            
            response = client.chat.completions.create(
                model=LLM_MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
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
            
            segment_data = json.loads(text.strip())
            
            # Validate
            errors = validate_segment(segment_data, segment_config)
            if errors:
                print(f"  ⚠️  Validation errors: {errors}")
                if attempt <= MAX_RETRIES:
                    print(f"  🔁 Retrying...")
                    # Add error feedback to prompt for retry
                    prompt += f"\n\nPREVIOUS ATTEMPT HAD ERRORS: {errors}\nPlease fix these issues."
                    continue
                else:
                    print(f"  ⚠️  Proceeding with validation warnings after {MAX_RETRIES} retries.")
            
            return segment_data
            
        except json.JSONDecodeError as e:
            print(f"  ❌ JSON parse error: {e}")
            if attempt <= MAX_RETRIES:
                print(f"  🔁 Retrying...")
                continue
            else:
                print(f"  ❌ Failed to parse JSON after {MAX_RETRIES} retries.")
                if 'text' in locals():
                    print(f"  --- RAW RESPONSE (first 500 chars) ---")
                    print(text[:500])
                sys.exit(1)
                
        except Exception as e:
            print(f"  ❌ API error: {e}")
            if attempt <= MAX_RETRIES:
                print(f"  🔁 Retrying in 5 seconds...")
                time.sleep(5)
                continue
            else:
                print(f"  ❌ Failed after {MAX_RETRIES} retries.")
                sys.exit(1)


def merge_segments(topic: str, segments: list) -> dict:
    """Merge all segment scripts into one final JSON output."""
    merged_script = []
    for seg in segments:
        merged_script.extend(seg.get("script", []))
    
    return {
        "title": f"English Podcast Everyday - {topic}",
        "script": merged_script
    }


def generate_full_script(topic: str) -> dict:
    """Orchestrate the full 9-segment generation pipeline."""
    completed_segments = []
    total = len(SEGMENTS)
    
    print(f"\n{'='*55}")
    print(f"  📝 MULTI-STEP SCRIPT GENERATION")
    print(f"  📌 Topic: {topic}")
    print(f"  🔢 Segments: {total}")
    print(f"{'='*55}\n")
    
    for segment_config in SEGMENTS:
        seg_id = segment_config["id"]
        seg_name = segment_config["name"]
        
        print(f"\n  [{seg_id}/{total}] ━━━ {seg_name} ━━━")
        
        # Build accumulated context from all previous segments
        accumulated_text = build_accumulated_text(completed_segments)
        
        # Generate this segment
        start_time = time.time()
        segment_data = generate_segment(segment_config, topic, accumulated_text)
        elapsed = time.time() - start_time
        
        # Count dialogue turns
        turns = len([i for i in segment_data.get("script", []) if i.get("type") == "dialogue"])
        print(f"  ✅ [{seg_id}/{total}] {seg_name} — {turns} dialogue turns ({elapsed:.1f}s)")
        
        completed_segments.append(segment_data)
    
    # Merge all segments
    print(f"\n  🔗 Merging {total} segments...")
    merged = merge_segments(topic, completed_segments)
    total_turns = len([i for i in merged["script"] if i.get("type") == "dialogue"])
    total_headings = len([i for i in merged["script"] if i.get("type") == "heading"])
    print(f"  📊 Final: {total_headings} headings + {total_turns} dialogue turns")
    
    return merged


# ================= PDF EBOOK GENERATION =================
class PDF(FPDF):
    def header(self):
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
                self.ln(5)
                self.set_font("helvetica", "B", 16)
                self.set_fill_color(240, 245, 250)
                self.set_text_color(20, 50, 100)
                # Use 'title' field for PDF chapter heading (short title)
                heading_text = item.get("title", item.get("text_display", ""))
                text = heading_text.encode('latin-1', 'replace').decode('latin-1')
                self.multi_cell(0, 12, f"  {text}", fill=True, new_x="LMARGIN", new_y="NEXT", align='L')
                self.ln(3)
                
                # In câu dẫn (text_display) bên dưới tiêu đề cho heading có speaker
                speaker = item.get("speaker", "")
                transition = item.get("text_display", "")
                if speaker and transition and transition != heading_text:
                    speaker_safe = speaker.encode('latin-1', 'replace').decode('latin-1')
                    transition_safe = transition.encode('latin-1', 'replace').decode('latin-1')
                    self.set_font("helvetica", "", 12)
                    self.set_text_color(45, 45, 45)
                    self.multi_cell(0, 8, f"**{speaker_safe}:** {transition_safe}", markdown=True, new_x="LMARGIN", new_y="NEXT")
                self.ln(3)
            
            elif item.get("type") == "dialogue":
                speaker = item.get("speaker", "Unknown").encode('latin-1', 'replace').decode('latin-1')
                text = item.get("text_display", "").encode('latin-1', 'replace').decode('latin-1')
                
                self.set_font("helvetica", "", 12)
                self.set_text_color(45, 45, 45)
                
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
# ========================================================


def main():
    if not os.path.exists(TOPICS_FILE):
        print("No topics.txt found. Please run make_youtube_video.py first to specify a topic.")
        sys.exit(1)

    with open(TOPICS_FILE, "r", encoding="utf-8") as f:
        topic_name = f.read().strip()

    if not topic_name:
        print("Topic is empty.")
        sys.exit(1)

    # Generate full script via multi-step pipeline
    json_data = generate_full_script(topic_name)
    
    # Create safe filename based on topic
    safe_topic_name = "".join([c for c in topic_name if c.isalnum() or c==' ']).rstrip().replace(" ", "_")
    
    # Save JSON
    json_filename = os.path.join(OUTPUT_DIR, f"{safe_topic_name}_script.json")
    with open(json_filename, "w", encoding="utf-8") as f:
        json.dump(json_data, f, ensure_ascii=False, indent=2)
    print(f"\n  💾 JSON saved to {json_filename}")
    
    # Save PDF (E-book style)
    pdf_filename = os.path.join(OUTPUT_DIR, f"{safe_topic_name}_script.pdf")
    create_pdf_from_json(json_data, pdf_filename)
    print(f"  📕 PDF saved to {pdf_filename}")

    print(f"\n{'='*55}")
    print(f"  🎉 Script generation complete!")
    print(f"{'='*55}\n")


if __name__ == "__main__":
    main()
