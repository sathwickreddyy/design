#!/usr/bin/env python3
"""
Test script to demonstrate sticky sessions vs load balancing.

- test_sticky(): Uses requests.Session() - should hit SAME server (with ip_hash)
- test_balanced(): No session - shows raw load balancer behavior
"""

import requests
from collections import Counter

URL = "http://localhost:8080"


def test_sticky(num_requests: int = 100) -> dict:
    """
    Send requests using a Session object.
    With ip_hash enabled, all requests should hit the same server.
    """
    hits = Counter()
    
    with requests.Session() as session:
        for _ in range(num_requests):
            try:
                response = session.get(URL, timeout=5)
                data = response.json()
                server_name = data.get("app_name", "unknown")
                hits[server_name] += 1
            except requests.RequestException as e:
                hits["ERROR"] += 1
    
    return dict(hits)


def test_balanced(num_requests: int = 100) -> dict:
    """
    Send requests WITHOUT a session.
    Shows raw load balancer behavior (ip_hash still applies based on IP).
    """
    hits = Counter()
    
    for _ in range(num_requests):
        try:
            response = requests.get(URL, timeout=5)
            data = response.json()
            server_name = data.get("app_name", "unknown")
            hits[server_name] += 1
        except requests.RequestException as e:
            hits["ERROR"] += 1
    
    return dict(hits)


def print_summary(title: str, results: dict, total: int):
    """Print a formatted summary table."""
    print(f"\n{'='*50}")
    print(f"  {title}")
    print(f"{'='*50}")
    print(f"{'Server':<25} {'Hits':>10} {'Percentage':>12}")
    print(f"{'-'*50}")
    
    for server, count in sorted(results.items()):
        pct = (count / total) * 100
        bar = "█" * int(pct / 5)  # Visual bar
        print(f"{server:<25} {count:>10} {pct:>10.1f}%  {bar}")
    
    print(f"{'-'*50}")
    print(f"{'TOTAL':<25} {total:>10}")


def main():
    NUM_REQUESTS = 100
    
    print("\n🔗 STICKY SESSIONS TEST")
    print("=" * 50)
    print(f"Sending {NUM_REQUESTS} requests to {URL}")
    print("=" * 50)
    
    # Test with Session (sticky)
    print("\n⏳ Running test_sticky() with requests.Session()...")
    sticky_results = test_sticky(NUM_REQUESTS)
    print_summary("TEST 1: With Session (Sticky)", sticky_results, NUM_REQUESTS)
    
    # Test without Session (balanced)
    print("\n⏳ Running test_balanced() without Session...")
    balanced_results = test_balanced(NUM_REQUESTS)
    print_summary("TEST 2: Without Session (Balanced)", balanced_results, NUM_REQUESTS)
    
    # Analysis
    print("\n" + "=" * 50)
    print("  📊 ANALYSIS")
    print("=" * 50)
    
    sticky_servers = len([k for k in sticky_results if k != "ERROR"])
    balanced_servers = len([k for k in balanced_results if k != "ERROR"])
    
    if sticky_servers == 1 and balanced_servers == 1:
        print("✅ ip_hash is ENABLED - All requests hit the same server")
        print("   (Both tests show stickiness because ip_hash uses client IP)")
        print("\n💡 To see round-robin: Comment out 'ip_hash;' in nginx.conf")
    elif sticky_servers > 1 or balanced_servers > 1:
        print("🔄 Requests are being distributed across servers")
        print("   (ip_hash may be disabled, showing round-robin)")
    
    print("\n" + "=" * 50)


if __name__ == "__main__":
    main()
