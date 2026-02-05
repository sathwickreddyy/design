"""
Demo: Online Conflict Scenario
Simulates two clients editing the same file simultaneously while connected,
causing a race condition
"""

import asyncio
import logging
from sync_client import SyncClient

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("demo_online")


async def main():
    print("\n" + "="*70)
    print("🎬 ONLINE CONFLICT SCENARIO DEMO")
    print("="*70 + "\n")
    
    # Initialize two clients
    client_a = SyncClient("ClientA")
    client_b = SyncClient("ClientB")
    
    file_id = "shared_doc.txt"
    initial_content = "Shared document - Version 1"
    
    print("\n📝 STEP 1: Client A creates initial file")
    print("-" * 70)
    await client_a.create_file(file_id, initial_content)
    await asyncio.sleep(0.5)
    
    print("\n📥 STEP 2: Both clients download the file (v1)")
    print("-" * 70)
    await client_a.download(file_id)
    await client_b.download(file_id)
    await asyncio.sleep(0.5)
    
    print("\n✏️ STEP 3: BOTH clients edit simultaneously (still online)")
    print("-" * 70)
    print("🔄 Both clients are connected and editing at the same time...")
    client_a.edit_file(file_id, "PYTHON is the best language!")
    await asyncio.sleep(0.1)  # Tiny delay to show concurrency
    client_b.edit_file(file_id, "JAVASCRIPT is the best language!")
    await asyncio.sleep(0.5)
    
    print("\n⚡ STEP 4: RACE CONDITION - Both sync at nearly same time")
    print("-" * 70)
    print("📤 Both clients racing to upload their changes...")
    
    # Create tasks for parallel upload (race condition)
    task_a = asyncio.create_task(client_a.upload(file_id))
    task_b = asyncio.create_task(client_b.upload(file_id))
    
    # Wait for both uploads
    results = await asyncio.gather(task_a, task_b)
    result_a, result_b = results
    
    await asyncio.sleep(0.5)
    
    print("\n" + "="*70)
    print("📊 RACE RESULTS")
    print("="*70)
    
    # Determine winner
    winner = None
    loser = None
    loser_client = None
    
    if result_a["status"] == "success" and result_b["status"] == "conflict":
        winner = "Client A"
        loser = "Client B"
        loser_client = client_b
        loser_result = result_b
        winner_content = client_a.local_files[file_id]["content"]
    elif result_b["status"] == "success" and result_a["status"] == "conflict":
        winner = "Client B"
        loser = "Client A"
        loser_client = client_a
        loser_result = result_a
        winner_content = client_b.local_files[file_id]["content"]
    else:
        print("⚠️  Unexpected race result!")
        return
    
    print(f"\n🏆 Winner: {winner}")
    print(f"   • Upload succeeded (v1 → v2)")
    print(f"   • Content: \"{winner_content}\"")
    
    print(f"\n❌ Loser: {loser}")
    print(f"   • Upload rejected (version conflict)")
    print(f"   • Reason: Server version already updated to v2")
    
    print("\n🔧 STEP 5: Loser resolves conflict")
    print("-" * 70)
    await asyncio.sleep(0.5)
    
    if loser_result["status"] == "conflict":
        resolution = await loser_client.resolve_conflict_keep_both(
            file_id,
            loser_result["conflict_data"]
        )
        
        await asyncio.sleep(0.5)
        print("\n" + "="*70)
        print("✅ CONFLICT RESOLVED")
        print("="*70)
        print(f"\n📁 Final State:")
        print(f"   • {file_id}: Winner's version (v2)")
        print(f"   • {resolution['conflicted_file']}: Loser's conflicted copy")
    
    print("\n" + "="*70)
    print("🎯 DEMO COMPLETE")
    print("="*70)
    print("\n💡 Key Takeaway:")
    print("   Online conflict detected via optimistic locking.")
    print("   First-write-wins: Server atomically checks version.")
    print("   Loser must retry after fetching latest version.")
    print("\n")


if __name__ == "__main__":
    asyncio.run(main())
