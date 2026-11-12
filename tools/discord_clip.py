"""Shrink a recording so it fits a Discord upload limit (50 MB by default: boost level 2+ servers).

  python discord_clip.py "recording.mp4"
  python discord_clip.py clip.mp4 --size 50            # Nitro Basic limit
  python discord_clip.py clip.mp4 --start 1:05 --end 2:10   # just the drop
  python discord_clip.py clip.mp4 --crop auto          # cut away black bars (e.g. ultrawide in a 16:9 canvas)

Two-pass H.264 at the exact bitrate that fits, so the file lands just under the limit. The resolution
and frame rate drop automatically when the bitrate is low (blocky 1080p looks worse than clean 720p).
Writes "<name> (discord).mp4" next to the original.
"""
import argparse
import os
import subprocess
import sys
import tempfile


def seconds(text):
    """'95', '1:35' or '0:01:35.5' -> seconds."""
    if text is None:
        return None
    total = 0.0
    for part in str(text).split(":"):
        total = total * 60 + float(part)
    return total


def probe_duration(path):
    output = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                            capture_output=True, text=True, check=True).stdout
    return float(output.strip())


def detect_crop(path, start, duration):
    """ffmpeg cropdetect over a stretch of the video -> 'w:h:x:y' of the picture without black bars."""
    probe_from = start + min(30.0, duration / 3)
    result = subprocess.run(["ffmpeg", "-hide_banner", "-ss", str(probe_from), "-t", "20", "-i", path,
                             "-vf", "cropdetect=limit=24:round=2:reset=0", "-f", "null", "-"],
                            capture_output=True, text=True)
    found = [line.split("crop=")[-1].strip() for line in result.stderr.splitlines() if "crop=" in line]
    return found[-1] if found else None


def pick_video_settings(video_kbps):
    """(height, fps) that look best at this bitrate."""
    if video_kbps >= 4500:
        return 1080, 60
    if video_kbps >= 2500:
        return 1080, 30
    if video_kbps >= 1400:
        return 720, 30
    if video_kbps >= 700:
        return 540, 30
    return 480, 30


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("video")
    parser.add_argument("--size", type=float, default=50.0, help="target size in MB (Discord free: 10, server boost level 2: 50, level 3: 100)")
    parser.add_argument("--start", help="start time, e.g. 1:05")
    parser.add_argument("--end", help="end time, e.g. 2:10")
    parser.add_argument("--crop", help="'auto' to remove black bars, or w:h:x:y")
    parser.add_argument("--suffix", default="discord", help="added to the output name")
    args = parser.parse_args()

    source = os.path.abspath(args.video)
    start, end = seconds(args.start) or 0.0, seconds(args.end)
    duration = (end or probe_duration(source)) - start
    if duration <= 0:
        sys.exit("end must be after start")

    budget_kbits = args.size * 0.95 * 8 * 1000          # 5% headroom for the MP4 container
    audio_kbps = 96 if budget_kbits / duration > 900 else 64
    video_kbps = int(budget_kbits / duration - audio_kbps)
    if video_kbps < 150:
        sys.exit(f"{duration:.0f} s is too long for {args.size:g} MB - trim it with --start/--end or raise --size")
    height, fps = pick_video_settings(video_kbps)
    crop = detect_crop(source, start, duration) if args.crop == "auto" else args.crop
    if crop:
        crop_width, crop_height = (int(value) for value in crop.split(":")[:2])
        # same pixel count as a 16:9 frame of that height, so wide crops don't get starved of bitrate
        aspect = crop_width / crop_height
        height = min(crop_height, int(round(height * (16 / 9 / aspect) ** 0.5 / 2) * 2))
        print(f"cropping to {crop}")
    print(f"{duration:.0f} s -> {height}p{fps}, video {video_kbps} kbps + audio {audio_kbps} kbps (target {args.size:g} MB)")

    base, _ = os.path.splitext(source)
    output = f"{base} ({args.suffix}).mp4"
    trim = (["-ss", str(start)] if start else []) + (["-t", str(duration)] if end else [])
    video_filter = (f"crop={crop}," if crop else "") + f"scale=-2:{height}:flags=lanczos,fps={fps}"
    common = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-stats", "-y", *trim, "-i", source,
              "-vf", video_filter, "-c:v", "libx264", "-preset", "slow", "-b:v", f"{video_kbps}k",
              "-pix_fmt", "yuv420p"]
    with tempfile.TemporaryDirectory() as work:
        log_prefix = os.path.join(work, "pass")
        print("pass 1/2...")
        subprocess.run(common + ["-pass", "1", "-passlogfile", log_prefix, "-an", "-f", "mp4", os.devnull], check=True)
        print("pass 2/2...")
        subprocess.run(common + ["-pass", "2", "-passlogfile", log_prefix, "-c:a", "aac", "-b:a", f"{audio_kbps}k",
                                 "-movflags", "+faststart", output], check=True)
    size_mb = os.path.getsize(output) / 1e6
    print(f"done: {output} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
