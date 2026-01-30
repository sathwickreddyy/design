"""
Consistent Hashing Implementation

Purpose:
    Minimize data movement when adding/removing shards.
    With modulo sharding (user_id % N), adding a shard causes ~66% data movement.
    With consistent hashing, only ~33% of data moves (approximately 1/N).

How It Works:
    1. Hash both shards and users to the same number space (0 to 2^32-1)
    2. Place them on a circular "ring"
    3. Each user is assigned to the next shard clockwise on the ring
    4. Use virtual nodes to ensure even distribution

Consumers:
    FastAPI ingestion service for routing user data to shards.
"""

import bisect
import hashlib
import logging
import json
from typing import List, Dict, Any, Tuple

logger = logging.getLogger(__name__)


class ConsistentHashRing:
    """
    Consistent Hash Ring with Virtual Nodes
    
    Purpose:
        Distribute data evenly across shards with minimal movement on shard changes.
    
    Logic:
        1. Create multiple virtual nodes per physical shard (default: 150)
        2. Hash each virtual node to a position on the ring (0 to 2^32-1)
        3. Sort all positions for fast lookup
        4. For each key (user_id), find the next virtual node clockwise
        5. Return the physical shard that owns that virtual node
    """
    
    def __init__(self, virtual_nodes_per_shard: int = 150):
        """
        Initialize the consistent hash ring.
        
        Args:
            virtual_nodes_per_shard: Number of virtual nodes per physical shard.
                                    More vnodes = better distribution, slightly slower lookup.
                                    150 is a good balance.
        """
        self.virtual_nodes_per_shard = virtual_nodes_per_shard
        self.ring: List[Tuple[int, int]] = []  # Sorted list of (hash_position, shard_id)
        self.shards: set = set()  # Track active shard IDs
        
        logger.info(f"Initialized ConsistentHashRing with {virtual_nodes_per_shard} virtual nodes per shard")
    
    def _hash(self, key: str) -> int:
        """
        Hash a string to a 32-bit integer position on the ring.
        
        Purpose:
            Convert any string (shard name, user ID, etc.) to a number 0 to 2^32-1.
        
        Logic:
            1. Use MD5 for fast, well-distributed hashing
            2. Take first 4 bytes of the hash
            3. Convert to unsigned 32-bit integer
        
        Args:
            key: String to hash (e.g., "shard_0_vnode_42" or "user_123")
            
        Returns:
            int: Hash value between 0 and 2^32-1 (4,294,967,295)
        """
        hash_bytes = hashlib.md5(key.encode()).digest()
        hash_value = int.from_bytes(hash_bytes[:4], 'big')
        
        logger.debug(f"Hash: {key} -> {hash_value}")
        return hash_value
    
    def add_shard(self, shard_id: int):
        """
        Add a shard to the ring with virtual nodes.
        
        Purpose:
            Register a new physical shard by creating virtual nodes distributed around the ring.
        
        Logic:
            1. For each virtual node (0 to virtual_nodes_per_shard):
                - Create unique key: "shard_{id}_vnode_{n}"
                - Hash it to get ring position
                - Insert into sorted ring
            2. Track which positions belong to which physical shard
        
        Args:
            shard_id: Physical shard identifier (e.g., 0, 1, 2)
        """
        if shard_id in self.shards:
            logger.warning(f"Shard {shard_id} already exists in ring")
            return
        
        logger.info(f"Adding shard {shard_id} to ring with {self.virtual_nodes_per_shard} virtual nodes")
        
        vnode_positions = []
        
        for vnode_num in range(self.virtual_nodes_per_shard):
            # Create unique virtual node identifier
            vnode_key = f"shard_{shard_id}_vnode_{vnode_num}"
            
            # Hash to get position on ring
            hash_position = self._hash(vnode_key)
            
            # Insert into ring maintaining sorted order
            bisect.insort(self.ring, (hash_position, shard_id))
            
            vnode_positions.append(hash_position)
        
        self.shards.add(shard_id)
        
        # Log structured data for Splunk
        log_data = {
            "event": "shard_added",
            "shard_id": shard_id,
            "virtual_nodes": self.virtual_nodes_per_shard,
            "total_ring_size": len(self.ring),
            "sample_positions": sorted(vnode_positions)[:5],  # First 5 for inspection
            "ring_coverage": {
                "min_position": min(vnode_positions),
                "max_position": max(vnode_positions),
                "range": "0 to 4294967295"
            }
        }
        logger.info(f"SPLUNK: {json.dumps(log_data)}")
    
    def remove_shard(self, shard_id: int):
        """
        Remove a shard from the ring.
        
        Purpose:
            Deregister a physical shard by removing all its virtual nodes.
        
        Logic:
            1. Filter out all ring entries where physical shard matches shard_id
            2. Update ring and shard tracking
        
        Args:
            shard_id: Physical shard identifier to remove
        """
        if shard_id not in self.shards:
            logger.warning(f"Shard {shard_id} not found in ring")
            return
        
        logger.info(f"Removing shard {shard_id} from ring")
        
        # Remove all virtual nodes for this shard
        self.ring = [(pos, sid) for pos, sid in self.ring if sid != shard_id]
        self.shards.remove(shard_id)
        
        log_data = {
            "event": "shard_removed",
            "shard_id": shard_id,
            "remaining_ring_size": len(self.ring),
            "remaining_shards": list(self.shards)
        }
        logger.info(f"SPLUNK: {json.dumps(log_data)}")
    
    def get_shard(self, key: str) -> int:
        """
        Find which shard a key (user_id) belongs to.
        
        Purpose:
            Route a user to their assigned shard using consistent hashing.
        
        Logic:
            1. Hash the key to get its position on the ring
            2. Binary search to find the next virtual node clockwise
            3. Return the physical shard that owns that virtual node
        
        Consumers:
            Data ingestion service to determine target shard for writes.
        
        Args:
            key: Identifier to route (e.g., user_id)
            
        Returns:
            int: Physical shard ID
            
        Raises:
            ValueError: If no shards are available
        """
        if not self.ring:
            raise ValueError("No shards available in the hash ring")
        
        # Hash the key to get position on ring
        key_hash = self._hash(str(key))
        
        # Binary search for next virtual node clockwise
        # ring = [(pos1, shard1), (pos2, shard2), ...]
        ring_positions = [pos for pos, _ in self.ring]
        
        # Find insertion point (next position clockwise)
        index = bisect.bisect_right(ring_positions, key_hash)
        
        # Wrap around if past the end
        if index == len(self.ring):
            index = 0
        
        # Get the physical shard at this position
        _, shard_id = self.ring[index]
        
        # Log routing decision for Splunk visualization
        log_data = {
            "event": "routing_decision",
            "key": key,
            "key_hash": key_hash,
            "next_vnode_position": self.ring[index][0],
            "assigned_shard": shard_id,
            "total_vnodes_checked": len(self.ring),
            "search_wrapped": index == 0 and key_hash > ring_positions[-1]
        }
        logger.debug(f"SPLUNK: {json.dumps(log_data)}")
        
        return shard_id
    
    def get_ring_state(self) -> Dict[str, Any]:
        """
        Get current state of the hash ring for visualization.
        
        Purpose:
            Provide detailed ring state for monitoring and debugging.
        
        Returns:
            dict: Ring state with distribution statistics
        """
        if not self.ring:
            return {"shards": [], "virtual_nodes": 0, "distribution": {}}
        
        # Calculate distribution per shard
        distribution = {}
        for _, shard_id in self.ring:
            distribution[shard_id] = distribution.get(shard_id, 0) + 1
        
        # Get ring coverage for each shard
        shard_ranges = {}
        for shard_id in self.shards:
            positions = [pos for pos, sid in self.ring if sid == shard_id]
            shard_ranges[shard_id] = {
                "virtual_nodes": len(positions),
                "min_position": min(positions),
                "max_position": max(positions),
                "sample_positions": sorted(positions)[:10]  # First 10 for inspection
            }
        
        state = {
            "total_shards": len(self.shards),
            "shard_ids": sorted(list(self.shards)),
            "total_virtual_nodes": len(self.ring),
            "virtual_nodes_per_shard": self.virtual_nodes_per_shard,
            "distribution": distribution,
            "shard_ranges": shard_ranges,
            "ring_size_range": "0 to 4,294,967,295 (2^32-1)"
        }
        
        logger.info(f"SPLUNK: {json.dumps({'event': 'ring_state', 'state': state})}")
        return state
    
    def analyze_redistribution(self, new_shard_id: int) -> Dict[str, Any]:
        """
        Analyze impact of adding a new shard WITHOUT actually adding it.
        
        Purpose:
            Predict data movement before performing migration.
        
        Logic:
            1. Simulate adding new shard to a temporary ring
            2. For each existing key, check if routing changes
            3. Calculate movement statistics
        
        Args:
            new_shard_id: ID of shard to simulate adding
            
        Returns:
            dict: Analysis showing expected data movement
        """
        logger.info(f"Analyzing impact of adding shard {new_shard_id}")
        
        # Create temporary ring with new shard
        temp_ring = ConsistentHashRing(self.virtual_nodes_per_shard)
        
        # Add all existing shards
        for shard_id in self.shards:
            temp_ring.add_shard(shard_id)
        
        # Add the new shard
        temp_ring.add_shard(new_shard_id)
        
        # Simulate data distribution
        sample_size = 10000
        movements = 0
        
        for user_id in range(sample_size):
            old_shard = self.get_shard(user_id)
            new_shard = temp_ring.get_shard(user_id)
            
            if old_shard != new_shard:
                movements += 1
        
        movement_percentage = (movements / sample_size) * 100
        
        analysis = {
            "event": "redistribution_analysis",
            "new_shard_id": new_shard_id,
            "current_shards": len(self.shards),
            "new_total_shards": len(self.shards) + 1,
            "sample_size": sample_size,
            "keys_that_move": movements,
            "keys_that_stay": sample_size - movements,
            "movement_percentage": round(movement_percentage, 2),
            "theoretical_movement": round(100 / (len(self.shards) + 1), 2),
            "difference": abs(movement_percentage - (100 / (len(self.shards) + 1)))
        }
        
        logger.info(f"SPLUNK: {json.dumps(analysis)}")
        return analysis
