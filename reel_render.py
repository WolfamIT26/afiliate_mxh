import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic

MAX_CLIPS = 12
RENDER_TIMEOUT_SECONDS = 180
PORTRAIT_FILTER = (
    "scale=w='max(2,trunc(min(720,1280*dar)/2)*2)'"
    ":h='max(2,trunc(min(1280,720/dar)/2)*2)',"
    "setsar=1,pad=720:1280:(ow-iw)/2:(oh-ih)/2,fps=30"
)


class ReelRenderError(RuntimeError):
    """A Reel could not be rendered."""


def run_ffmpeg(executable: str, arguments: list[str], deadline: float) -> None:
    remaining = deadline - monotonic()
    if remaining <= 0:
        raise ReelRenderError("Dựng Reel vượt quá thời gian cho phép.")
    try:
        subprocess.run(
            [executable, "-nostdin", "-hide_banner", "-loglevel", "error", *arguments],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
            timeout=remaining,
        )
    except subprocess.TimeoutExpired as error:
        raise ReelRenderError("Dựng Reel vượt quá thời gian cho phép.") from error
    except (OSError, subprocess.CalledProcessError) as error:
        raise ReelRenderError("FFmpeg không dựng được Reel từ các clip đã chọn.") from error


def render_reel(clips: Sequence[Path], output: Path) -> None:
    """Compose ordered local MP4 clips into a silent 720×1280, 30 fps MP4."""
    if not 1 <= len(clips) <= MAX_CLIPS:
        raise ReelRenderError("Cần từ 1 đến 12 clip để dựng Reel.")
    executable = shutil.which("ffmpeg")
    if executable is None:
        raise ReelRenderError("Cần cài FFmpeg trên máy chủ để dựng Reel.")

    try:
        sources = [clip.resolve() for clip in clips]
        destination = output.resolve()
        if destination in sources or any(not clip.is_file() for clip in sources):
            raise ReelRenderError("Kiểm tra các clip nguồn và đường dẫn xuất Reel.")

        deadline = monotonic() + RENDER_TIMEOUT_SECONDS
        with TemporaryDirectory(prefix=".reel-render-", dir=destination.parent) as temporary:
            workdir = Path(temporary)
            clip_names = []
            for index, source in enumerate(sources):
                name = f"clip-{index:02d}.mp4"
                run_ffmpeg(executable, [
                    "-protocol_whitelist", "file", "-f", "mov", "-threads", "2", "-i", str(source),
                    "-map", "0:V:0", "-map_metadata", "-1", "-map_chapters", "-1",
                    "-an", "-abort_on", "empty_output_stream", "-filter_threads", "2", "-vf", PORTRAIT_FILTER,
                    "-c:v", "libx264", "-threads", "2", "-preset", "veryfast",
                    "-pix_fmt", "yuv420p", str(workdir / name),
                ], deadline)
                clip_names.append(name)

            manifest = workdir / "clips.txt"
            manifest.write_text("".join(f"file '{name}'\n" for name in clip_names), encoding="ascii")
            rendered = workdir / "reel.mp4"
            run_ffmpeg(executable, [
                "-protocol_whitelist", "file", "-f", "concat", "-safe", "1", "-i", str(manifest),
                "-map", "0:v:0", "-c", "copy", "-movflags", "+faststart", str(rendered),
            ], deadline)
            rendered.replace(destination)
    except ReelRenderError:
        raise
    except (OSError, RuntimeError) as error:
        raise ReelRenderError("Không thể đọc clip nguồn hoặc lưu Reel vào vị trí đã chọn.") from error
