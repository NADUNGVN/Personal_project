from pathlib import Path
import sys


ROOT_DIR = Path(__file__).resolve().parent
SRC_DIR = ROOT_DIR / "src"
AUDIO_DATASET_SRC_DIR = ROOT_DIR / "audio_dataset" / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
if str(AUDIO_DATASET_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(AUDIO_DATASET_SRC_DIR))

from focus_music_video.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
