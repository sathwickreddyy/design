"""
Scene detection activity for video chapter generation.

Purpose: Detect scene changes in videos to create chapter markers.
Consumers: Workers polling 'metadata-queue' (lightweight I/O operation).
Logic:
  1. Analyze video for scene changes using FFmpeg
  2. Filter/merge scenes based on minimum duration
  3. Generate chapter metadata in multiple formats (JSON, WebVTT, HLS)
  4. Optionally detect intro/outro sequences
"""
import os
import re
import json
import tempfile
import subprocess
from pathlib import Path
from typing import Optional, List
from dataclasses import dataclass, asdict
from temporalio import activity
from shared.storage import MinIOStorage, StoragePaths


@dataclass
class Chapter:
    """Represents a video chapter/scene."""
    index: int
    start_time: float      # seconds
    end_time: float        # seconds
    duration: float        # seconds
    title: str             # Auto-generated or custom
    scene_score: float     # FFmpeg scene detection score (0-1)
    is_intro: bool = False
    is_outro: bool = False


@dataclass
class SceneDetectionResult:
    """Result of scene detection analysis."""
    video_id: str
    total_duration: float
    scene_count: int
    chapters: List[Chapter]
    threshold_used: float
    
    def to_dict(self) -> dict:
        return {
            "video_id": self.video_id,
            "total_duration": self.total_duration,
            "scene_count": self.scene_count,
            "chapters": [asdict(c) for c in self.chapters],
            "threshold_used": self.threshold_used
        }


def format_vtt_timestamp(seconds: float) -> str:
    """Format seconds as WebVTT timestamp (HH:MM:SS.mmm)."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"


def generate_webvtt(chapters: List[Chapter], video_id: str) -> str:
    """
    Generate WebVTT chapter file.
    
    WebVTT is the standard format for web video chapters.
    Supported by most HTML5 video players.
    
    Example output:
        WEBVTT
        
        00:00:00.000 --> 00:00:30.000
        Chapter 1: Introduction
        
        00:00:30.000 --> 00:02:15.000
        Chapter 2: Main Content
    """
    lines = ["WEBVTT", f"X-VIDEO-ID: {video_id}", ""]
    
    for chapter in chapters:
        start = format_vtt_timestamp(chapter.start_time)
        end = format_vtt_timestamp(chapter.end_time)
        lines.append(f"{start} --> {end}")
        lines.append(chapter.title)
        lines.append("")
    
    return "\n".join(lines)


def generate_hls_chapter_tags(chapters: List[Chapter]) -> List[str]:
    """
    Generate HLS EXT-X-DATERANGE tags for chapter markers.
    
    These can be inserted into m3u8 playlists for native HLS chapter support.
    
    Example output:
        #EXT-X-DATERANGE:ID="chapter-1",START-DATE="1970-01-01T00:00:00Z",DURATION=30.0,X-TITLE="Introduction"
    """
    tags = []
    base_date = "1970-01-01T"
    
    for chapter in chapters:
        # Convert start time to ISO format
        h = int(chapter.start_time // 3600)
        m = int((chapter.start_time % 3600) // 60)
        s = int(chapter.start_time % 60)
        start_iso = f"{base_date}{h:02d}:{m:02d}:{s:02d}Z"
        
        tag = (
            f'#EXT-X-DATERANGE:ID="chapter-{chapter.index}",'
            f'START-DATE="{start_iso}",'
            f'DURATION={chapter.duration:.1f},'
            f'X-TITLE="{chapter.title}"'
        )
        tags.append(tag)
    
    return tags


def parse_scene_timestamps(ffmpeg_output: str) -> List[tuple[float, float]]:
    """
    Parse scene detection timestamps from FFmpeg showinfo output.
    
    FFmpeg outputs lines like:
        [Parsed_showinfo_1 @ 0x...] n:  42 pts:  84084 pts_time:3.5035  ...
    
    Returns:
        List of (timestamp, scene_score) tuples
    """
    scenes = []
    # Match pts_time values from showinfo filter output
    pattern = r'pts_time:\s*([0-9.]+)'
    
    for match in re.finditer(pattern, ffmpeg_output):
        timestamp = float(match.group(1))
        # Scene score not directly available, we'll estimate based on detection
        scenes.append((timestamp, 1.0))
    
    return scenes


@activity.defn
async def detect_scenes(
    video_id: str,
    threshold: float = 0.3,
    min_chapter_duration: int = 30,
    detect_intro: bool = True,
    detect_outro: bool = True,
    video_duration: Optional[float] = None
) -> dict:
    """
    Detect scene changes in a video to create chapter markers.
    
    Purpose: Automatically segment videos into chapters based on visual changes.
    Consumers: Workflow orchestrator when chapter generation is enabled.
    
    How it works:
        1. FFmpeg analyzes each frame for visual differences
        2. Frames exceeding the threshold are marked as scene changes
        3. Adjacent scenes are merged if below min_chapter_duration
        4. Optionally detects intro (black frames at start) and outro
    
    Args:
        video_id: Unique identifier for the video
        threshold: Scene change sensitivity (0.1-0.5, lower = more scenes)
        min_chapter_duration: Minimum chapter length in seconds
        detect_intro: Whether to detect intro sequences
        detect_outro: Whether to detect outro/credits
        video_duration: Video duration (optional, will probe if not provided)
        
    Returns:
        Dictionary with scene detection results
    """
    activity.logger.info(
        f"[{video_id}] Starting scene detection (threshold={threshold}, "
        f"min_duration={min_chapter_duration}s)"
    )
    
    storage = MinIOStorage()
    temp_input_path = None
    
    try:
        # Step 1: Download source video
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tmp_in:
            temp_input_path = tmp_in.name
        
        success = storage.download_file(
            bucket_name="videos",
            object_name=StoragePaths.source_video(video_id),
            file_path=temp_input_path
        )
        
        if not success:
            raise RuntimeError(f"Failed to download video {video_id}")
        
        # Step 2: Get video duration if not provided
        if not video_duration:
            probe_cmd = [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                temp_input_path
            ]
            result = subprocess.run(probe_cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                video_duration = float(result.stdout.strip())
            else:
                raise RuntimeError("Could not determine video duration")
        
        activity.logger.info(f"[{video_id}] Video duration: {video_duration:.2f}s")
        
        # Skip scene detection for very short videos
        if video_duration < min_chapter_duration * 2:
            activity.logger.info(f"[{video_id}] Video too short for chapters, returning single chapter")
            single_chapter = Chapter(
                index=0,
                start_time=0,
                end_time=video_duration,
                duration=video_duration,
                title="Full Video",
                scene_score=1.0
            )
            result = SceneDetectionResult(
                video_id=video_id,
                total_duration=video_duration,
                scene_count=1,
                chapters=[single_chapter],
                threshold_used=threshold
            )
            return {**result.to_dict(), "success": True, "error": None}
        
        # Step 3: Run FFmpeg scene detection
        # select filter detects scene changes, showinfo outputs timestamps
        cmd = [
            "ffmpeg",
            "-i", temp_input_path,
            "-filter:v", f"select='gt(scene,{threshold})',showinfo",
            "-f", "null",
            "-"
        ]
        
        activity.logger.info(f"[{video_id}] Running FFmpeg scene detection")
        
        process = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300  # 5 min timeout for long videos
        )
        
        # Parse scene timestamps from stderr (FFmpeg outputs filter info there)
        scene_timestamps = parse_scene_timestamps(process.stderr)
        
        activity.logger.info(f"[{video_id}] Detected {len(scene_timestamps)} raw scene changes")
        
        # Step 4: Build chapters from scene timestamps
        chapters = []
        
        # Always start with a chapter at 0
        scene_times = [0.0] + [t for t, _ in scene_timestamps] + [video_duration]
        
        # Merge scenes that are too short
        merged_times = [0.0]
        for t in scene_times[1:]:
            if t - merged_times[-1] >= min_chapter_duration:
                merged_times.append(t)
        
        # Ensure we end at video duration
        if merged_times[-1] != video_duration:
            if video_duration - merged_times[-1] < min_chapter_duration:
                # Merge with previous chapter
                merged_times[-1] = video_duration
            else:
                merged_times.append(video_duration)
        
        activity.logger.info(f"[{video_id}] After merging: {len(merged_times) - 1} chapters")
        
        # Step 5: Create chapter objects
        for i in range(len(merged_times) - 1):
            start = merged_times[i]
            end = merged_times[i + 1]
            duration = end - start
            
            # Detect intro (first 30 seconds, typically)
            is_intro = detect_intro and i == 0 and duration <= 60
            
            # Detect outro (last chapter if short)
            is_outro = detect_outro and i == len(merged_times) - 2 and duration <= 60
            
            # Generate title
            if is_intro:
                title = "Introduction"
            elif is_outro:
                title = "Outro"
            else:
                title = f"Chapter {i + 1}"
            
            chapter = Chapter(
                index=i,
                start_time=start,
                end_time=end,
                duration=duration,
                title=title,
                scene_score=1.0,
                is_intro=is_intro,
                is_outro=is_outro
            )
            chapters.append(chapter)
        
        # Handle case where no scenes were detected
        if len(chapters) == 0:
            chapters.append(Chapter(
                index=0,
                start_time=0,
                end_time=video_duration,
                duration=video_duration,
                title="Full Video",
                scene_score=1.0
            ))
        
        result = SceneDetectionResult(
            video_id=video_id,
            total_duration=video_duration,
            scene_count=len(chapters),
            chapters=chapters,
            threshold_used=threshold
        )
        
        activity.logger.info(
            f"[{video_id}] Scene detection complete: {len(chapters)} chapters"
        )
        
        return {**result.to_dict(), "success": True, "error": None}
        
    except subprocess.TimeoutExpired:
        activity.logger.error(f"[{video_id}] Scene detection timed out")
        return {
            "video_id": video_id,
            "success": False,
            "error": "Scene detection timed out"
        }
    except Exception as e:
        activity.logger.error(f"[{video_id}] Scene detection failed: {e}")
        return {
            "video_id": video_id,
            "success": False,
            "error": str(e)
        }
    finally:
        if temp_input_path and Path(temp_input_path).exists():
            Path(temp_input_path).unlink()


@activity.defn
async def generate_chapter_files(
    video_id: str,
    chapters: List[dict],
    total_duration: float
) -> dict:
    """
    Generate chapter metadata files in multiple formats.
    
    Purpose: Create chapter files for different consumers (web, mobile, HLS).
    Consumers: Workflow orchestrator after scene detection.
    
    Generates:
        1. chapters.json - Machine-readable JSON
        2. chapters.vtt - WebVTT for HTML5 video players
        3. chapters_hls.txt - HLS EXT-X-DATERANGE tags for m3u8
    
    Args:
        video_id: Unique identifier for the video
        chapters: List of chapter dictionaries
        total_duration: Total video duration
        
    Returns:
        Dictionary with paths to generated files
    """
    activity.logger.info(f"[{video_id}] Generating chapter files for {len(chapters)} chapters")
    
    storage = MinIOStorage()
    
    try:
        # Convert dicts back to Chapter objects
        chapter_objects = [
            Chapter(
                index=c["index"],
                start_time=c["start_time"],
                end_time=c["end_time"],
                duration=c["duration"],
                title=c["title"],
                scene_score=c.get("scene_score", 1.0),
                is_intro=c.get("is_intro", False),
                is_outro=c.get("is_outro", False)
            )
            for c in chapters
        ]
        
        # Generate JSON
        json_content = json.dumps({
            "video_id": video_id,
            "total_duration": total_duration,
            "chapter_count": len(chapters),
            "chapters": chapters
        }, indent=2)
        
        json_key = StoragePaths.chapters_json(video_id)
        storage.upload_fileobj(
            file_data=json_content.encode('utf-8'),
            bucket_name="videos",
            object_name=json_key
        )
        
        # Generate WebVTT
        vtt_content = generate_webvtt(chapter_objects, video_id)
        vtt_key = StoragePaths.chapters_vtt(video_id)
        storage.upload_fileobj(
            file_data=vtt_content.encode('utf-8'),
            bucket_name="videos",
            object_name=vtt_key
        )
        
        # Generate HLS tags
        hls_tags = generate_hls_chapter_tags(chapter_objects)
        hls_content = "\n".join(hls_tags)
        hls_key = StoragePaths.chapters_hls(video_id)
        storage.upload_fileobj(
            file_data=hls_content.encode('utf-8'),
            bucket_name="videos",
            object_name=hls_key
        )
        
        activity.logger.info(f"[{video_id}] Chapter files generated successfully")
        
        return {
            "video_id": video_id,
            "json_key": json_key,
            "vtt_key": vtt_key,
            "hls_key": hls_key,
            "chapter_count": len(chapters),
            "success": True,
            "error": None
        }
        
    except Exception as e:
        activity.logger.error(f"[{video_id}] Chapter file generation failed: {e}")
        return {
            "video_id": video_id,
            "success": False,
            "error": str(e)
        }


__all__ = ["detect_scenes", "generate_chapter_files"]
