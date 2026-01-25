"""
Video processing activities package

Contains all Temporal activities for video processing:
- metadata: Fast metadata extraction using ffprobe
- chunked_transcode: Parallel chunk-based transcoding with HLS output
"""

from worker.activities.metadata import extract_metadata
from worker.activities.chunked_transcode import (
    split_video,
    transcode_chunk,
    generate_hls_playlist,
    generate_master_playlist,
    cleanup_source_chunks,
)

__all__ = [
    # Metadata
    'extract_metadata',
    # Chunk-based transcoding with HLS output
    'split_video',
    'transcode_chunk',
    'generate_hls_playlist',
    'generate_master_playlist',
    'cleanup_source_chunks',
]
