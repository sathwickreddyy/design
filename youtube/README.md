# 🎥 Distributed Video Transcoding Engine

## 🏗 System Architecture
- **API:** FastAPI (Submits Workflows)
- **Orchestrator:** Temporal (Durable Execution)
- **Workers:** Python + FFmpeg (Stateless Compute)
- **Storage:** Minio (S3-Compatible)

## 📊 Milestone Tracker

| Phase | Goal | Status | Key Learning |
| :--- | :--- | :--- | :--- |
| **M0** | Infra Scaffolding | 🏗 In Progress | Docker-compose for Distributed systems |
| **M1** | Hello Transcode | 🔘 Todo | Temporal Workflows & Activity patterns |
| **M2** | Parallel DAG | 🔘 Todo | Handling high-write/compute fan-out |
| **M3** | Failure Injection| 🔘 Todo | Idempotency & Retries (Staff Skill) |

## 🛠 Design Decisions
- **Why Temporal?** To avoid writing complex state-machine logic for retries.
- **Why S3/Minio?** Decoupling storage from compute; allows workers to scale.