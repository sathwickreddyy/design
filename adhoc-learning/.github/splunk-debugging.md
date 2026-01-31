# Splunk Debugging Guide

## Logging Format

### For Debugging (Default - Use This)
Simple text logging is perfect for troubleshooting:

```python
logger.info(f"User {user_id} routed to shard {shard_id}")
logger.error(f"Failed to connect to database: {error}")
logger.debug(f"Processing request with params: {params}")
```

**Benefits:**
- ✅ Easy to read
- ✅ Easy to grep and search
- ✅ Perfect for troubleshooting
- ✅ No overhead

### For Analytics (Only when needed)
Use structured JSON only when you need aggregation/visualization:

```python
log_data = {
    "event": "event_name",
    "key1": value1,
    "key2": value2
}
logger.info(json.dumps(log_data))
```

**When to use:**
- Aggregating metrics across services
- Building dashboards
- Complex filtering/grouping

**When NOT to use:**
- Basic debugging (overkill)
- Development phase (premature optimization)

## Basic Splunk Searches

### The Universal Search Pattern
Start every search with this template:

```spl
index=main sourcetype="docker:json" "<keyword>"
| spath input=log
| table _time, log
| sort -_time
```

**Breakdown:**
- `index=main` - Where Docker logs are stored
- `sourcetype="docker:json"` - Docker container log format (NOT just "json")
- `"<keyword>"` - Any text you're searching for (use double quotes)
- `spath input=log` - Extracts the actual log message from Docker's JSON wrapper
- `table _time, log` - Show timestamp and log message
- `sort -_time` - Most recent first

### Common Search Patterns

**Search specific container:**
```spl
index=main sourcetype="docker:json" source="*drive_consistent_api*"
| spath input=log
| table _time, log
| sort -_time
```

**Find errors:**
```spl
index=main sourcetype="docker:json" "error" OR "ERROR" OR "failed"
| spath input=log
| table _time, log
| sort -_time
```

**Search with time range:**
```spl
index=main sourcetype="docker:json" "shard" earliest=-1h
| spath input=log
| table _time, log
| sort -_time
```

**Time range options:**
- `earliest=-15m` - Last 15 minutes
- `earliest=-1h` - Last hour
- `earliest=-24h` - Last 24 hours
- `earliest=-7d` - Last 7 days

**Multiple keywords:**
```spl
index=main sourcetype="docker:json" "shard" AND "added"
| spath input=log
| table _time, log
| sort -_time
```

**Search specific field/value:**
```spl
index=main sourcetype="docker:json" "user_id: 123"
| spath input=log
| table _time, log
| sort -_time
```

### Quick Reference

```spl
# All logs from last hour
index=main sourcetype="docker:json" earliest=-1h
| spath input=log
| table _time, log

# Specific container, last 15 minutes
index=main sourcetype="docker:json" source="*container_name*" earliest=-15m
| spath input=log
| table _time, log

# Error logs only
index=main sourcetype="docker:json" "ERROR"
| spath input=log
| table _time, log
| sort -_time

# Multiple containers
index=main sourcetype="docker:json" (source="*api*" OR source="*worker*")
| spath input=log
| table _time, source, log
```

## Debugging Workflow

### When Logs Don't Show Up

**Step 1: Verify container is generating logs**
```bash
docker logs <container_name> --tail 50
```

If logs appear here but not in Splunk, continue to next steps.

**Step 2: Check log file path**
```bash
docker inspect <container_name> --format='{{.LogPath}}'
```

**Step 3: Verify Splunk can read the file**
```bash
docker exec splunk cat /host_docker_logs/<container_id>/<container_id>-json.log | head -5
```

**Step 4: Check Splunk ingestion**
```spl
index=main sourcetype="docker:json"
| spath input=log
| table _time, log
| head 10
```

If you see ANY logs, Splunk is working. Refine your search.

**Step 5: Build query progressively**
```spl
# Step 1: Find any logs
index=main sourcetype="docker:json"

# Step 2: Add container filter
index=main sourcetype="docker:json" source="*container_name*"

# Step 3: Parse and display
index=main sourcetype="docker:json" source="*container_name*"
| spath input=log
| table _time, log

# Step 4: Add keyword filter
index=main sourcetype="docker:json" source="*container_name*" "keyword"
| spath input=log
| table _time, log
```

## Common Mistakes

❌ **Wrong sourcetype**
```spl
# WRONG
index=main sourcetype=json

# RIGHT
index=main sourcetype="docker:json"
```

❌ **Missing spath**
```spl
# WRONG - shows Docker JSON wrapper
index=main sourcetype="docker:json" "keyword"
| table _time, log

# RIGHT - extracts actual log message
index=main sourcetype="docker:json" "keyword"
| spath input=log
| table _time, log
```

❌ **Single quotes**
```spl
# WRONG
index=main sourcetype='docker:json' 'keyword'

# RIGHT
index=main sourcetype="docker:json" "keyword"
```

❌ **No time range on broad searches**
```spl
# SLOW - searches all history
index=main sourcetype="docker:json"

# FAST - only recent logs
index=main sourcetype="docker:json" earliest=-1h
```

❌ **Overcomplicated first attempt**
Start simple, then add filters:
```spl
# Start here
index=main sourcetype="docker:json" "keyword"
| spath input=log
| table _time, log

# Then refine
index=main sourcetype="docker:json" source="*container*" "keyword" earliest=-1h
| spath input=log
| table _time, log
| sort -_time
```

## Pro Tips

1. **Always use the base template** - copy/paste, then modify
2. **Start broad, narrow down** - find any logs first, then filter
3. **Use `head` for testing** - add `| head 10` to limit results while testing queries
4. **Check time range** - if no results, try expanding time window
5. **Use wildcards** - `source="*api*"` matches any container with "api" in the name
6. **Case sensitivity** - searches are case-insensitive by default
