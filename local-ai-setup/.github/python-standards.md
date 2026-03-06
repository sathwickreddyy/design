# Python Coding Standards

## Import Organization
Always place imports at the top of the file, organized in three groups:

```python
# Standard Library
import os
import sys
import logging
from typing import List, Dict, Any

# Third Party
import psycopg2
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# Local/Application
from consistent_hash import ConsistentHashRing
from database import get_connection
```

**Rules:**
- One blank line between groups
- Alphabetical within each group
- No wildcard imports (`from module import *`)

## Code Structure

### Avoid "God Methods"
Break down complex logic into small, testable functions:

❌ **Bad:**
```python
def process_user_request(user_id, data):
    # 200 lines of mixed logic
    # validation, database, business logic, response formatting
    pass
```

✅ **Good:**
```python
def validate_user_data(data: Dict) -> bool:
    """Validate incoming user data."""
    pass

def get_user_shard(user_id: int) -> int:
    """Determine target shard for user."""
    pass

def insert_user_record(shard_id: int, data: Dict) -> int:
    """Insert record into specific shard."""
    pass

def process_user_request(user_id: int, data: Dict) -> Dict:
    """
    Process user request through validation, routing, and insertion.
    
    Orchestrates the full request flow.
    """
    validate_user_data(data)
    shard_id = get_user_shard(user_id)
    record_id = insert_user_record(shard_id, data)
    return {"record_id": record_id, "shard_id": shard_id}
```

**Benefits:**
- Easy to test individual pieces
- Easy to reuse components
- Easy to understand and maintain
- Clear separation of concerns

## Logging

### Comprehensive Logging Required
Every logical branch and major state change must be logged:

```python
def add_shard(shard_id: int):
    logger.info(f"Adding shard {shard_id} to ring")
    
    if shard_id in self.shards:
        logger.warning(f"Shard {shard_id} already exists")
        return
    
    try:
        # Add shard logic
        logger.info(f"Successfully added shard {shard_id}")
    except Exception as e:
        logger.error(f"Failed to add shard {shard_id}: {e}")
        raise
```

**What to log:**
- Entry/exit of major functions
- Decision points (if/else branches)
- External calls (database, API)
- Errors and warnings
- State changes

**What NOT to log:**
- Passwords or secrets
- Full request bodies (may contain PII)
- Inside tight loops (use sampling)

### Log Levels
- `DEBUG` - Detailed diagnostic info (development only)
- `INFO` - General informational messages
- `WARNING` - Something unexpected but not critical
- `ERROR` - Serious problem, function failed
- `CRITICAL` - System-level failure

## Documentation

### Every Method Must Have a Docstring
Required sections:

```python
def get_shard(self, key: str) -> int:
    """
    Find which shard a key (user_id) belongs to.
    
    Purpose:
        Route a user to their assigned shard using consistent hashing.
    
    Consumers:
        Data ingestion service to determine target shard for writes.
    
    Logic:
        1. Hash the key to get its position on the ring
        2. Binary search to find the next virtual node clockwise
        3. Return the physical shard that owns that virtual node
    
    Args:
        key: Identifier to route (e.g., user_id)
        
    Returns:
        int: Physical shard ID
        
    Raises:
        ValueError: If no shards are available
    """
    pass
```

**Required sections:**
- **Purpose:** What it does (one sentence)
- **Consumers:** Who/what calls it
- **Logic:** Simple numbered steps
- **Args:** Parameter descriptions
- **Returns:** What it returns
- **Raises:** What exceptions it might raise

### Update Outdated Documentation
If you encounter missing or outdated docs in existing code:
- **Update it immediately** as part of the task
- Don't skip it, don't leave TODOs
- Documentation debt compounds quickly

## Type Hints
Use type hints for function signatures:

```python
def process_data(
    user_id: int,
    items: List[str],
    config: Dict[str, Any]
) -> Dict[str, int]:
    """Process data and return summary."""
    pass
```

**Benefits:**
- Self-documenting
- IDE autocomplete
- Catch type errors early

## Error Handling

### Specific Exceptions
Catch specific exceptions, not generic:

❌ **Bad:**
```python
try:
    conn = connect_to_db()
except:
    print("Error")
```

✅ **Good:**
```python
try:
    conn = connect_to_db()
except psycopg2.OperationalError as e:
    logger.error(f"Database connection failed: {e}")
    raise
except psycopg2.Error as e:
    logger.error(f"Database error: {e}")
    raise
```

### Always Log Before Re-raising
```python
try:
    result = risky_operation()
except ValueError as e:
    logger.error(f"Invalid value in risky_operation: {e}")
    raise  # Re-raise after logging
```

## Configuration

### Use Environment Variables
Never hardcode configuration:

❌ **Bad:**
```python
DB_HOST = "localhost"
DB_PORT = 5432
```

✅ **Good:**
```python
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
```

### Provide Sensible Defaults
- Defaults for development
- Required for production (fail fast if missing)

```python
# Required in production
API_KEY = os.getenv("API_KEY")
if not API_KEY:
    raise ValueError("API_KEY environment variable required")

# Optional with default
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
```

## Code Style

### Naming Conventions
- `snake_case` for functions and variables
- `PascalCase` for classes
- `UPPER_SNAKE_CASE` for constants
- Descriptive names (no single letters except loop counters)

### Line Length
- Max 100 characters (not 80, not 120)
- Break long lines logically

### Blank Lines
- Two blank lines between top-level functions/classes
- One blank line between methods in a class
- Use blank lines to separate logical sections within functions

## Testing Considerations

### Write Testable Code
```python
# Testable - pure function
def calculate_shard(user_id: int, num_shards: int) -> int:
    return user_id % num_shards

# Hard to test - mixed concerns
def process_and_save(user_id: int):
    shard = calculate_shard(user_id, 3)
    db = connect_database()
    db.insert(user_id, shard)
```

Separate:
- Business logic (pure functions)
- I/O operations (database, network)
- External dependencies

Makes testing easier and code more maintainable.
