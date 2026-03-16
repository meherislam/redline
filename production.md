# Productionizing Redline

```
                         ┌──────────────┐
                         │  CloudFront   │
                         │  (CDN / SPA)  │
                         └──────┬───────┘
                                │
                         ┌──────▼───────┐
                         │     ALB       │
                         │ (TLS + health)│
                         └──────┬───────┘
                                │
                ┌───────────────┼───────────────┐
                │               │               │
         ┌──────▼──────┐ ┌─────▼──────┐ ┌──────▼──────┐
         │  ECS Fargate │ │ ECS Fargate│ │ ECS Fargate │
         │  (FastAPI)   │ │ (FastAPI)  │ │ (FastAPI)   │
         └──────┬───────┘ └─────┬──────┘ └──────┬──────┘
                │               │               │
                └───────┬───────┴───────┬───────┘
                        │               │
                 ┌──────▼──────┐ ┌──────▼──────┐
                 │  PostgreSQL  │ │    Redis     │
                 │  RDS Multi-AZ│ │ ElastiCache  │
                 │  + replica   │ └─────────────┘
                 └──────────────┘

            Document Processing Pipeline

         ┌──────────┐    ┌────────────────┐    ┌──────────┐
         │    S3    │───▶│    Temporal     │───▶│ Reducto  │
         │ (uploads)│    │    Workers      │    │ (parse)  │
         └──────────┘    │ (auto-scaled)   │    └────┬─────┘
                         └────────────────┘         │
                                                    ▼
                                              Chunks → DB
```

## Architecture & Infrastructure

The API layer runs on ECS Fargate behind an ALB — stateless containers with TLS termination, health checks, and auto-scaling on CPU + request count. Fargate eliminates all OS patching and capacity planning. We chose Fargate over Lambda because our API needs persistent DB connection pools and warm startup for consistent p99 latency.

Storage is split by purpose: RDS PostgreSQL (Multi-AZ) with a read replica for the relational data (users, documents, chunks, changes, with a GIN index for full-text search), ElastiCache Redis for caching document metadata and hot chunk pages, and S3 for original uploaded documents. S3 serves as the source of truth — if our chunking strategy improves, we re-process from S3 without re-upload. The frontend is a static SPA deployed to S3 + CloudFront for edge caching.

The biggest architectural upgrade is the document processing pipeline. In the prototype, upload is synchronous. In production, the client uploads directly to S3 via presigned URL (keeping large files off the API servers), which triggers a Temporal workflow: parse the document with Reducto (intelligent chunking that understands headings, tables, and semantic boundaries — a major upgrade over naive paragraph splitting), chunk, index, mark ready. Temporal gives us durable execution with per-step retries, and workers auto-scale based on queue backlog — fully decoupled from API latency. We chose Temporal over SQS + Lambda because document processing is a multi-step workflow with dependencies, not a single-step job. Temporal also provides a built-in UI for debugging stuck workflows in production.

For identity, we'd add `users`, `organizations`, and `org_members` tables, with Auth0 or Clerk handling SSO (SAML, Google, Microsoft), MFA, and session management. Auth is a liability, not a feature — buying eliminates an entire class of security incidents. A JWT validation middleware on every FastAPI request extracts user/org context statelessly. Adding `created_by` to documents and changes completes the audit trail.

## CI/CD & Deployment

`Push to main → GitHub Actions → pytest + lint → Docker build → Push ECR → ECS rolling deploy`. Rolling deployment with minimum healthy = 100% — new tasks start, pass health checks, old tasks drain. Zero downtime. Database migrations run via Alembic as a one-off ECS task *before* deploy, and must be backward-compatible (expand/contract pattern) so old and new code coexist during rollout. Rollback is a single command: redeploy the previous ECR image tag. We chose rolling over blue-green because blue-green complicates migration coordination and requires more infrastructure overhead. At higher scale, canary (route 5% first) is the natural next step.

## Security

Authentication is handled by Auth0 or Clerk, giving us SSO (SAML, Google, Microsoft) and MFA out of the box. Every API request passes through a JWT validation middleware that extracts user and organization context — short-lived tokens (15 min) with refresh tokens so revocation stays tight. Endpoints are scoped by organization: a user can only access documents belonging to their org, enforced at the middleware layer before any business logic runs. Role-based access on the `org_members` table controls who can edit vs view. All services run in private VPC subnets with only the ALB exposed publicly, and encryption is applied at rest (RDS, S3) and in transit (TLS at the ALB).

## Scalability & Resilience

Several patterns are already production-ready in the prototype: batch writes via `insert().values([...])` with configurable `BATCH_SIZE`, prefetched chunk reads via `WHERE id IN (...)`, and optimistic concurrency via version field + ETag.

For scaling, the API auto-scales on ECS (CPU + request count targets), Temporal workers scale on queue backlog, and the read replica offloads search/listing from the primary. PgBouncer handles connection multiplexing as task count grows. If search becomes a bottleneck, we can extract to OpenSearch/ElasticSearch without changing the API contract. If write throughput becomes a bottleneck, we shard by organization — each org's data is fully independent.

For resilience, the system is designed so that every component either self-heals or degrades gracefully. ECS auto-replaces failed tasks behind the ALB. RDS Multi-AZ fails over automatically (~60s), with PgBouncer handling reconnection. If a Temporal worker dies, another picks up the workflow from exactly where it left off — durable execution is Temporal's core guarantee. If Redis goes down, requests fall through to Postgres — slower but fully functional. If the Anthropic API goes down, a circuit breaker stops calling after consecutive failures and returns a clear error; all other features (edits, accept/reject, search) are completely unaffected.

Why single-region? Multi-region adds massive complexity (cross-region DB replication, conflict resolution) for a problem that doesn't exist yet. Multi-AZ covers availability; multi-region waits until latency for geographically distributed users becomes measurable.

## Monitoring & Observability

Structured JSON logs on every request piped to CloudWatch Logs for searchability and filtering. OpenTelemetry tracing for end-to-end request visibility across services. Temporal UI for pipeline monitoring and debugging failed workflows. Key metrics to alert on: API latency, error rates, pipeline backlog depth, and database connection utilization.

## Operations & Cost

Estimated $300-700/mo at early scale. The primary cost drivers are ECS Fargate ($50-150/mo), RDS PostgreSQL ($50-200/mo on burstable T-class instances), Temporal Cloud ($100-200/mo), and the Anthropic API (variable, usage-dependent). Redis and S3 are negligible. The Anthropic API is the largest wildcard — rate limiting per user and caching identical suggestion requests are the main controls to keep it predictable.
