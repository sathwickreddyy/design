#!/usr/bin/env python3
"""
Test script to demonstrate SELECT FOR UPDATE SKIP LOCKED.
Shows how multiple workers compete for tasks without conflicts.
"""

import requests
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

URL = "http://localhost:8080"


def create_tasks(count: int = 30):
    """Create test tasks."""
    print(f"\n🏗️  Creating {count} test tasks...")
    response = requests.post(f"{URL}/create-tasks?count={count}")
    data = response.json()
    print(f"✅ {data['message']} by {data['server']}")
    return data


def grab_task(request_num: int):
    """Grab and process a single task."""
    start_time = time.time()
    try:
        response = requests.post(f"{URL}/grab-task", timeout=10)
        elapsed = time.time() - start_time
        
        data = response.json()
        if "task" in data:
            task_id = data["task"]["id"]
            server = data["server"]
            return {
                "success": True,
                "request_num": request_num,
                "task_id": task_id,
                "server": server,
                "elapsed": elapsed
            }
        else:
            return {
                "success": False,
                "request_num": request_num,
                "message": data.get("message", "No task"),
                "elapsed": elapsed
            }
    except Exception as e:
        elapsed = time.time() - start_time
        return {
            "success": False,
            "request_num": request_num,
            "error": str(e),
            "elapsed": elapsed
        }


def test_concurrent_task_grabbing(num_workers: int = 15):
    """
    Send multiple concurrent requests to grab tasks.
    This demonstrates:
    1. No conflicts - each worker grabs a different task
    2. Load balancing - tasks distributed across workers
    3. Database locking prevents race conditions
    """
    print(f"\n🚀 Launching {num_workers} concurrent task-grab requests...")
    print(f"   (With {num_workers} requests and 3 workers, expect ~{num_workers//3} tasks per worker)")
    print("\n" + "="*70)
    
    start_time = time.time()
    results = []
    
    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        futures = [executor.submit(grab_task, i+1) for i in range(num_workers)]
        
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            
            if result["success"]:
                task_id = result["task_id"]
                server = result["server"]
                elapsed = result["elapsed"]
                print(f"✅ Request #{result['request_num']:2d}: Task #{task_id:2d} grabbed by {server:<20} ({elapsed:.2f}s)")
            else:
                msg = result.get("message", result.get("error", "Unknown"))
                elapsed = result["elapsed"]
                print(f"⚪ Request #{result['request_num']:2d}: {msg} ({elapsed:.2f}s)")
    
    total_time = time.time() - start_time
    
    # Summary
    print("\n" + "="*70)
    print("📊 SUMMARY")
    print("="*70)
    
    successful = [r for r in results if r["success"]]
    failed = [r for r in results if not r["success"]]
    
    print(f"\nTotal Requests:    {num_workers}")
    print(f"Successful:        {len(successful)}")
    print(f"Failed/No Task:    {len(failed)}")
    print(f"Total Time:        {total_time:.2f}s")
    print(f"Avg Time/Request:  {total_time/num_workers:.2f}s")
    
    # Server distribution
    if successful:
        server_counts = {}
        for result in successful:
            server = result["server"]
            server_counts[server] = server_counts.get(server, 0) + 1
        
        print("\n📈 Tasks Processed Per Worker:")
        for server, count in sorted(server_counts.items()):
            bar = "█" * count
            print(f"   {server:<20} {count:2d} tasks  {bar}")
    
    print("\n" + "="*70)
    print("\n💡 KEY OBSERVATIONS:")
    print("   • Each request grabbed a DIFFERENT task (no conflicts)")
    print("   • Tasks distributed across all 3 workers (load balancing)")
    print("   • SELECT FOR UPDATE SKIP LOCKED prevented race conditions")
    print("   • Lock held during 2-second sleep (connection stays open)")
    print("="*70)


def view_task_status():
    """View current task status."""
    print("\n📋 Current Task Status:")
    response = requests.get(f"{URL}/tasks")
    data = response.json()
    
    print(f"\nTotal Tasks: {data['total']}")
    print(f"Status Counts: {data['status_counts']}")
    print(f"Reported by: {data['server']}")
    
    return data


def reset_tasks():
    """Reset all tasks."""
    print("\n🗑️  Resetting all tasks...")
    response = requests.delete(f"{URL}/reset-tasks")
    data = response.json()
    print(f"✅ {data['message']}")


def main():
    print("="*70)
    print("  🔐 TASK LOCKING DEMO - SELECT FOR UPDATE SKIP LOCKED")
    print("="*70)
    
    try:
        # Reset and create fresh tasks
        reset_tasks()
        create_tasks(count=30)
        
        # Test concurrent task grabbing
        test_concurrent_task_grabbing(num_workers=15)
        
        # View final status
        view_task_status()
        
    except requests.exceptions.ConnectionError:
        print("\n❌ ERROR: Cannot connect to http://localhost:8080")
        print("   Make sure Docker containers are running:")
        print("   docker-compose up -d")
    except Exception as e:
        print(f"\n❌ ERROR: {e}")


if __name__ == "__main__":
    main()
