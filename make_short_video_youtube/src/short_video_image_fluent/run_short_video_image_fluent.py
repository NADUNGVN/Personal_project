import json
import subprocess
import sys
from pathlib import Path

MODE_LLM_FULL = "1"
MODE_LLM_FROM_TITLE = "2"
MODE_MANUAL = "3"

FLOW_NEW = "1"
FLOW_CONTINUE = "2"


def run_step(script_path: Path, extra_args: list[str] | None = None):
    print(f"\n{'=' * 80}")
    print(f"Running: {script_path.name}")
    print(f"{'=' * 80}\n")

    command = [sys.executable, str(script_path)]
    if extra_args:
        command.extend(extra_args)

    result = subprocess.run(command, cwd=str(script_path.parent.parent.parent))

    if result.returncode != 0:
        print(f"\nPipeline stopped: {script_path.name} failed with exit code {result.returncode}.")
        sys.exit(result.returncode)


def prompt_required(prompt_text: str) -> str:
    while True:
        value = input(prompt_text).strip()
        if value:
            return value
        print("Input cannot be empty. Please try again.")


def prompt_optional(prompt_text: str) -> str | None:
    value = input(prompt_text).strip()
    return value or None


def prompt_optional_int(prompt_text: str) -> str | None:
    while True:
        value = input(prompt_text).strip()
        if not value:
            return None
        if value.isdigit() and int(value) > 0:
            return value
        print("Please enter a positive integer or press ENTER to skip.")


def prompt_multiline_text() -> str:
    print("Enter text content (multi-line allowed).")
    print("Press ENTER on an empty line to finish, or type END on a new line.")
    while True:
        lines: list[str] = []
        while True:
            line = input()
            if line.strip().upper() == "END":
                break
            if line == "" and lines:
                break
            lines.append(line)

        text = "\n".join(lines).strip()
        if text:
            return text
        print("Text cannot be empty. Please input again.")


def choose_flow_mode() -> str:
    print("\nSelect pipeline action:")
    print("1) Create new project")
    print("2) Continue existing project by path")
    while True:
        choice = input("Choose action (1/2): ").strip()
        if choice in {FLOW_NEW, FLOW_CONTINUE}:
            return choice
        print("Invalid choice. Please enter 1 or 2.")


def choose_content_mode() -> str:
    print("\nSelect content generation mode for Step 1:")
    print("1) LLM full generation from theme/topic (current behavior)")
    print("2) You provide title, LLM generates only text")
    print("3) You provide title + text, no LLM in Step 1")

    while True:
        choice = input("Choose mode (1/2/3): ").strip()
        if choice in {MODE_LLM_FULL, MODE_LLM_FROM_TITLE, MODE_MANUAL}:
            return choice
        print("Invalid choice. Please enter 1, 2, or 3.")


def build_step1_args(mode: str) -> list[str]:
    args = ["--content-mode", mode]

    if mode in {MODE_LLM_FULL, MODE_LLM_FROM_TITLE}:
        difficulty = prompt_optional("Difficulty (default A2-B1): ")
        if difficulty:
            args.extend(["--difficulty", difficulty])

        target_duration = prompt_optional_int("Target duration in seconds (default 55): ")
        if target_duration:
            args.extend(["--target-duration", target_duration])

    if mode == MODE_LLM_FULL:
        topic = prompt_optional("Specific topic (optional, Enter to skip): ")
        if topic:
            args.extend(["--topic", topic])
        else:
            theme = prompt_optional("Theme (optional, Enter for default): ")
            if theme:
                args.extend(["--theme", theme])

    elif mode == MODE_LLM_FROM_TITLE:
        title = prompt_required("Title EN (required): ")
        args.extend(["--title-en", title])

        hashtags = prompt_optional("Custom hashtags (optional): ")
        if hashtags:
            args.extend(["--hashtags", hashtags])

    elif mode == MODE_MANUAL:
        title = prompt_required("Title EN (required): ")
        text = prompt_multiline_text()
        args.extend(["--title-en", title, "--text-en", text])

    return args


def clean_user_path(raw_path: str) -> Path:
    cleaned = raw_path.strip().strip('"').strip("'")
    return Path(cleaned).expanduser().resolve()


def prompt_project_dir() -> Path:
    while True:
        raw = prompt_required("Enter existing project folder path: ")
        path = clean_user_path(raw)
        if not path.exists():
            print(f"Path does not exist: {path}")
            continue
        if not path.is_dir():
            print(f"Path is not a folder: {path}")
            continue
        return path


def is_nonempty_file(path: Path) -> bool:
    try:
        return path.exists() and path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


def load_json_file(path: Path) -> dict | None:
    if not is_nonempty_file(path):
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def check_step1(project_dir: Path) -> tuple[bool, str]:
    content_path = project_dir / "01_content" / "content.json"
    data = load_json_file(content_path)
    if data is None:
        return False, "Missing/invalid 01_content/content.json"

    required = ("topic", "title_en", "text_en", "difficulty")
    missing = [k for k in required if not isinstance(data.get(k), str) or not data.get(k, "").strip()]
    if missing:
        return False, f"content.json missing required fields: {missing}"
    return True, "Step 1 completed"


def check_step2(project_dir: Path) -> tuple[bool, str]:
    wav_path = project_dir / "02_audio" / "audio.wav"
    if not is_nonempty_file(wav_path):
        return False, "Missing/invalid 02_audio/audio.wav"
    return True, "Step 2 completed"


def check_step3(project_dir: Path) -> tuple[bool, str]:
    video_path = project_dir / "03_video" / "final_short.mp4"
    status_path = project_dir / "03_video" / "render_status.json"

    if not is_nonempty_file(video_path):
        return False, "Missing/invalid 03_video/final_short.mp4"

    status = load_json_file(status_path)
    if status is None:
        return False, "Missing/invalid 03_video/render_status.json (cannot confirm render reached 100%)"

    is_completed = status.get("status") == "completed"
    is_success = bool(status.get("success"))
    progress = int(status.get("progress_percent", 0) or 0)
    if is_completed and is_success and progress >= 100:
        return True, "Step 3 completed (render 100%)"

    return False, f"Render status is not completed: status={status.get('status')}, progress={progress}%"


def check_step4(project_dir: Path) -> tuple[bool, str]:
    metadata_path = project_dir / "04_metadata" / "youtube_metadata.md"
    if not is_nonempty_file(metadata_path):
        return False, "Missing/invalid 04_metadata/youtube_metadata.md"
    return True, "Step 4 completed"


def inspect_steps(project_dir: Path) -> dict[int, tuple[bool, str]]:
    return {
        1: check_step1(project_dir),
        2: check_step2(project_dir),
        3: check_step3(project_dir),
        4: check_step4(project_dir),
    }


def determine_next_step(step_checks: dict[int, tuple[bool, str]]) -> int | None:
    for step_idx in (1, 2, 3, 4):
        if not step_checks[step_idx][0]:
            return step_idx
    return None


def print_step_report(step_checks: dict[int, tuple[bool, str]]) -> None:
    print("\nProject step inspection:")
    for step_idx in (1, 2, 3, 4):
        ok, detail = step_checks[step_idx]
        status = "DONE" if ok else "PENDING"
        print(f"- Step {step_idx}: {status} | {detail}")


def run_new_pipeline(step1: Path, step2: Path, step3: Path, step4: Path) -> None:
    selected_mode = choose_content_mode()
    step1_args = build_step1_args(selected_mode)

    run_step(step1, step1_args)
    run_step(step2)
    run_step(step3)
    run_step(step4)


def run_continue_pipeline(project_dir: Path, step2: Path, step3: Path, step4: Path) -> bool:
    step_checks = inspect_steps(project_dir)
    print_step_report(step_checks)

    next_step = determine_next_step(step_checks)
    if next_step is None:
        print("\nAll steps are already completed for this project.")
        return True

    if next_step == 1:
        print("\nCannot continue from Step 1 with existing folder.")
        print("Please choose 'Create new project' to generate Step 1 content.")
        return False

    print(f"\nContinuing from Step {next_step} for project: {project_dir}")

    if next_step <= 2:
        run_step(step2, ["--project-dir", str(project_dir)])
    if next_step <= 3:
        run_step(step3, ["--project-dir", str(project_dir)])
    if next_step <= 4:
        run_step(step4, ["--project-dir", str(project_dir)])
    return True


def main():
    root_dir = Path(__file__).resolve().parent

    step1 = root_dir / "step1_generate_content.py"
    step2 = root_dir / "step2_generate_audio.py"
    step3 = root_dir / "step3_generate_video.py"
    step4 = root_dir / "step4_generate_metadata.py"

    if not step1.exists() or not step2.exists() or not step3.exists() or not step4.exists():
        print("Could not find all pipeline scripts in the current directory.")
        sys.exit(1)

    print("SocialHarvester Complete Video Pipeline")
    flow_mode = choose_flow_mode()

    success = True
    if flow_mode == FLOW_NEW:
        run_new_pipeline(step1, step2, step3, step4)
    else:
        project_dir = prompt_project_dir()
        success = run_continue_pipeline(project_dir, step2, step3, step4)

    if success:
        print(f"\n{'=' * 80}")
        print("Pipeline completed successfully.")
        print(f"{'=' * 80}")
    else:
        print("\nPipeline was not executed because the selected project is not ready to continue.")


if __name__ == "__main__":
    main()
