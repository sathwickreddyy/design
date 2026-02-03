"""Demo: Checksum verification in multipart upload."""
import os
import sys
import tempfile
import hashlib
sys.path.insert(0, '/Users/sathwick/my-office/system-design-learning/adhoc-learning/multipart-upload/client')

from uploader import MultipartUploader

def demo_checksum_verification():
    """Demonstrate checksum verification workflow."""
    print("\n" + "="*70)
    print("DEMO: Multipart Upload with Checksum Verification (Option A)")
    print("="*70)
    
    # Create test file
    print("\n1. Creating test file...")
    test_file = tempfile.NamedTemporaryFile(mode='wb', delete=False, suffix='.bin')
    test_data = os.urandom(30 * 1024 * 1024)  # 30MB
    test_file.write(test_data)
    test_file.close()
    print(f"✓ Test file created: {test_file.name}")
    print(f"  Size: {len(test_data) / (1024*1024):.2f} MB")
    
    # Calculate checksums
    print("\n2. Calculating checksums...")
    uploader = MultipartUploader()
    
    file_hash = uploader.calculate_file_hash(test_file.name, "SHA256")
    print(f"✓ File SHA256: {file_hash}")
    
    # Split file and calculate part hashes
    print(f"\n3. Calculating part hashes...")
    with open(test_file.name, "rb") as f:
        for i in range(1, 7):
            chunk = f.read(5 * 1024 * 1024)
            part_hash = hashlib.md5(chunk).hexdigest()
            print(f"  Part {i}: {part_hash}")
    
    # Upload with verification
    print(f"\n4. Uploading file with checksum verification...")
    try:
        session_id = uploader.upload_file(test_file.name)
        print(f"\n✓ Upload successful!")
        
        # Get final status
        status = uploader.get_status(session_id)
        print(f"\nFinal Status:")
        print(f"  Session ID: {session_id}")
        print(f"  Filename: {status['filename']}")
        print(f"  Parts: {status['completed_parts']}/{status['total_parts']}")
        print(f"  Progress: {status['progress_percent']:.1f}%")
        print(f"  Status: {status['status']}")
        
    except Exception as e:
        print(f"✗ Upload failed: {e}")
    finally:
        os.unlink(test_file.name)


def demo_checksum_failure():
    """Demonstrate checksum failure detection."""
    print("\n" + "="*70)
    print("DEMO: Detecting Corrupted Data with Checksums")
    print("="*70)
    
    print("""
Scenario: Network corruption during part upload

1. Client calculates MD5 of part_3: "abc123def456"
2. Part corrupted in transit (1 bit flip)
3. Server calculates MD5: "abc123def457" (different!)
4. Server rejects upload with: "Checksum mismatch for part 3"
5. Client automatically retries part 3

Without checksum verification:
  ✗ Corrupted part would be silently accepted
  ✗ File would assemble with corruption
  ✗ You'd only find out weeks later during playback/viewing
  
With checksum verification:
  ✓ Corruption detected immediately
  ✓ Client retries automatically
  ✓ File integrity guaranteed at assembly time
""")


def demo_full_file_verification():
    """Demonstrate full file hash verification."""
    print("\n" + "="*70)
    print("DEMO: Full File Integrity Verification")
    print("="*70)
    
    print("""
Two-Level Verification Strategy:

Level 1: Per-Part Verification (MD5)
  └─ Fast, catches transport corruption
  └─ Each part verified on receipt
  └─ 1 MB part: ~1ms to verify

Level 2: Full File Verification (SHA256)
  └─ Comprehensive, catches assembly bugs
  └─ Verified after all parts assembled
  └─ 100 MB file: ~100ms to verify
  
Example Flow:
  
  Client              Network            Server
  ─────────────────────────────────────────────────
  Part 1 (MD5) ──────────────────>  Verify MD5 ✓
  Part 2 (MD5) ──────────────────>  Verify MD5 ✓
  Part 3 (MD5) ──────────────────>  Verify MD5 ✓
  ...
  Complete    ──────────────────>  Assemble parts
                                   Verify SHA256 ✓
                                   (Check against original)
  ✓ File ready
  <────────────────────────────── Success
""")


def show_checksum_api():
    """Show API usage with checksums."""
    print("\n" + "="*70)
    print("API: Checksum Usage")
    print("="*70)
    
    print("""
1. Initialize Upload (with file hash)
   ────────────────────────────────────
   POST /upload/init
   {
     "filename": "video.mp4",
     "file_size": 104857600,
     "file_hash": "abc123def456...",      ← SHA256 of full file
     "hash_algorithm": "SHA256"
   }

2. Upload Part (with part hash header)
   ────────────────────────────────────
   PUT /upload/{session_id}/part/1
   Headers:
     X-Part-Hash: abc123...  ← MD5 of part
   Body: <5MB chunk>
   
   Response:
   {
     "part_number": 1,
     "received": true,
     "size": 5242880,
     "checksum": "abc123..."  ← Server computed MD5
   }

3. Complete Upload (server verifies full file hash)
   ────────────────────────────────────────────────
   POST /upload/{session_id}/complete
   
   Server:
     - Assembles all parts
     - Calculates SHA256 of assembled file
     - Compares with file_hash from init
     - If mismatch: ✗ "File integrity check failed"
     - If match: ✓ Returns file_path
""")


if __name__ == "__main__":
    show_checksum_api()
    demo_checksum_failure()
    demo_full_file_verification()
    
    print("\n" + "="*70)
    print("To see checksum verification in action:")
    print("="*70)
    print("python3 demo_checksum.py --upload")
