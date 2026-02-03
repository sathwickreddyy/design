"""Test script demonstrating multipart upload with failure simulation."""
import os
import sys
import time
import random
import tempfile
import requests
from pathlib import Path
from uploader import MultipartUploader

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")


def create_test_file(size_mb: int = 50) -> str:
    """Create a test file with random data."""
    print(f"Creating test file ({size_mb} MB)...")
    
    test_file = tempfile.NamedTemporaryFile(mode='wb', delete=False, suffix='.bin')
    
    # Write in chunks to avoid memory issues
    chunk_size = 1024 * 1024  # 1MB
    for _ in range(size_mb):
        test_file.write(os.urandom(chunk_size))
    
    test_file.close()
    print(f"✓ Test file created: {test_file.name}")
    
    return test_file.name


def test_normal_upload():
    """Test normal upload flow."""
    print("\n" + "="*60)
    print("TEST 1: Normal Upload (No Failures)")
    print("="*60)
    
    test_file = create_test_file(size_mb=20)
    
    try:
        uploader = MultipartUploader(max_workers=4)
        uploader.upload_file(test_file)
        print("\n✓ Test 1 PASSED: Normal upload completed successfully")
    finally:
        os.unlink(test_file)


def test_resume_upload():
    """Test resuming after simulated failure."""
    print("\n" + "="*60)
    print("TEST 2: Resume After Failure")
    print("="*60)
    
    test_file = create_test_file(size_mb=50)
    
    try:
        # Phase 1: Upload some parts, then simulate failure
        print("\nPhase 1: Uploading (will simulate failure)...")
        
        uploader = MultipartUploader(max_workers=4)
        file_size = Path(test_file).stat().st_size
        filename = Path(test_file).name
        
        # Initialize upload
        session_id, total_parts = uploader.init_upload(filename, file_size)
        
        # Upload only first 60% of parts
        parts_to_upload = int(total_parts * 0.6)
        print(f"Uploading {parts_to_upload}/{total_parts} parts before 'failure'...")
        
        with open(test_file, "rb") as f:
            for part_num in range(1, parts_to_upload + 1):
                chunk_data = f.read(uploader.chunk_size)
                uploader.upload_part(session_id, part_num, chunk_data)
                print(f"  ✓ Part {part_num}/{parts_to_upload} uploaded")
        
        # Check status
        status = uploader.get_status(session_id)
        print(f"\nStatus before failure:")
        print(f"  Completed: {len(status['completed_parts'])}/{total_parts} parts")
        print(f"  Progress: {status['progress_percent']:.1f}%")
        
        print("\n💥 Simulating network failure...")
        time.sleep(2)
        
        # Phase 2: Resume upload
        print("\n\nPhase 2: Resuming upload...")
        uploader.upload_file(test_file, session_id=session_id)
        
        print("\n✓ Test 2 PASSED: Successfully resumed and completed upload")
    
    finally:
        os.unlink(test_file)


def test_parallel_performance():
    """Test different numbers of parallel workers."""
    print("\n" + "="*60)
    print("TEST 3: Parallel Upload Performance")
    print("="*60)
    
    test_file = create_test_file(size_mb=30)
    
    try:
        results = {}
        
        for num_workers in [1, 2, 4, 8]:
            print(f"\n--- Testing with {num_workers} worker(s) ---")
            
            uploader = MultipartUploader(max_workers=num_workers)
            start = time.time()
            uploader.upload_file(test_file)
            duration = time.time() - start
            
            results[num_workers] = duration
            
            time.sleep(2)  # Cool down
        
        print("\n\nPerformance Results:")
        print(f"{'Workers':<10} {'Time (s)':<12} {'Speedup':<10}")
        print("-" * 32)
        
        baseline = results[1]
        for workers, duration in results.items():
            speedup = baseline / duration
            print(f"{workers:<10} {duration:<12.2f} {speedup:<10.2f}x")
        
        print("\n✓ Test 3 PASSED: Performance comparison complete")
    
    finally:
        os.unlink(test_file)


def test_status_query():
    """Test querying upload status."""
    print("\n" + "="*60)
    print("TEST 4: Status Query During Upload")
    print("="*60)
    
    test_file = create_test_file(size_mb=30)
    
    try:
        uploader = MultipartUploader(max_workers=2)  # Slower upload
        file_size = Path(test_file).stat().st_size
        filename = Path(test_file).name
        
        # Initialize
        session_id, total_parts = uploader.init_upload(filename, file_size)
        
        # Upload parts gradually and check status
        with open(test_file, "rb") as f:
            for part_num in range(1, min(10, total_parts) + 1):
                chunk_data = f.read(uploader.chunk_size)
                uploader.upload_part(session_id, part_num, chunk_data)
                
                # Query status
                status = uploader.get_status(session_id)
                print(f"Part {part_num} uploaded - Progress: {status['progress_percent']:.1f}% "
                      f"({len(status['completed_parts'])}/{total_parts} parts)")
        
        print("\n✓ Test 4 PASSED: Status queries working correctly")
        uploader.complete_upload(session_id)
    
    finally:
        os.unlink(test_file)


def test_list_sessions():
    """Test listing all sessions."""
    print("\n" + "="*60)
    print("TEST 5: List All Sessions")
    print("="*60)
    
    response = requests.get(f"{API_BASE_URL}/sessions")
    response.raise_for_status()
    
    data = response.json()
    print(f"\nFound {data['total']} sessions:")
    
    for session in data['sessions'][:10]:  # Show first 10
        print(f"  {session['session_id'][:8]}... | {session['filename']:<30} | "
              f"{session['status']:<12} | {session['progress']}")
    
    print("\n✓ Test 5 PASSED: Session listing works")


def main():
    """Run all tests."""
    print("\n" + "="*60)
    print("MULTIPART UPLOAD - TEST SUITE")
    print("="*60)
    
    # Check if API is running
    try:
        response = requests.get(f"{API_BASE_URL}/health")
        response.raise_for_status()
        print("✓ API is running")
    except Exception as e:
        print(f"✗ API not available: {e}")
        print("\nStart the API first:")
        print("  docker-compose up -d")
        sys.exit(1)
    
    tests = [
        test_normal_upload,
        test_resume_upload,
        test_status_query,
        test_list_sessions,
        # test_parallel_performance,  # Comment out for quick runs
    ]
    
    for test in tests:
        try:
            test()
        except Exception as e:
            print(f"\n✗ Test FAILED: {e}")
            import traceback
            traceback.print_exc()
    
    print("\n" + "="*60)
    print("ALL TESTS COMPLETED")
    print("="*60)


if __name__ == "__main__":
    main()
