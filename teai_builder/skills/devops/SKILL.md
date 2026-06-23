---
name: devops
description: Docker, GitHub Actions CI/CD, health endpoints, environment/secrets management, rollback strategies.
metadata: {"teai_builder": {"emoji": "⚙️"}}
---

# DevOps Patterns

## Dockerfile Best Practices

### Node.js multi-stage build
```dockerfile
FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci --frozen-lockfile
COPY . .
RUN npm run build

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
RUN addgroup --system --gid 1001 nodejs && adduser --system --uid 1001 nextjs
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public
USER nextjs
EXPOSE 3000
CMD ["node", "server.js"]
```

### Python multi-stage build
```dockerfile
FROM python:3.12-slim AS builder
WORKDIR /app
RUN pip install poetry
COPY pyproject.toml poetry.lock ./
RUN poetry export -f requirements.txt --output requirements.txt --without-hashes
RUN pip install --prefix=/install -r requirements.txt

FROM python:3.12-slim AS runner
WORKDIR /app
COPY --from=builder /install /usr/local
COPY . .
RUN adduser --system --uid 1001 appuser
USER appuser
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### .dockerignore
```
node_modules
.next
.git
.env
*.log
coverage
__pycache__
.pytest_cache
```

## GitHub Actions CI

`.github/workflows/ci.yml`:
```yaml
name: CI
on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: '20'
          cache: 'npm'
      - run: npm ci
      - run: npm run lint
      - run: npm run type-check
      - run: npm test
      - run: npm run build
```

## GitHub Actions Deploy (Vercel)

`.github/workflows/deploy.yml`:
```yaml
name: Deploy
on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: amondnet/vercel-action@v25
        with:
          vercel-token: ${{ secrets.VERCEL_TOKEN }}
          vercel-org-id: ${{ secrets.VERCEL_ORG_ID }}
          vercel-project-id: ${{ secrets.VERCEL_PROJECT_ID }}
          vercel-args: '--prod'
```

## Health Endpoint

Always add a `/health` endpoint to every backend:

```typescript
// Express / Fastify
app.get('/health', (req, res) => {
  res.json({ status: 'ok', timestamp: new Date().toISOString() });
});
```

```python
# FastAPI
@app.get("/health")
def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}
```

Kubernetes-style: add `readinessProbe` and `livenessProbe` if deploying to k8s.

## Environment & Secrets

**Never commit secrets. Never hardcode values.**

Pattern:
1. `.env.example` — committed, documents all required vars with descriptions
2. `.env` — in `.gitignore`, actual values for local dev
3. Platform env vars — set via platform CLI or dashboard for production

```bash
# .env.example
DATABASE_URL=postgresql://user:password@localhost:5432/myapp
JWT_SECRET=your-secret-here-min-32-chars
NEXT_PUBLIC_API_URL=http://localhost:3000
```

Generate strong secrets:
```bash
openssl rand -hex 32  # JWT secret
```

## Rollback

**Vercel:** `vercel rollback` — instantly restores previous deployment
**Railway:** Redeploy from a previous Git commit via dashboard
**Render:** Dashboard → manual deploy from previous commit hash
**Fly.io:** `fly releases list` → `fly deploy --image <previous-image>`
**VPS:** `git checkout <previous-tag>` → `npm run build` → `systemctl restart app`
