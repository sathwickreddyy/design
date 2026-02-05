"""
Demo: Offline Conflict Scenario
Simulates two clients editing the same file while disconnected,
then syncing and detecting conflict
"""

import asyncio
import logging
from sync_client import SyncClient

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("demo_offline")


async def main():
    print("\n" + "="*70)
    print("🎬 OFFLINE CONFLICT SCENARIO DEMO")
    print("="*70 + "\n")
    
    # Initialize two clients
    client_a = SyncClient("ClientA")
    client_b = SyncClient("ClientB")
    
    file_id = "document.txt"
    initial_content = "Hello World - Version 1"
    
    print("\n📝 STEP 1: Client A creates initial file")
    print("-" * 70)
    await client_a.create_file(file_id, initial_content)
    await asyncio.sleep(0.5)
    
    print("\n📥 STEP 2: Both clients download the file (v1)")
    print("-" * 70)
    await client_a.download(file_id)
    await client_b.download(file_id)
    await asyncio.sleep(0.5)
    
    print("\n💤 STEP 3: BOTH CLIENTS GO OFFLINE (simulate disconnect)")
    print("-" * 70)
    print("⚠️  Network disconnected - clients working independently")
    await asyncio.sleep(0.5)
    
    print("\n✏️ STEP 4: Client A edits file (offline)")
    print("-" * 70)
    client_a.edit_file(file_id, "Hello World - EDITED BY CLIENT A (offline)")
    await asyncio.sleep(0.5)
    
    print("\n✏️ STEP 5: Client B edits file (offline)")
    print("-" * 70)
    client_b.edit_file(file_id, "Hello World - EDITED BY CLIENT B (offline)")
    await asyncio.sleep(0.5)
    
    print("\n🌐 STEP 6: CLIENTS RECONNECT - Attempt to sync")
    print("-" * 70)
    print("🔄 Network restored - clients syncing changes...")
    await asyncio.sleep(0.5)
    
    print("\n📤 STEP 7: Client A syncs first")
    print("-" * 70)
    result_a = await client_a.upload(file_id)
    await asyncio.sleep(0.5)
    
    print("\n📤 STEP 8: Client B tries to sync (CONFLICT!)")
    print("-" * 70)
    result_b = await client_b.upload(file_id)
    
    if result_b["status"] == "conflict":
        await asyncio.sleep(0.5)
        print("\n" + "="*70)
        print("⚠️  CONFLICT DETECTED!")
        print("="*70)
        print(f"\n📊 Conflict Details:")
        print(f"   • Expected version: v1 (what both clients had)")
        print(f"   • Server version: v2 (Client A synced first)")
        print(f"   • Client A's content: '{result_a['data']['content'] if 'data' in result_a else 'N/A'}'")
        print(f"   • Client B's content: '{client_b.local_files[file_id]['content']}'")
        
        print("\n🔧 STEP 9: Resolving conflict (KEEP BOTH strategy)")
        print("-" * 70)
        await asyncio.sleep(0.5)
        
        resolution = await client_b.resolve_conflict_keep_both(
            file_id,
            result_b["conflict_data"]
        )
        
        await asyncio.sleep(0.5)
        print("\n" + "="*70)
        print("✅ CONFLICT RESOLVED")
        print("="*70)
        print(f"\n📁 Final State:")
        print(f"   • {file_id}: Server version (Client A's edit)")
        print(f"   • {resolution['conflicted_file']}: Client B's conflicted copy")
    
    print("\n" + "="*70)
    print("🎯 DEMO COMPLETE")
    print("="*70)
    print("\n💡 Key Takeaway:")
    print("   Offline conflict detected via version mismatch.")
    print("   Resolution: Keep both versions (conflicted copy created).")
    print("\n")


if __name__ == "__main__":
    asyncio.run(main())
