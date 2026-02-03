# Docker & Infrastructure Standards

## Network Configuration
- **External Network Required:** All `docker-compose.yml` files must use the external network `observability-net`.
- **Never use default bridge networks** - they isolate containers from monitoring infrastructure.

```yaml
networks:
  observability-net:
    external: true
```

## Logging Configuration
All containers must use the `json-file` logging driver with rotation to prevent disk space issues:

```yaml
logging:
  driver: "json-file"
  options:
    max-size: "10m"
    max-file: "3"
```

**Why:**
- Limits each container to 30MB total logs (10MB × 3 files)
- Automatic rotation when files reach size limit
- Compatible with Splunk monitoring
- Prevents runaway log growth

## Container Labels
Add consistent metadata labels for better searchability and monitoring:

```yaml
labels:
  project_name: "<project-name>"
  service_type: "<api|database|worker>"
```

**Common service types:**
- `api` - HTTP/REST APIs
- `database` - PostgreSQL, MySQL, etc.
- `worker` - Background job processors
- `cache` - Redis, Memcached
- `proxy` - Nginx, HAProxy

## Health Checks
Always define health checks for services that other containers depend on:

```yaml
healthcheck:
  test: ["CMD-SHELL", "pg_isready -U user -d dbname"]
  interval: 5s
  timeout: 5s
  retries: 5
```

Use `depends_on` with `condition: service_healthy` to ensure proper startup order.

## Port Mapping
- **External ports:** Use consistent port ranges (e.g., 5432, 5433, 5434 for multiple DB instances)
- **Avoid port conflicts:** Check what's running before adding new services
- **Document all exposed ports** in README.md

## Volume Management
- **Named volumes** for data that should persist (`postgres-data`, `redis-data`)
- **Bind mounts** for configuration files that need editing (`./config:/etc/app/config:ro`)
- **Always use `:ro` (read-only)** for configuration mounts when possible

## Log Cleanup
Logs are automatically managed by Docker's rotation, but manual cleanup if needed:

```bash
# Remove logs for stopped containers
docker system prune

# Fresh start with empty logs
docker-compose down
docker-compose up -d
```
