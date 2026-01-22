"""
Load test for YouTube video processing system.

Purpose: Test system capacity with 100 concurrent YouTube video requests.
Consumers: Manual testing, performance validation.
Logic:
  1. Define diverse set of YouTube videos (various durations)
  2. Send 100 concurrent POST requests to /upload-youtube-url
  3. Track success rate, response times, errors
  4. Monitor workflow status
"""
import asyncio
import aiohttp
import time
from typing import List, Dict

# Diverse YouTube videos for testing (various durations)
TEST_VIDEOS = [
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ",  # Rick Roll - 3:33
    "https://www.youtube.com/watch?v=jNQXAC9IVRw",  # Me at the zoo - 0:19
    "https://www.youtube.com/watch?v=9bZkp7q19f0",  # Gangnam Style - 4:13
    "https://www.youtube.com/watch?v=kJQP7kiw5Fk",  # Despacito - 4:42
    "https://www.youtube.com/watch?v=OPf0YbXqDm0",  # Mark Ronson - Uptown Funk - 4:30
    "https://www.youtube.com/watch?v=fJ9rUzIMcZQ",  # Queen - Bohemian Rhapsody - 5:55
    "https://www.youtube.com/watch?v=YQHsXMglC9A",  # Adele - Hello - 6:07
    "https://www.youtube.com/watch?v=RgKAFK5djSk",  # Wiz Khalifa - See You Again - 3:57
    "https://www.youtube.com/watch?v=kffacxfA7G4",  # Baby Shark - 2:17
    "https://www.youtube.com/watch?v=SlPhMPnQ58k",  # Despacito Remix - 3:49
]

API_URL = "http://localhost:8000/api/videos"


async def upload_video(session: aiohttp.ClientSession, video_url: str, request_id: int) -> Dict:
    """
    Upload a single YouTube video via API.
    
    Args:
        session: aiohttp session for connection pooling
        video_url: YouTube video URL
        request_id: Sequential request identifier
    
    Returns:
        Dict with success status, video_id, duration, and timing info
    """
    start_time = time.time()
    try:
        async with session.post(
            f"{API_URL}/upload-youtube-url",
            json={"url": video_url},
            timeout=aiohttp.ClientTimeout(total=180)
        ) as response:
            elapsed = time.time() - start_time
            if response.status == 200:
                data = await response.json()
                return {
                    "success": True,
                    "request_id": request_id,
                    "video_id": data.get("video_id"),
                    "title": data.get("title", "")[:50],
                    "duration": data.get("duration_seconds"),
                    "response_time": round(elapsed, 2),
                    "status_code": 200
                }
            else:
                error_text = await response.text()
                return {
                    "success": False,
                    "request_id": request_id,
                    "error": error_text[:100],
                    "response_time": round(elapsed, 2),
                    "status_code": response.status
                }
    except asyncio.TimeoutError:
        return {
            "success": False,
            "request_id": request_id,
            "error": "Request timeout (>180s)",
            "response_time": 180.0,
            "status_code": 0
        }
    except Exception as e:
        elapsed = time.time() - start_time
        return {
            "success": False,
            "request_id": request_id,
            "error": str(e)[:100],
            "response_time": round(elapsed, 2),
            "status_code": 0
        }


async def run_load_test(num_requests: int = 10):
    """
    Execute load test with concurrent YouTube video uploads.
    
    Args:
        num_requests: Total number of requests to send (default: 10)
    
    Logic:
        1. Create video URL list by cycling through TEST_VIDEOS
        2. Create concurrent tasks for all requests
        3. Gather results and calculate statistics
        4. Print summary report
    """
    print(f"🚀 Starting load test with {num_requests} concurrent requests...\n")
    
    # Create video list by cycling through test videos
    video_urls = [TEST_VIDEOS[i % len(TEST_VIDEOS)] for i in range(num_requests)]
    
    start_time = time.time()
    
    # Create single session for connection pooling
    connector = aiohttp.TCPConnector(limit=100, limit_per_host=50)
    async with aiohttp.ClientSession(connector=connector) as session:
        # Create concurrent tasks
        tasks = [
            upload_video(session, url, i + 1)
            for i, url in enumerate(video_urls)
        ]
        
        # Execute all requests concurrently
        results = await asyncio.gather(*tasks)
    
    total_time = time.time() - start_time
    
    # Calculate statistics
    successful = [r for r in results if r["success"]]
    failed = [r for r in results if not r["success"]]
    
    response_times = [r["response_time"] for r in results]
    avg_response_time = sum(response_times) / len(response_times)
    min_response_time = min(response_times)
    max_response_time = max(response_times)
    
    # Print results
    print("\n" + "=" * 70)
    print("📊 LOAD TEST RESULTS")
    print("=" * 70)
    print(f"Total Requests:     {num_requests}")
    print(f"Successful:         {len(successful)} ({len(successful)/num_requests*100:.1f}%)")
    print(f"Failed:             {len(failed)} ({len(failed)/num_requests*100:.1f}%)")
    print(f"Total Duration:     {total_time:.2f}s")
    print(f"Requests/sec:       {num_requests/total_time:.2f}")
    print()
    print(f"Response Times:")
    print(f"  - Average:        {avg_response_time:.2f}s")
    print(f"  - Min:            {min_response_time:.2f}s")
    print(f"  - Max:            {max_response_time:.2f}s")
    print("=" * 70)
    
    # Show first 10 successful uploads
    if successful:
        print(f"\n✅ First 10 Successful Uploads:")
        for r in successful[:10]:
            print(f"  [{r['request_id']:3d}] {r['video_id']} - {r['title']} ({r['response_time']}s)")
    
    # Show all failures
    if failed:
        print(f"\n❌ Failed Requests ({len(failed)}):")
        for r in failed[:20]:  # Show max 20 failures
            print(f"  [{r['request_id']:3d}] Error: {r['error']} (HTTP {r['status_code']})")
    
    print(f"\n💡 Next Steps:")
    print(f"  - Check status: curl http://localhost:8000/api/videos/status/<video_id>")
    print(f"  - Temporal UI: http://localhost:8080")
    print(f"  - Docker logs: docker-compose -f docker/docker-compose.yml logs -f")
    print()


if __name__ == "__main__":
    # Install dependencies: pip install aiohttp
    # Usage: python load_test.py [num_requests]
    import sys
    num_requests = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    print(f"\n📝 Load Test Configuration:")
    print(f"  - Requests: {num_requests}")
    print(f"  - Timeout: 180s per request")
    print(f"  - Video pool: {len(TEST_VIDEOS)} YouTube videos\n")
    asyncio.run(run_load_test(num_requests))
