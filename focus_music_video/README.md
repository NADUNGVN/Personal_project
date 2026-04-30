# Focus Music Video Pipeline

This subproject builds long-form `Study / Focus Music Video` outputs from one shared source package:

- one music track
- one background image or loop video
- one shared concept
- four channel-specific outputs

The goal is to keep one pipeline while packaging the same source into four clear channel targets:

1. `Lo-fi Hip Hop / Lo-fi Jazz`
2. `Study with Me / Work with Me`
3. `Ambient Video / Aesthetic Video`
4. `Deep Sleep / Relax`

## Output Structure

Each project writes into a predictable output tree:

```text
focus_music_video/projects/<project_name>/
├── input/
│   ├── audio/
│   │   └── main_track.mp3
│   └── background/
│       └── background.jpg
├── output/
│   ├── build_manifest.json
│   ├── 01_lofi_hiphop_jazz/
│   ├── 02_study_with_me_work_with_me/
│   ├── 03_ambient_aesthetic_video/
│   └── 04_deep_sleep_relax/
└── project.json
```

Each channel folder contains:

- `final_video.mp4`
- `metadata.json`
- `youtube_metadata.md`
- `job_manifest.json`

## Commands

Recommended day-to-day workflow:

```powershell
python run.py
```

This opens the interactive production wizard:

1. collect audio from `1 URL` or `many URLs`
2. choose an existing internal channel or create a new one
3. crawl the selected YouTube audio and build `audio_final.m4a`
4. choose a background `image` or `video`
5. render the final MP4
6. generate the final YouTube `title + description` when `OPENROUTER_API_KEY` is available

List the built-in channel profiles:

```powershell
python run.py list-profiles
```

Create a new project scaffold:

```powershell
python run.py init-project --name rainy_night_library --title "Rainy Night Library Session"
```

Build all four outputs:

```powershell
python run.py build --project "D:\work\Personal_project\focus_music_video\projects\rainy_night_library\project.json"
```

Build one profile only:

```powershell
python run.py build --project "D:\work\Personal_project\focus_music_video\projects\rainy_night_library\project.json" --profile lofi_hiphop_jazz
```

Generate manifests and metadata without rendering:

```powershell
python run.py build --project "D:\work\Personal_project\focus_music_video\projects\rainy_night_library\project.json" --dry-run
```

Render a short preview:

```powershell
python run.py build --project "D:\work\Personal_project\focus_music_video\projects\rainy_night_library\project.json" --profile ambient_aesthetic_video --preview-seconds 30
```

Build one long audio mix from the crawled dataset and generate the YouTube text blocks:

```powershell
python run.py build-mix --source lofidailystudio --name first_video
```

This writes:

- `productions/<source>/<mix_name>/audio/audio_final.m4a`
- `productions/<source>/<mix_name>/metadata/tracklist.txt`
- `productions/<source>/<mix_name>/metadata/music_credits.txt`
- `productions/<source>/<mix_name>/metadata/youtube_description_blocks.md`
- `productions/<source>/<mix_name>/metadata/mix_manifest.json`

Render one final MP4 from the mix with an image or video background, a countdown at the top, and an audio bar at the bottom:

```powershell
python run.py render-mix-video --source lofidailystudio --name first_video --background "D:\work\Personal_project\focus_music_video\input\video\Video Project 43.mp4"
```

Run the full non-interactive production pipeline in one command:

```powershell
python run.py build-final-package --source lofidailystudio --name first_video --background "D:\work\Personal_project\focus_music_video\input\video\Video Project 43.mp4"
```

## Project Model

`project.json` stores the shared source inputs and the common pipeline settings. The four outputs differ only by profile:

- channel positioning
- overlay copy
- metadata copy
- color and overlay treatment
- keywords and hashtags

This keeps the workflow centralized while preserving separate channel packaging.

## Notes

- Rendering uses `ffmpeg` and `ffprobe`.
- Background can be a still image or a loopable video.
- This version focuses on packaging and repeatable output structure.
- A later step can plug in AI music generation, thumbnail generation, or automated upload.
