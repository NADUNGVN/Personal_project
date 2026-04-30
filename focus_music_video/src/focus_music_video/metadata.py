from __future__ import annotations

import json

from focus_music_video.models import BuildJob


def build_metadata_payload(job: BuildJob) -> dict:
    description_lines: list[str] = [
        job.metadata_summary,
        "",
        f"Channel angle: {job.profile.channel_name}",
        f"Positioning: {job.profile.positioning}",
        f"Use case: {job.profile.use_case}",
        f"Duration: {job.duration_label}",
    ]

    if job.project.shared_description_lines:
        description_lines.append("")
        description_lines.extend(job.project.shared_description_lines)

    description_lines.extend(
        [
            "",
            "Keywords:",
            ", ".join(job.keywords),
            "",
            "Hashtags:",
            " ".join(job.hashtags),
        ]
    )

    return {
        "title": job.metadata_title,
        "summary": job.metadata_summary,
        "description": "\n".join(description_lines),
        "channel_name": job.profile.channel_name,
        "positioning": job.profile.positioning,
        "use_case": job.profile.use_case,
        "duration_seconds": job.duration_seconds,
        "duration_label": job.duration_label,
        "keywords": job.keywords,
        "hashtags": job.hashtags,
        "overlay_title": job.overlay_title,
        "overlay_subtitle": job.overlay_subtitle,
    }


def write_metadata(job: BuildJob) -> None:
    payload = build_metadata_payload(job)
    job.metadata_json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    md_lines = [
        f"Title: {payload['title']}",
        "",
        "Summary:",
        payload["summary"],
        "",
        "Description:",
        payload["description"],
        "",
        "Overlay Title:",
        payload["overlay_title"],
        "",
        "Overlay Subtitle:",
        payload["overlay_subtitle"],
        "",
        "Keywords:",
        ", ".join(payload["keywords"]),
        "",
        "Hashtags:",
        " ".join(payload["hashtags"]),
    ]
    job.metadata_md_path.write_text("\n".join(md_lines), encoding="utf-8")
