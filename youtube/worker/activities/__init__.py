"""
Video processing activities package

Contains all Temporal activities for video processing:
- metadata: Fast metadata extraction using ffprobe
- transcode: Slow video transcoding using ffmpeg
"""

from worker.activities.metadata import extract_metadata
from worker.activities.transcode import transcode_to_720p

__all__ = [
    'extract_metadata',
    'transcode_to_720p',
]
