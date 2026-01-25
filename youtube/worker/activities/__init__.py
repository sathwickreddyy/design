"""
Video processing activities package

Contains all Temporal activities for video processing:
- metadata: Fast metadata extraction using ffprobe
- chunked_transcode: Parallel chunk-based transcoding (split, transcode, merge)
"""

from worker.activities.metadata import extract_metadata
from worker.activities.chunked_transcode import (
    split_video,
    transcode_chunk,
    merge_segments,
    cleanup_source_chunks,
)

__all__ = [
    # Metadata
    'extract_metadata',
    # Chunk-based transcoding
    'split_video',
    'transcode_chunk',
    'merge_segments',
    'cleanup_source_chunks',
]
