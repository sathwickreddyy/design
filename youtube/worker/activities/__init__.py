"""
Video processing activities package

Contains all Temporal activities for video processing:
- metadata: Fast metadata extraction using ffprobe
- thumbnail: Thumbnail generation (auto, custom, scene-based)
- scene_detection: Scene detection and chapter generation
- chunked_transcode: Parallel chunk-based transcoding with HLS output
"""

from worker.activities.metadata import extract_metadata
from worker.activities.thumbnail import generate_thumbnail, upload_custom_thumbnail
from worker.activities.scene_detection import detect_scenes, generate_chapter_files
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
    # Thumbnail
    'generate_thumbnail',
    'upload_custom_thumbnail',
    # Scene detection & chapters
    'detect_scenes',
    'generate_chapter_files',
    # Chunk-based transcoding with HLS output
    'split_video',
    'transcode_chunk',
    'generate_hls_playlist',
    'generate_master_playlist',
    'cleanup_source_chunks',
]
