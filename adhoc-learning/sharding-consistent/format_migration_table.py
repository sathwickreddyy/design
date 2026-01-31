#!/usr/bin/env python3
"""
Format migration comparison data into a readable table.

Usage:
    curl "http://localhost:8000/migration/compare_approaches" > migration_data.json
    python3 format_migration_table.py migration_data.json
"""

import json
import sys
from tabulate import tabulate

def format_migration_table(data):
    """Format migration data into comparison tables."""
    
    summary = data["summary"]
    
    print("\n" + "="*80)
    print("MIGRATION COMPARISON: Naive (Modulo) vs Consistent Hashing")
    print("="*80)
    
    print(f"\n📊 Analysis completed in: {data['analysis_time_seconds']}s")
    print(f"📝 Total users analyzed: {data['total_users_analyzed']}")
    
    # Summary Table
    print("\n" + "-"*80)
    print("SUMMARY: Movement Statistics")
    print("-"*80)
    
    summary_table = [
        ["Metric", "Consistent Hashing", "Modulo Hashing", "Improvement"],
        ["-"*30, "-"*20, "-"*20, "-"*15],
        [
            "Users that MOVE",
            f"{summary['consistent_hashing']['users_that_move']} ({summary['consistent_hashing']['movement_percentage']}%)",
            f"{summary['modulo_hashing']['users_that_move']} ({summary['modulo_hashing']['movement_percentage']}%)",
            f"-{summary['savings']['fewer_moves']} moves"
        ],
        [
            "Users that STAY",
            f"{summary['consistent_hashing']['users_that_stay']}",
            f"{summary['modulo_hashing']['users_that_stay']}",
            f"+{summary['savings']['fewer_moves']} stay"
        ],
        [
            "Theoretical",
            f"{summary['consistent_hashing']['theoretical_movement']}%",
            f"{summary['modulo_hashing']['theoretical_movement']}%",
            f"{summary['savings']['percentage_improvement']}% better"
        ]
    ]
    
    print(tabulate(summary_table, headers="firstrow", tablefmt="grid"))
    
    # Detailed Migrations Table
    print("\n" + "-"*80)
    print("DETAILED USER MIGRATIONS (First 30)")
    print("-"*80)
    
    detailed_table = []
    detailed_table.append([
        "User ID", 
        "User Hash", 
        "Consistent: Old→New", 
        "Moved?",
        "Modulo: Old→New",
        "Moved?",
        "Who Wins?"
    ])
    detailed_table.append(["-"*8, "-"*12, "-"*18, "-"*7, "-"*15, "-"*7, "-"*10])
    
    for item in data["detailed_migrations"][:30]:
        user_id = item["user_id"]
        user_hash = str(item["user_hash"])[:10] + "..."
        
        cons = item["consistent_hashing"]
        mod = item["modulo_hashing"]
        
        cons_movement = f"{cons['old_shard']} → {cons['new_shard']}"
        cons_moved = "✅ YES" if cons['moved'] else "❌ NO"
        
        mod_movement = f"{mod['old_shard']} → {mod['new_shard']}"
        mod_moved = "✅ YES" if mod['moved'] else "❌ NO"
        
        # Determine winner (who moved less)
        if not cons['moved'] and mod['moved']:
            winner = "🏆 Consistent"
        elif cons['moved'] and not mod['moved']:
            winner = "🏆 Modulo"
        else:
            winner = "🤝 Tie"
        
        detailed_table.append([
            user_id,
            user_hash,
            cons_movement,
            cons_moved,
            mod_movement,
            mod_moved,
            winner
        ])
    
    print(tabulate(detailed_table, headers="firstrow", tablefmt="grid"))
    
    # Virtual Node Analysis for moved users
    print("\n" + "-"*80)
    print("VIRTUAL NODE ANALYSIS (Why Users Move with Consistent Hashing)")
    print("-"*80)
    
    moved_users = [item for item in data["detailed_migrations"] if item["consistent_hashing"]["moved"]]
    
    if moved_users:
        vnode_table = []
        vnode_table.append([
            "User ID",
            "User Hash Position",
            "Old VNode Position",
            "New VNode Position",
            "Reason"
        ])
        vnode_table.append(["-"*8, "-"*18, "-"*18, "-"*18, "-"*50])
        
        for item in moved_users[:10]:
            cons = item["consistent_hashing"]
            reason_short = cons["reason"][:80] + "..." if len(cons["reason"]) > 80 else cons["reason"]
            
            vnode_table.append([
                item["user_id"],
                item["user_hash"],
                cons["old_vnode_position"],
                cons["new_vnode_position"],
                reason_short
            ])
        
        print(tabulate(vnode_table, headers="firstrow", tablefmt="grid"))
    else:
        print("\n⚠️  No users moved with consistent hashing! This seems wrong.")
        print("    This likely means the ring already had shard 2 when calculating old_shard.")
        print("    The comparison is between 2-shard ring vs 3-shard ring,")
        print("    but both calculations used the 3-shard ring.")
    
    # Key Insights
    print("\n" + "="*80)
    print("KEY INSIGHTS")
    print("="*80)
    print(f"""
1. Consistent Hashing: {summary['consistent_hashing']['movement_percentage']}% movement
   - Only users whose next virtual node changed need to move
   - When shard 2 added 150 vnodes, they "captured" ~33% of the hash space
   
2. Modulo Hashing: {summary['modulo_hashing']['movement_percentage']}% movement
   - user_id % 2 → user_id % 3 causes massive redistribution
   - Only users where (id % 2 == id % 3) stay in place
   - That's approximately 1/3 of users, so 2/3 must move
   
3. Savings: {summary['savings']['fewer_moves']} fewer moves ({summary['savings']['percentage_improvement']}% improvement)
   - At scale (1 TB, 1M users), this saves massive migration time
   - Less downtime, less data transfer, less risk
    """)

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python3 format_migration_table.py migration_data.json")
        sys.exit(1)
    
    with open(sys.argv[1], 'r') as f:
        data = json.load(f)
    
    if not data.get("success"):
        print(f"Error: {data}")
        sys.exit(1)
    
    format_migration_table(data)
