#!/usr/bin/env python3
"""
video-to-markdown — AI-powered video analysis for OpenClaw / clawhub
Combines frame extraction + transcription → Claude vision → Markdown

Usage:
    python video_analyzer.py "<URL>" [--output ./output] [options]

Requirements:
    System: ffmpeg, yt-dlp
    Python: anthropic, Pillow, faster-whisper (optional)
    Env:    ANTHROPIC_API_KEY
"""

import sys
import os
import argparse
import base64
import subprocess
import tempfile
import re
import json
from pathlib import Path
from datetime import datetime


# ─── Platform Detection ───────────────────────────────────────────────────────

def detect_platform(url: str) -> str:
    url_lower = url.lower()
    if "youtube.com" in url_lower or "youtu.be" in url_lower:
        return "youtube"
    elif "facebook.com" in url_lower or "fb.watch" in url_lower or "fb.com" in url_lower:
        return "facebook"
    elif "instagram.com" in url_lower:
        return "instagram"
    return "unknown"


# ─── Transcript / Caption Handling ───────────────────────────────────────────

def parse_vtt(vtt_path: Path) -> str:
    """Parse WebVTT captions into plain timestamped text."""
    with open(vtt_path, encoding="utf-8", errors="replace") as f:
        content = f.read()

    # Strip WEBVTT header and STYLE blocks
    content = re.sub(r"WEBVTT[^\n]*\n", "", content)
    content = re.sub(r"STYLE\b.*?\n\n", "", content, flags=re.DOTALL)

    cue_pattern = re.compile(
        r"(\d{2}:\d{2}:\d{2}\.\d{3})\s*-->\s*\d{2}:\d{2}:\d{2}\.\d{3}[^\n]*\n"
        r"((?:(?!\n\n).)+)",
        re.DOTALL,
    )
    lines = []
    for m in cue_pattern.finditer(content):
        ts = m.group(1)
        text = re.sub(r"<[^>]+>", "", m.group(2)).strip()
        noise = {"[Music]", "[Applause]", "[Laughter]", ""}
        if text not in noise:
            lines.append(f"[{ts}] {text}")

    # Deduplicate adjacent duplicates (YouTube auto-cap quirk)
    deduped, prev = [], None
    for line in lines:
        if line != prev:
            deduped.append(line)
        prev = line

    return "\n".join(deduped)


def get_transcript_captions(url: str, platform: str, work_dir: Path, cookies: str | None) -> tuple[str | None, str]:
    """Try platform captions first. Returns (transcript | None, video_title)."""
    cmd = [
        "yt-dlp",
        "--write-info-json",
        "--write-subs", "--write-auto-subs",
        "--sub-langs", "en,en-orig,en-US",
        "--sub-format", "vtt",
        "--skip-download",
        "--output", str(work_dir / "video"),
        url,
    ]
    if cookies:
        cmd += ["--cookies", cookies]
    if platform == "facebook":
        cmd += ["--impersonate", "Chrome-99"]

    subprocess.run(cmd, capture_output=True, text=True)

    title = "Untitled Video"
    info_file = work_dir / "video.info.json"
    if info_file.exists():
        try:
            title = json.loads(info_file.read_text(encoding="utf-8")).get("title", title)
        except Exception:
            pass

    vtt_files = sorted(work_dir.glob("*.vtt"))
    return (parse_vtt(vtt_files[0]) if vtt_files else None), title


def get_transcript_whisper(url: str, platform: str, work_dir: Path, cookies: str | None, model_size: str = "base") -> str | None:
    """Download audio and transcribe with faster-whisper."""
    audio_path = work_dir / "audio.mp3"
    cmd = [
        "yt-dlp", "-f", "bestaudio",
        "--extract-audio", "--audio-format", "mp3",
        "--output", str(audio_path), url,
    ]
    if cookies:
        cmd += ["--cookies", cookies]
    if platform == "facebook":
        cmd += ["--impersonate", "Chrome-99"]

    subprocess.run(cmd, capture_output=True, text=True)

    if not audio_path.exists():
        print("[warn] Audio download failed — skipping Whisper.", file=sys.stderr)
        return None

    try:
        from faster_whisper import WhisperModel
        m = WhisperModel(model_size, device="cpu", compute_type="int8")
        segments, _ = m.transcribe(str(audio_path), beam_size=5)
        lines = []
        for seg in segments:
            mm, ss = divmod(int(seg.start), 60)
            lines.append(f"[{mm:02d}:{ss:02d}] {seg.text.strip()}")
        return "\n".join(lines)
    except ImportError:
        print("[warn] faster-whisper not installed; skipping Whisper.", file=sys.stderr)
        return None
    except Exception as e:
        print(f"[warn] Whisper failed: {e}", file=sys.stderr)
        return None


# ─── Frame Extraction ─────────────────────────────────────────────────────────

def download_video(url: str, platform: str, work_dir: Path, cookies: str | None) -> Path | None:
    """Download video file for frame extraction."""
    video_path = work_dir / "video.mp4"
    cmd = [
        "yt-dlp",
        "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "--output", str(video_path), url,
    ]
    if cookies:
        cmd += ["--cookies", cookies]
    if platform == "facebook":
        cmd += ["--impersonate", "Chrome-99"]

    subprocess.run(cmd, capture_output=True, text=True)

    if video_path.exists():
        return video_path
    candidates = [p for p in work_dir.glob("video.*") if p.suffix not in (".json", ".vtt")]
    return candidates[0] if candidates else None


def extract_frames(video_path: Path, frames_dir: Path, max_frames: int = 50) -> list[Path]:
    """
    Extract frames using scene-change detection with a 2s minimum interval guard.
    Falls back to 1-per-15s fixed sampling if scene detection yields fewer than 5 frames.
    Caps result to max_frames by even sampling.
    """
    frames_dir.mkdir(exist_ok=True)

    # Scene-detection pass
    filter_expr = "select='gt(scene\\,0.25)*gte(t-prev_selected_t\\,2)',setpts=N/FRAME_RATE/TB"
    subprocess.run(
        ["ffmpeg", "-i", str(video_path), "-vf", filter_expr,
         "-vsync", "vfr", "-q:v", "2",
         str(frames_dir / "frame_%04d.jpg"), "-y", "-loglevel", "error"],
        capture_output=True,
    )

    frames = sorted(frames_dir.glob("frame_*.jpg"))

    # Fallback: fixed 1-per-15s
    if len(frames) < 5:
        for f in frames:
            f.unlink()
        subprocess.run(
            ["ffmpeg", "-i", str(video_path), "-vf", "fps=1/15",
             str(frames_dir / "frame_%04d.jpg"), "-y", "-loglevel", "error"],
            capture_output=True,
        )
        frames = sorted(frames_dir.glob("frame_*.jpg"))

    # Cap to max_frames
    if len(frames) > max_frames:
        step = len(frames) / max_frames
        frames = [frames[int(i * step)] for i in range(max_frames)]

    return frames


def resize_frame(frame_path: Path, max_long_edge: int = 1092) -> bytes:
    """
    Resize frame to stay within Claude Sonnet vision token ceiling (~1568 tokens).
    Returns JPEG bytes. Falls back to raw bytes if Pillow is unavailable.
    """
    try:
        from PIL import Image
        import io
        img = Image.open(frame_path).convert("RGB")
        w, h = img.size
        long_edge = max(w, h)
        if long_edge > max_long_edge:
            r = max_long_edge / long_edge
            img = img.resize((int(w * r), int(h * r)), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        return buf.getvalue()
    except ImportError:
        return frame_path.read_bytes()


# ─── Claude Vision Analysis ───────────────────────────────────────────────────

ANALYSIS_PROMPT = """\
You are building a Markdown reference document from a video.

You have {n_frames} frames extracted at scene-change points throughout the video, \
plus the full transcript below (when available). Each frame is labeled with its \
sequence number so you can correlate visuals to the transcript timeline.

Generate a thorough, well-structured Markdown document using this format:

---

# {title}

## Overview
What this video is about (2-3 sentences). Key topics. What someone learns from it.

## Visual Content Summary
A description of what appears on screen throughout the video — charts, diagrams, \
slides, code, demonstrations, data. Be specific: label names on axes, price levels \
visible, indicator settings, slide titles, tool names, data values shown.

## Section Breakdown
For each major topic or section, describe:
- **Said**: what the narrator explained
- **Shown**: what appeared on screen at that point
- **Why it matters**: significance to the overall topic

Use timestamps from the transcript to anchor sections where possible.

## Key Visuals Explained
For every significant chart, diagram, slide, or visual element:
- What exactly it shows (be specific — values, labels, patterns)
- What it means or why it's there
- Whether the narration explained it, or left it to the viewer

## Key Takeaways
Main lessons, strategies, insights, or actionable points.

## Terms & Concepts
Domain-specific terms, ticker symbols, indicators, tools, or concepts introduced. \
Brief definition for each.

## Visual–Narration Gaps
Anything clearly shown on screen that was NOT fully explained verbally. \
This section is the whole point for chart-heavy and technical content — \
surface anything the viewer would have missed by only reading a transcript.

---

Rules:
- If the transcript is missing or incomplete, extract as much as possible from the frames alone.
- Be specific about visual details — vague descriptions ("a chart") are not useful.
- Preserve technical precision; don't paraphrase jargon.
- Write in clear, direct prose. No filler.
"""


def analyze_with_claude(
    frames: list[Path],
    transcript: str | None,
    title: str,
    api_key: str,
    model: str = "claude-sonnet-4-6",
) -> str:
    """Send frames + transcript to Claude API for multimodal synthesis."""
    try:
        import anthropic
    except ImportError:
        sys.exit("[error] 'anthropic' package not installed. Run: pip install anthropic")

    client = anthropic.Anthropic(api_key=api_key)
    content = []

    for i, fp in enumerate(frames):
        img_data = base64.b64encode(resize_frame(fp)).decode()
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg", "data": img_data},
        })
        content.append({"type": "text", "text": f"[Frame {i + 1}/{len(frames)}]"})

    content.append({
        "type": "text",
        "text": f"\nTRANSCRIPT:\n{transcript}" if transcript
                else "\n[No transcript available — analysis from frames only]",
    })
    content.append({
        "type": "text",
        "text": ANALYSIS_PROMPT.format(n_frames=len(frames), title=title),
    })

    response = client.messages.create(
        model=model,
        max_tokens=4096,
        messages=[{"role": "user", "content": content}],
    )
    return response.content[0].text


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Analyze a video URL → comprehensive Markdown reference document.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python video_analyzer.py "https://youtu.be/abc123"
  python video_analyzer.py "https://youtu.be/abc123" --max-frames 30 --output ./notes
  python video_analyzer.py "https://fb.watch/xyz" --cookies cookies.txt
  python video_analyzer.py "https://youtu.be/abc123" --whisper --whisper-model large-v3
        """,
    )
    parser.add_argument("url", help="Video URL (YouTube, Facebook, or Instagram)")
    parser.add_argument("--output", "-o", default=".", help="Output directory (default: current dir)")
    parser.add_argument("--max-frames", type=int, default=50, help="Max frames to sample (default: 50)")
    parser.add_argument("--cookies", help="Path to cookies.txt (required for FB/IG, sometimes YouTube)")
    parser.add_argument("--whisper", action="store_true", help="Force Whisper transcription instead of platform captions")
    parser.add_argument(
        "--whisper-model", default="base",
        choices=["tiny", "base", "small", "medium", "large-v3"],
        help="Whisper model size (default: base; large-v3 for best accuracy)",
    )
    parser.add_argument(
        "--model", default="claude-sonnet-4-6",
        help="Claude model to use (default: claude-sonnet-4-6)",
    )
    args = parser.parse_args()

    # ── Preflight ──
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        sys.exit("[error] ANTHROPIC_API_KEY not set. Export it before running.")

    for tool, ver_flag, install_hint in [
        # ffmpeg exits non-zero for `--version` (it wants `-version`); yt-dlp accepts `--version`
        ("ffmpeg", "-version", "brew install ffmpeg  /  sudo apt install ffmpeg  /  https://ffmpeg.org/download.html"),
        ("yt-dlp", "--version", "pip install yt-dlp"),
    ]:
        try:
            r = subprocess.run([tool, ver_flag], capture_output=True, timeout=20)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            sys.exit(f"[error] '{tool}' not found or timed out. Install: {install_hint}")
        if r.returncode != 0:
            sys.exit(f"[error] '{tool}' check failed (exit {r.returncode}). Install: {install_hint}")

    platform = detect_platform(args.url)
    print(f"[info] Platform: {platform}")

    if platform == "unknown":
        print("[warn] Unrecognized platform — attempting download anyway.", file=sys.stderr)

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="vtm_") as tmp:
        work_dir = Path(tmp)

        # ── Transcript ──
        transcript, title = None, "Untitled Video"

        if not args.whisper:
            print("[info] Fetching captions...")
            transcript, title = get_transcript_captions(args.url, platform, work_dir, args.cookies)
            if transcript:
                print(f"[info] Captions: {len(transcript.split())} words")
            else:
                print("[info] No captions found — falling back to Whisper...")

        if transcript is None:
            transcript = get_transcript_whisper(args.url, platform, work_dir, args.cookies, args.whisper_model)
            if transcript:
                print(f"[info] Whisper: {len(transcript.split())} words")
            else:
                print("[warn] No transcript — proceeding with frames only.")

        # ── Video + Frames ──
        print("[info] Downloading video for frame extraction...")
        video_path = download_video(args.url, platform, work_dir, args.cookies)

        if not video_path:
            sys.exit(
                "[error] Video download failed.\n"
                "  Facebook/Instagram: add --cookies /path/to/cookies.txt\n"
                "  YouTube (bot detection): add --cookies /path/to/cookies.txt"
            )

        print(f"[info] Extracting frames (max {args.max_frames})...")
        frames_dir = work_dir / "frames"
        frames = extract_frames(video_path, frames_dir, args.max_frames)
        print(f"[info] {len(frames)} frames extracted")

        if not frames:
            sys.exit("[error] No frames extracted — check ffmpeg and verify the video downloaded.")

        # ── Claude Analysis ──
        print(f"[info] Sending {len(frames)} frames + transcript to {args.model}...")
        markdown = analyze_with_claude(frames, transcript, title, api_key, args.model)

        # ── Write Output ──
        safe_title = re.sub(r"[^\w\s-]", "", title).strip().replace(" ", "_")[:60]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
        out_file = output_dir / f"{safe_title}_{timestamp}.md"

        frontmatter = (
            f"---\n"
            f"source: {args.url}\n"
            f"platform: {platform}\n"
            f"title: \"{title}\"\n"
            f"analyzed: {datetime.now().isoformat()}\n"
            f"frames_analyzed: {len(frames)}\n"
            f"transcript: {'whisper' if args.whisper else 'captions'}\n"
            f"model: {args.model}\n"
            f"---\n\n"
        )

        out_file.write_text(frontmatter + markdown, encoding="utf-8")
        print(f"\n✓ Saved: {out_file}")
        # Last printed line is the path — SKILL.md captures this
        print(str(out_file))


if __name__ == "__main__":
    main()
