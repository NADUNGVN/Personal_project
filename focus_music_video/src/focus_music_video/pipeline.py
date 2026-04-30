from __future__ import annotations

import json
from dataclasses import asdict

from focus_music_video.models import BuildJob, ChannelProfile, ProjectConfig
from focus_music_video.utils import format_duration_label, unique_preserve


def build_job(
    project: ProjectConfig,
    profile: ChannelProfile,
    source_duration_seconds: float,
    preview_seconds: float | None = None,
) -> BuildJob:
    duration_seconds = source_duration_seconds
    is_preview = preview_seconds is not None
    if preview_seconds is not None:
        duration_seconds = min(duration_seconds, max(1.0, preview_seconds))

    duration_label = format_duration_label(duration_seconds)
    override = project.channel_overrides.get(profile.slug, {})

    overlay_title = override.get("overlay_title") or profile.overlay_title_template.format(
        title=project.title,
        concept=project.concept,
        duration_label=duration_label,
        channel_name=profile.channel_name,
    )
    overlay_subtitle = override.get("overlay_subtitle") or profile.overlay_subtitle_template.format(
        title=project.title,
        concept=project.concept,
        duration_label=duration_label,
        channel_name=profile.channel_name,
    )
    metadata_title = override.get("title") or profile.metadata_title_template.format(
        title=project.title,
        concept=project.concept,
        duration_label=duration_label,
        channel_name=profile.channel_name,
    )
    metadata_summary = override.get("summary") or profile.metadata_summary_template.format(
        title=project.title,
        concept=project.concept,
        duration_label=duration_label,
        channel_name=profile.channel_name,
    )

    keywords = unique_preserve(project.shared_keywords + profile.keywords)
    hashtags = unique_preserve(project.shared_hashtags + profile.hashtags)

    output_dir = project.output_root / f"{profile.order:02d}_{profile.slug}"
    video_name = "final_video.mp4"
    if is_preview:
        preview_label = int(round(duration_seconds))
        video_name = f"preview_{preview_label}s.mp4"

    return BuildJob(
        profile=profile,
        project=project,
        output_dir=output_dir,
        video_path=output_dir / video_name,
        manifest_path=output_dir / "job_manifest.json",
        metadata_json_path=output_dir / "metadata.json",
        metadata_md_path=output_dir / "youtube_metadata.md",
        overlay_title_path=output_dir / "overlay_title.txt",
        overlay_subtitle_path=output_dir / "overlay_subtitle.txt",
        duration_seconds=duration_seconds,
        duration_label=duration_label,
        overlay_title=overlay_title,
        overlay_subtitle=overlay_subtitle,
        metadata_title=metadata_title,
        metadata_summary=metadata_summary,
        keywords=keywords,
        hashtags=hashtags,
        is_preview=is_preview,
    )


def write_job_files(job: BuildJob) -> None:
    job.output_dir.mkdir(parents=True, exist_ok=True)
    job.overlay_title_path.write_text(job.overlay_title, encoding="utf-8")
    job.overlay_subtitle_path.write_text(job.overlay_subtitle, encoding="utf-8")

    payload = {
        "profile": {
            "slug": job.profile.slug,
            "order": job.profile.order,
            "channel_name": job.profile.channel_name,
            "positioning": job.profile.positioning,
            "use_case": job.profile.use_case,
        },
        "source": {
            "music": str(job.project.music_path),
            "background": str(job.project.background_path),
            "project_title": job.project.title,
            "concept": job.project.concept,
        },
        "output": {
            "directory": str(job.output_dir),
            "video": str(job.video_path),
            "metadata_json": str(job.metadata_json_path),
            "metadata_md": str(job.metadata_md_path),
        },
        "render": {
            "duration_seconds": job.duration_seconds,
            "duration_label": job.duration_label,
            "preview": job.is_preview,
            "video": {
                "width": job.project.video.width,
                "height": job.project.video.height,
                "fps": job.project.video.fps,
                "codec": job.project.video.codec,
                "preset": job.project.video.preset,
                "audio_bitrate": job.project.video.audio_bitrate,
            },
            "audio": {
                "volume": job.project.audio.volume,
                "fade_in": job.project.audio.fade_in,
                "fade_out": job.project.audio.fade_out,
            },
            "visual": asdict(job.profile.visual),
        },
        "copy": {
            "overlay_title": job.overlay_title,
            "overlay_subtitle": job.overlay_subtitle,
            "metadata_title": job.metadata_title,
            "metadata_summary": job.metadata_summary,
            "keywords": job.keywords,
            "hashtags": job.hashtags,
        },
    }

    job.manifest_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def write_build_manifest(project: ProjectConfig, jobs: list[BuildJob], dry_run: bool) -> None:
    project.output_root.mkdir(parents=True, exist_ok=True)
    payload = {
        "project_title": project.title,
        "project_file": str(project.project_file),
        "dry_run": dry_run,
        "profiles": [
            {
                "slug": job.profile.slug,
                "output_dir": str(job.output_dir),
                "video": str(job.video_path),
                "metadata": str(job.metadata_md_path),
                "preview": job.is_preview,
            }
            for job in jobs
        ],
    }
    (project.output_root / "build_manifest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
