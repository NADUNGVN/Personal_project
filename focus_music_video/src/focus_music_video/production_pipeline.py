from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from focus_music_video.mix_builder import MixBuildResult, build_audio_mix
from focus_music_video.mix_video_renderer import MixVideoRenderResult, render_mix_video
from focus_music_video.production_cleanup import CleanupResult, cleanup_production_folder
from focus_music_video.youtube_copy import YoutubeCopyResult, generate_youtube_copy


@dataclass(slots=True)
class FinalPackageResult:
    mix_result: MixBuildResult
    render_result: MixVideoRenderResult
    youtube_copy_result: YoutubeCopyResult | None
    cleanup_result: CleanupResult | None

    @property
    def final_video_path(self) -> Path:
        return self.render_result.video_path

    @property
    def title_description_path(self) -> Path | None:
        if not self.youtube_copy_result:
            return None
        return self.youtube_copy_result.title_description_path


def build_final_package(
    *,
    source_name: str,
    mix_name: str,
    background_path: str | Path,
    config_path: str | Path,
    dataset_root: str | Path,
    output_root: str | Path,
    audio_bitrate: str = "192k",
    selected_urls: list[str] | None = None,
    scene_label: str | None = None,
    model: str | None = None,
    preview_seconds: float | None = None,
    codec: str = "h264_nvenc",
    preset: str = "p1",
    cq: int = 23,
    width: int = 1920,
    height: int = 1080,
    fps: int = 30,
    background_codec: str = "libx264",
    background_preset: str = "slow",
    background_quality: int = 14,
    show_countdown: bool = True,
    show_visualizer: bool = True,
    skip_youtube_copy: bool = False,
    cleanup: bool = False,
    aggressive_cleanup: bool = False,
) -> FinalPackageResult:
    mix_result = build_audio_mix(
        source_name=source_name,
        mix_name=mix_name,
        config_path=config_path,
        dataset_root=dataset_root,
        output_root=output_root,
        audio_bitrate=audio_bitrate,
        selected_urls=selected_urls,
    )

    render_result = render_mix_video(
        source_name=source_name,
        mix_name=mix_name,
        background_path=background_path,
        output_root=output_root,
        preview_seconds=preview_seconds,
        codec=codec,
        preset=preset,
        cq=cq,
        width=width,
        height=height,
        fps=fps,
        background_codec=background_codec,
        background_preset=background_preset,
        background_quality=background_quality,
        show_countdown=show_countdown,
        show_visualizer=show_visualizer,
    )

    youtube_copy_result: YoutubeCopyResult | None = None
    if not skip_youtube_copy:
        youtube_copy_result = generate_youtube_copy(
            source_name=source_name,
            mix_name=mix_name,
            config_path=config_path,
            output_root=output_root,
            scene_label=scene_label,
            model=model,
        )

    cleanup_result: CleanupResult | None = None
    should_cleanup = cleanup or aggressive_cleanup
    if should_cleanup:
        cleanup_result = cleanup_production_folder(
            source_name=source_name,
            mix_name=mix_name,
            output_root=output_root,
            aggressive=aggressive_cleanup,
        )

    return FinalPackageResult(
        mix_result=mix_result,
        render_result=render_result,
        youtube_copy_result=youtube_copy_result,
        cleanup_result=cleanup_result,
    )
