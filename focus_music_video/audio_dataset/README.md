# Focus Music Audio Dataset

This folder is dedicated to building a structured audio dataset for:

- `music`
- `ambient`

It only keeps the YouTube ingestion logic needed for this project.
Everything unrelated to YouTube audio crawling is intentionally excluded.

## Goal

Use a small set of no-copyright YouTube channels as trusted sources and build a clean dataset tree that is ready for:

- asset review
- tagging
- later audio normalization
- later video packaging

## Folder Structure

```text
focus_music_video/audio_dataset/
├── config/
│   ├── youtube_channels.template.json
│   └── youtube_channels.json
├── dataset/
│   ├── music/
│   └── ambient/
├── state/
│   └── download_archives/
├── src/
└── run.py
```

After crawling, each channel is stored like this:

```text
dataset/<music|ambient>/<channel_slug>/
├── channel_manifest.json
├── sources/
│   └── <source_entry_key>.json
└── items/
    └── <youtube_video_id>/
        ├── audio/
        ├── metadata/
        ├── thumbnails/
        └── other/
```

## Config Model

Each source entry defines:

- `name`: local channel label
- `dataset_type`: `music` or `ambient`
- `purpose`: one of the three target channel directions
- `url`: YouTube channel / playlist / video URL
- `tags`: freeform tags for later filtering
- `max_items`: optional cap per source
- `enabled`: source toggle

Multiple URLs can belong to the same local channel name. They will be grouped under one dataset channel folder and tracked as separate source entries.

## Commands

Run without arguments to open the wizard:

```powershell
python run.py
```

The terminal will show two modes:

- create with 1 URL
- create with multiple URLs

Create an empty working config:

```powershell
python run.py init-config
```

The example schema remains in `config/youtube_channels.template.json`.

Add one source interactively after you paste a URL:

```powershell
python run.py add-source --url "https://www.youtube.com/@example"
```

Open the wizard explicitly:

```powershell
python run.py interactive
```

If you want to auto-suggest the detected source name from YouTube metadata, add `--probe`.

Validate the current config:

```powershell
python run.py validate-config
```

Crawl every enabled source:

```powershell
python run.py crawl
```

Crawl only one source:

```powershell
python run.py crawl --source lofi_girl
```

## Notes

- Downloading uses `yt_dlp`.
- The crawler writes audio, metadata, thumbnails, and manifests.
- A per-channel download archive prevents duplicate downloads across reruns.
- `add-source` prompts for channel name, `music|ambient`, and the target channel purpose.
- The next step can add normalization, deduplication, and audio quality scoring.
