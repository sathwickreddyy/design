# 🔗 Sticky Sessions Demo with Docker, FastAPI & Nginx

## What are Sticky Sessions?

**Sticky sessions** (also called **session affinity**) ensure that requests from the same client are always routed to the same backend server.

```
Without Sticky Sessions:          With Sticky Sessions (ip_hash):
                                  
Client A ──┬──► Server 1          Client A ────────► Server 1 (always)
           ├──► Server 2          
           └──► Server 3          Client B ────────► Server 2 (always)
                                  
(Round-robin: unpredictable)      (Consistent: predictable)
```

---

## 🎯 When to USE Sticky Sessions

| Situation | Why It Helps |
|-----------|--------------|
| **In-memory sessions** | User login state stored in server RAM |
| **Shopping carts** | Cart data not in shared database |
| **File uploads** | Multi-part uploads to same server |
| **WebSocket connections** | Maintain persistent connections |
| **Legacy applications** | Apps not designed for distributed state |
| **Caching per-user data** | Local cache for user-specific data |

---

## 🚫 When to SKIP Sticky Sessions

| Situation | Why to Skip |
|-----------|-------------|
| **Stateless APIs** | JWT tokens, no server-side state |
| **Shared session store** | Redis/Memcached for sessions |
| **Database-backed state** | All state in PostgreSQL/MySQL |
| **Microservices** | Each request is independent |
| **High availability needs** | Server failure = lost sessions |
| **Auto-scaling** | New servers won't get existing sessions |

---

## 📊 Stickiness Methods Comparison

| Method | How It Works | Pros | Cons |
|--------|--------------|------|------|
| **ip_hash** | Hash of client IP | Simple, no cookies | Breaks with NAT/proxies |
| **Cookie-based** | Server sets sticky cookie | Works with NAT | Requires cookie support |
| **URL hash** | Hash of request URL | Good for caching | Not user-specific |
| **Consistent hashing** | Ring-based distribution | Better failover | More complex |

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Docker Network                        │
│                                                         │
│  ┌─────────┐     ┌─────────────────────────────────┐   │
│  │         │     │         Nginx (ip_hash)          │   │
│  │ Client  │────►│         Port: 8080               │   │
│  │         │     │                                   │   │
│  └─────────┘     └──────────────┬────────────────────┘   │
│                                 │                        │
│                    ┌────────────┼────────────┐          │
│                    │            │            │          │
│                    ▼            ▼            ▼          │
│              ┌─────────┐  ┌─────────┐  ┌─────────┐     │
│              │  app1   │  │  app2   │  │  app3   │     │
│              │ 🟢      │  │ 🔵      │  │ 🟣      │     │
│              │ :8000   │  │ :8000   │  │ :8000   │     │
│              └─────────┘  └─────────┘  └─────────┘     │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

---

## 🚀 Quick Start

### 1. Start the Stack
```bash
docker-compose up --build -d
```

### 2. Test Sticky Sessions
```bash
# Make multiple requests - should always hit SAME server
curl http://localhost:8080
curl http://localhost:8080
curl http://localhost:8080

# Or use the test script
chmod +x test_sticky.sh
./test_sticky.sh
```

### 3. Observe the Behavior
```json
{
  "app_name": "SERVER-1-🟢",
  "process_id": 1,
  "client_ip": "172.18.0.1",
  "message": "Hello from SERVER-1-🟢!"
}
```

**With `ip_hash`**: Every request returns the SAME `app_name`  
**Without `ip_hash`**: Requests cycle through different servers

---

## 🔬 Experiment: Disable Sticky Sessions

1. Edit `nginx/nginx.conf`
2. Comment out the `ip_hash;` line:
   ```nginx
   upstream fastapi_servers {
       # ip_hash;  # <-- COMMENTED OUT
       server app1:8000;
       server app2:8000;
       server app3:8000;
   }
   ```
3. Restart Nginx:
   ```bash
   docker-compose restart nginx
   ```
4. Run the test again - now requests will round-robin!

---

## 📁 Project Structure

```
sticky-sessions/
├── docker-compose.yml    # Orchestrates all containers
├── Dockerfile            # FastAPI app image
├── nginx/
│   └── nginx.conf        # Load balancer config (ip_hash here!)
├── app/
│   ├── main.py           # FastAPI application
│   └── requirements.txt  # Python dependencies
├── test_sticky.sh        # Test script
└── README.md             # This file
```

---

## 🔧 Useful Commands

```bash
# View logs
docker-compose logs -f

# Check which container served request
docker-compose logs nginx | grep upstream

# Stop everything
docker-compose down

# Rebuild after changes
docker-compose up --build -d
```

---

## ⚠️ ip_hash Limitations

1. **NAT/Proxy issues**: Multiple users behind same NAT = same server
2. **IPv6 handling**: Only uses first 3 octets of IPv6
3. **Server changes**: Adding/removing servers can reassign clients
4. **No persistence**: Nginx restart may change assignments

---

## 🎓 Key Takeaways

1. **Sticky sessions trade scalability for simplicity**
2. **Prefer stateless design** when possible (JWT, shared cache)
3. **Use sticky sessions** for legacy apps or specific use cases
4. **ip_hash is simple** but has limitations with NAT
5. **Cookie-based stickiness** is more reliable but complex

---

## 📚 Further Reading

- [Nginx Load Balancing Docs](https://nginx.org/en/docs/http/load_balancing.html)
- [Session Affinity in Kubernetes](https://kubernetes.io/docs/concepts/services-networking/service/#session-affinity)
- [HAProxy Stick Tables](https://www.haproxy.com/documentation/haproxy-configuration-tutorials/stick-tables/)
