from __future__ import annotations

import argparse
import sys
from pathlib import Path

from focus_music_video.ffmpeg_tools import probe_duration, render_video
from focus_music_video.interactive_production import run_interactive_production
from focus_music_video.metadata import write_metadata
from focus_music_video.mix_builder import build_audio_mix
from focus_music_video.mix_video_renderer import render_mix_video
from focus_music_video.pipeline import build_job, write_build_manifest, write_job_files
from focus_music_video.profiles import list_profiles, load_profiles
from focus_music_video.production_pipeline import build_final_package
from focus_music_video.production_cleanup import cleanup_production_folder
from focus_music_video.project import load_project, scaffold_project
from focus_music_video.youtube_copy import generate_youtube_copy


def _tool_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build one shared focus music source into four channel-specific video outputs."
    )
    subparsers = parser.add_subparsers(dest="command")

    interactive_parser = subparsers.add_parser(
        "interactive-production",
        help="Open the end-to-end production wizard: audio ingest, mix, video render, and title/description",
    )

    subparsers.add_parser("list-profiles", help="List the built-in channel profiles")

    init_parser = subparsers.add_parser("init-project", help="Scaffold a new focus music project")
    init_parser.add_argument("--name", required=True, help="Project folder name")
    init_parser.add_argument("--title", help="Project display title")
    init_parser.add_argument(
        "--root",
        default=str(_tool_root() / "projects"),
        help="Directory where project folders should be created",
    )

    build_parser = subparsers.add_parser("build", help="Build manifests, metadata and videos")
    build_parser.add_argument("--project", required=True, help="Path to project.json")
    build_parser.add_argument(
        "--profile",
        action="append",
        help="Build only one or more specific profiles",
    )
    build_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate manifests and metadata without rendering video",
    )
    build_parser.add_argument(
        "--preview-seconds",
        type=float,
        help="Render only the first N seconds and write a preview_<N>s.mp4 file",
    )

    mix_parser = subparsers.add_parser(
        "build-mix",
        help="Concatenate crawled dataset audio into one long mix and write tracklist + credits",
    )
    mix_parser.add_argument("--source", required=True, help="Internal source/channel name")
    mix_parser.add_argument(
        "--name",
        default="first_video",
        help="Output mix folder name",
    )
    mix_parser.add_argument(
        "--config",
        default=str(_tool_root() / "audio_dataset" / "config" / "youtube_channels.json"),
        help="Path to audio dataset source config JSON",
    )
    mix_parser.add_argument(
        "--dataset-root",
        default=str(_tool_root() / "audio_dataset" / "dataset"),
        help="Root directory of the crawled audio dataset",
    )
    mix_parser.add_argument(
        "--output-root",
        default=str(_tool_root() / "productions"),
        help="Root directory where mix outputs should be written",
    )
    mix_parser.add_argument(
        "--audio-bitrate",
        default="192k",
        help="AAC bitrate for the merged mix output",
    )

    render_mix_parser = subparsers.add_parser(
        "render-mix-video",
        help="Render one final MP4 from a built mix using a looping background, countdown and audio bar",
    )
    render_mix_parser.add_argument("--source", required=True, help="Internal source/channel name")
    render_mix_parser.add_argument(
        "--name",
        default="first_video",
        help="Mix folder name under productions/<source>",
    )
    render_mix_parser.add_argument(
        "--background",
        required=True,
        help="Path to the background image or video file",
    )
    render_mix_parser.add_argument(
        "--output-root",
        default=str(_tool_root() / "productions"),
        help="Root directory where mix outputs are written",
    )
    render_mix_parser.add_argument(
        "--preview-seconds",
        type=float,
        help="Render only the first N seconds for layout checks",
    )
    render_mix_parser.add_argument(
        "--codec",
        default="h264_nvenc",
        help="Video codec, e.g. h264_nvenc, hevc_nvenc, libx264",
    )
    render_mix_parser.add_argument(
        "--preset",
        default="p1",
        help="Encoder preset",
    )
    render_mix_parser.add_argument(
        "--cq",
        type=int,
        default=23,
        help="CQ/CRF-like quality value for the selected video codec",
    )
    render_mix_parser.add_argument(
        "--width",
        type=int,
        default=1920,
        help="Output video width",
    )
    render_mix_parser.add_argument(
        "--height",
        type=int,
        default=1080,
        help="Output video height",
    )
    render_mix_parser.add_argument(
        "--fps",
        type=int,
        default=30,
        help="Output frames per second",
    )
    render_mix_parser.add_argument(
        "--background-codec",
        default="libx264",
        help="Codec for the prepared background video",
    )
    render_mix_parser.add_argument(
        "--background-preset",
        default="slow",
        help="Preset for the prepared background video",
    )
    render_mix_parser.add_argument(
        "--background-quality",
        type=int,
        default=14,
        help="CRF/CQ-like quality for the prepared background video",
    )
    render_mix_parser.add_argument(
        "--disable-countdown",
        action="store_true",
        help="Render without the countdown timer overlay",
    )
    render_mix_parser.add_argument(
        "--disable-visualizer",
        action="store_true",
        help="Render without the audio bar visualizer overlay",
    )

    youtube_copy_parser = subparsers.add_parser(
        "generate-youtube-copy",
        help="Generate title candidates, final description, hashtags, and an LLM prompt package for a built mix",
    )
    youtube_copy_parser.add_argument("--source", required=True, help="Internal source/channel name")
    youtube_copy_parser.add_argument(
        "--name",
        default="first_video",
        help="Mix folder name under productions/<source>",
    )
    youtube_copy_parser.add_argument(
        "--config",
        default=str(_tool_root() / "audio_dataset" / "config" / "youtube_channels.json"),
        help="Path to audio dataset source config JSON",
    )
    youtube_copy_parser.add_argument(
        "--output-root",
        default=str(_tool_root() / "productions"),
        help="Root directory where mix outputs are written",
    )
    youtube_copy_parser.add_argument(
        "--scene-label",
        help="Optional custom scene label for the metadata package, e.g. Quiet Lake",
    )
    youtube_copy_parser.add_argument(
        "--model",
        help="OpenRouter model name for the final metadata generation step. Defaults to OPENROUTER_MODEL or google/gemini-2.5-flash.",
    )

    cleanup_parser = subparsers.add_parser(
        "cleanup-production",
        help="Remove preview/intermediate artifacts and keep the production folder tidy",
    )
    cleanup_parser.add_argument("--source", required=True, help="Internal source/channel name")
    cleanup_parser.add_argument(
        "--name",
        default="first_video",
        help="Mix folder name under productions/<source>",
    )
    cleanup_parser.add_argument(
        "--output-root",
        default=str(_tool_root() / "productions"),
        help="Root directory where mix outputs are written",
    )
    cleanup_parser.add_argument(
        "--aggressive",
        action="store_true",
        help="Also remove secondary metadata files like tracklist and music credits, keeping only core artifacts",
    )

    package_parser = subparsers.add_parser(
        "build-final-package",
        help="Run the full production pipeline: build mix, render MP4, generate YouTube title/description, and optionally cleanup",
    )
    package_parser.add_argument("--source", required=True, help="Internal source/channel name")
    package_parser.add_argument(
        "--name",
        default="first_video",
        help="Mix folder name under productions/<source>",
    )
    package_parser.add_argument(
        "--background",
        required=True,
        help="Path to the background image or video file",
    )
    package_parser.add_argument(
        "--config",
        default=str(_tool_root() / "audio_dataset" / "config" / "youtube_channels.json"),
        help="Path to audio dataset source config JSON",
    )
    package_parser.add_argument(
        "--dataset-root",
        default=str(_tool_root() / "audio_dataset" / "dataset"),
        help="Root directory of the crawled audio dataset",
    )
    package_parser.add_argument(
        "--output-root",
        default=str(_tool_root() / "productions"),
        help="Root directory where production outputs should be written",
    )
    package_parser.add_argument(
        "--audio-bitrate",
        default="192k",
        help="AAC bitrate for the merged mix output",
    )
    package_parser.add_argument(
        "--scene-label",
        help="Optional custom scene label for the YouTube metadata step, e.g. Quiet Lake",
    )
    package_parser.add_argument(
        "--model",
        help="OpenRouter model name for the YouTube title/description generation step",
    )
    package_parser.add_argument(
        "--preview-seconds",
        type=float,
        help="Render only the first N seconds for layout checks",
    )
    package_parser.add_argument(
        "--codec",
        default="h264_nvenc",
        help="Video codec, e.g. h264_nvenc, hevc_nvenc, libx264",
    )
    package_parser.add_argument(
        "--preset",
        default="p1",
        help="Encoder preset",
    )
    package_parser.add_argument(
        "--cq",
        type=int,
        default=23,
        help="CQ/CRF-like quality value for the selected video codec",
    )
    package_parser.add_argument(
        "--width",
        type=int,
        default=1920,
        help="Output video width",
    )
    package_parser.add_argument(
        "--height",
        type=int,
        default=1080,
        help="Output video height",
    )
    package_parser.add_argument(
        "--fps",
        type=int,
        default=30,
        help="Output frames per second",
    )
    package_parser.add_argument(
        "--background-codec",
        default="libx264",
        help="Codec for the prepared background video",
    )
    package_parser.add_argument(
        "--background-preset",
        default="slow",
        help="Preset for the prepared background video",
    )
    package_parser.add_argument(
        "--background-quality",
        type=int,
        default=14,
        help="CRF/CQ-like quality for the prepared background video",
    )
    package_parser.add_argument(
        "--disable-countdown",
        action="store_true",
        help="Render without the countdown timer overlay",
    )
    package_parser.add_argument(
        "--disable-visualizer",
        action="store_true",
        help="Render without the audio bar visualizer overlay",
    )
    package_parser.add_argument(
        "--skip-youtube-copy",
        action="store_true",
        help="Skip the LLM title/description generation step",
    )
    package_parser.add_argument(
        "--cleanup",
        action="store_true",
        help="Remove preview/intermediate artifacts after the full pipeline finishes",
    )
    package_parser.add_argument(
        "--aggressive-cleanup",
        action="store_true",
        help="Also remove secondary metadata files like tracklist and music credits",
    )

    return parser


def _command_list_profiles() -> int:
    for profile in list_profiles():
        print(f"[{profile.order}] {profile.slug}")
        print(f"  Channel: {profile.channel_name}")
        print(f"  Positioning: {profile.positioning}")
    return 0


def _command_interactive_production() -> int:
    run_interactive_production(_tool_root())
    return 0


def _command_init_project(args: argparse.Namespace) -> int:
    project_dir = scaffold_project(args.root, args.name, args.title)
    print(f"[OK] Project scaffolded at: {project_dir}")
    print(f"[NEXT] Put assets into: {project_dir / 'input'}")
    print(f"[NEXT] Build with: python run.py build --project \"{project_dir / 'project.json'}\"")
    return 0


def _command_build(args: argparse.Namespace) -> int:
    project = load_project(args.project)

    required_paths = {
        "music": project.music_path,
        "background": project.background_path,
    }
    for label, path in required_paths.items():
        if not path.exists():
            raise FileNotFoundError(f"Missing {label} file: {path}")

    profile_slugs = args.profile or project.profiles
    profiles = load_profiles(profile_slugs)
    source_duration_seconds = probe_duration(project.music_path)

    jobs = [
        build_job(
            project=project,
            profile=profile,
            source_duration_seconds=source_duration_seconds,
            preview_seconds=args.preview_seconds,
        )
        for profile in profiles
    ]

    for job in jobs:
        write_job_files(job)
        write_metadata(job)
        if not args.dry_run:
            render_video(job)
        print(f"[OK] {job.profile.slug}: {job.video_path}")

    write_build_manifest(project, jobs, dry_run=args.dry_run)
    print(f"[OK] Build manifest: {project.output_root / 'build_manifest.json'}")
    return 0


def _command_build_mix(args: argparse.Namespace) -> int:
    result = build_audio_mix(
        source_name=args.source,
        mix_name=args.name,
        config_path=args.config,
        dataset_root=args.dataset_root,
        output_root=args.output_root,
        audio_bitrate=args.audio_bitrate,
    )
    print(f"[OK] Mix audio: {result.audio_path}")
    print(f"[OK] Tracklist: {result.tracklist_path}")
    print(f"[OK] Music credits: {result.credits_path}")
    print(f"[OK] Manifest: {result.manifest_path}")
    if result.skipped_items:
        print(f"[WARN] Skipped {len(result.skipped_items)} uncrawled or incomplete items")
    return 0


def _command_render_mix_video(args: argparse.Namespace) -> int:
    result = render_mix_video(
        source_name=args.source,
        mix_name=args.name,
        background_path=args.background,
        output_root=args.output_root,
        preview_seconds=args.preview_seconds,
        codec=args.codec,
        preset=args.preset,
        cq=args.cq,
        width=args.width,
        height=args.height,
        fps=args.fps,
        background_codec=args.background_codec,
        background_preset=args.background_preset,
        background_quality=args.background_quality,
        show_countdown=not args.disable_countdown,
        show_visualizer=not args.disable_visualizer,
    )
    print(f"[OK] Prepared background: {result.prepared_background_path}")
    print(f"[OK] Visualizer overlay: {result.visualizer_path}")
    print(f"[OK] Final video: {result.video_path}")
    return 0


def _command_generate_youtube_copy(args: argparse.Namespace) -> int:
    result = generate_youtube_copy(
        source_name=args.source,
        mix_name=args.name,
        config_path=args.config,
        output_root=args.output_root,
        scene_label=args.scene_label,
        model=args.model,
    )
    print(f"[OK] Title + Description: {result.title_description_path}")
    return 0


def _command_cleanup_production(args: argparse.Namespace) -> int:
    result = cleanup_production_folder(
        source_name=args.source,
        mix_name=args.name,
        output_root=args.output_root,
        aggressive=args.aggressive,
    )
    print(f"[OK] Removed {len(result.removed_paths)} files")
    for path in result.removed_paths:
        print(f"  - {path}")
    return 0


def _command_build_final_package(args: argparse.Namespace) -> int:
    result = build_final_package(
        source_name=args.source,
        mix_name=args.name,
        background_path=args.background,
        config_path=args.config,
        dataset_root=args.dataset_root,
        output_root=args.output_root,
        audio_bitrate=args.audio_bitrate,
        scene_label=args.scene_label,
        model=args.model,
        preview_seconds=args.preview_seconds,
        codec=args.codec,
        preset=args.preset,
        cq=args.cq,
        width=args.width,
        height=args.height,
        fps=args.fps,
        background_codec=args.background_codec,
        background_preset=args.background_preset,
        background_quality=args.background_quality,
        show_countdown=not args.disable_countdown,
        show_visualizer=not args.disable_visualizer,
        skip_youtube_copy=args.skip_youtube_copy,
        cleanup=args.cleanup,
        aggressive_cleanup=args.aggressive_cleanup,
    )
    print(f"[OK] Mix audio: {result.mix_result.audio_path}")
    print(f"[OK] Final video: {result.final_video_path}")
    if result.mix_result.skipped_items:
        print(f"[WARN] Skipped {len(result.mix_result.skipped_items)} uncrawled or incomplete items")
    if result.title_description_path:
        print(f"[OK] Title + Description: {result.title_description_path}")
    if result.cleanup_result:
        print(f"[OK] Removed {len(result.cleanup_result.removed_paths)} intermediate files")
    return 0


def main(argv: list[str] | None = None) -> int:
    if argv is None and len(sys.argv) == 1:
        return _command_interactive_production()

    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "interactive-production":
        return _command_interactive_production()
    if args.command == "list-profiles":
        return _command_list_profiles()
    if args.command == "init-project":
        return _command_init_project(args)
    if args.command == "build":
        return _command_build(args)
    if args.command == "build-mix":
        return _command_build_mix(args)
    if args.command == "render-mix-video":
        return _command_render_mix_video(args)
    if args.command == "generate-youtube-copy":
        return _command_generate_youtube_copy(args)
    if args.command == "cleanup-production":
        return _command_cleanup_production(args)
    if args.command == "build-final-package":
        return _command_build_final_package(args)

    parser.print_help()
    return 1
