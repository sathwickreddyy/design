"""
Video processing activities package

Contains all Temporal activities for video processing:
- metadata: Fast metadata extraction using ffprobe
- transcode: Slow video transcoding using ffmpeg (per-resolution)
- chunked_transcode: Parallel chunk-based transcoding (split, transcode, merge)
"""

from worker.activities.metadata import extract_metadata
from worker.activities.transcode import (
    transcode_to_320p,
    transcode_to_480p,
    transcode_to_720p,
    transcode_to_1080p,
)
from worker.activities.chunked_transcode import (
    split_video,
    transcode_chunk,
    merge_segments,
    cleanup_source_chunks,
)

__all__ = [
    # Metadata
    'extract_metadata',
    # Per-resolution transcoding (legacy)
    'transcode_to_320p',
    'transcode_to_480p',
    'transcode_to_720p',
    'transcode_to_1080p',
    # Chunk-based transcoding (new)
    'split_video',
    'transcode_chunk',
    'merge_segments',
    'cleanup_source_chunks',
]
