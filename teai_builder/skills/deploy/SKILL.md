---
name: deploy
description: Deployment decision tree and step-by-step guides for Vercel, Railway, Render, Fly.io, and VPS — from build to live URL with health verification.
metadata: {"teai_builder": {"emoji": "🚀"}}
---

# Deployment Guide

## Verified Deploy Is a Hard Gate (do this every time)

A deploy is **not done** until it is *verified live*. "I ran the deploy command"
is never proof. The CEO must not tell the user a site is live, and must not
advance the project to `deploy`, until ALL of the following pass:

1. **Pre-deploy build check** — run `run_verification(project="<name>")` and
   confirm it returns `status: pass`. A failing build never deploys.
2. **Deploy** to the chosen platform (sections below).
3. **Live health check** — `curl -fsS -o /dev/null -w "%{http_code}" <live-url>`
   (or `<live-url>/health` for APIs) returns **200**. Retry for up to ~60s to
   allow cold starts; if it never returns 200, the deploy FAILED — fix and redeploy.
4. **Live screenshot gate** — capture the live URL with the `screenshot` tool
   and push it to the canvas: `canvas(type="url", content="<live-url>")`. Visually
   confirm it is the real app, not an error/placeholder page.
5. **Record + advance** — record the live URL as an artifact and only then
   `project_gate(action="advance", project="<name>", phase="deploy")`.

If any step fails, the project stays in its current phase. Never paper over a
failed deploy by reporting success.

## Decision Tree: Choosing a Platform

```
What are you deploying?
├── Static site / Frontend only (React, Next.js static export, Vue)
│   └── → Vercel or Netlify (best DX, global CDN, free tier)
│
├── Full-stack app (Next.js + API routes, Nuxt, SvelteKit)
│   └── → Vercel (fullstack) or Railway (more control)
│
├── Separate frontend + backend API
│   ├── Frontend → Vercel
│   └── Backend API → Railway or Render
│
├── Backend API only (Node.js, Python FastAPI, Go)
│   └── → Railway (easy) or Render (free tier with sleep) or Fly.io (containers)
│
├── Containerized app (Dockerfile required)
│   └── → Fly.io (best container DX) or Railway (Docker support)
│
└── VPS / self-hosted (user has a server)
    └── → nginx + systemd + certbot
```

## Vercel Deployment

```bash
npm i -g vercel
vercel login
vercel --prod
# Follow prompts: link project, set root dir, set build command
```

Set environment variables:
```bash
vercel env add DATABASE_URL production
vercel env add JWT_SECRET production
```

Custom domain:
```bash
vercel domains add yourdomain.com
# Update DNS: CNAME www → cname.vercel-dns.com
```

Verify: `curl https://<project>.vercel.app/api/health`

## Netlify Deployment

Best for static sites and SPAs (also supports serverless functions in `netlify/functions`).

```bash
npm i -g netlify-cli
netlify login
# Build first, then deploy the publish dir (e.g. dist/ or build/):
npm run build
netlify deploy --prod --dir=dist
```

Non-interactive / CI (token-based):
```bash
export NETLIFY_AUTH_TOKEN=<token>
netlify deploy --prod --dir=dist --site=<site-id>
```

`netlify.toml` for build config:
```toml
[build]
  command = "npm run build"
  publish = "dist"

[[redirects]]   # SPA fallback
  from = "/*"
  to = "/index.html"
  status = 200
```

Environment variables:
```bash
netlify env:set JWT_SECRET <value>
```

Verify: the CLI prints a `Website URL`. Run the live health check + screenshot
gate against it before declaring success.

## Railway Deployment

```bash
npm i -g @railway/cli
railway login
railway init
railway up
```

Add Postgres:
```bash
railway add --plugin postgresql
# DATABASE_URL is auto-injected as env var
```

Set environment variables:
```bash
railway variables set JWT_SECRET=<value>
railway variables set NODE_ENV=production
```

Get live URL:
```bash
railway open
```

## Render Deployment

Create `render.yaml`:
```yaml
services:
  - type: web
    name: my-app
    env: node
    buildCommand: npm install && npm run build
    startCommand: npm start
    healthCheckPath: /health
    envVars:
      - key: NODE_ENV
        value: production
      - key: DATABASE_URL
        fromDatabase:
          name: my-db
          property: connectionString
databases:
  - name: my-db
    databaseName: myapp
    user: myapp
```

Deploy: push to GitHub → Render auto-deploys on merge to main.

## Fly.io Deployment

```bash
curl -L https://fly.io/install.sh | sh
fly auth login
fly launch  # auto-detects Dockerfile
fly secrets set JWT_SECRET=<value> DATABASE_URL=<value>
fly deploy
```

Check status:
```bash
fly status
fly logs
```

## VPS Deployment (nginx + systemd)

```bash
# On the server:
git clone <repo> /var/www/app
cd /var/www/app && npm install && npm run build

# nginx config: /etc/nginx/sites-available/app
server {
    server_name yourdomain.com;
    location / {
        proxy_pass http://localhost:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
ln -s /etc/nginx/sites-available/app /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx

# certbot SSL
certbot --nginx -d yourdomain.com -d www.yourdomain.com

# systemd service: /etc/systemd/system/app.service
[Unit]
Description=App
After=network.target
[Service]
WorkingDirectory=/var/www/app
ExecStart=/usr/bin/node server.js
Restart=always
EnvironmentFile=/var/www/app/.env
[Install]
WantedBy=multi-user.target

systemctl enable app && systemctl start app
```

## Post-Deployment Verification (the gate)

Always verify after deployment — this is the hard gate from the top of this skill:
```bash
# Health check (retry for cold starts, up to ~60s):
for i in $(seq 1 12); do
  code=$(curl -fsS -o /dev/null -w "%{http_code}" "https://<live-url>" || true)
  [ "$code" = "200" ] && break
  sleep 5
done
echo "final status: $code"   # must be 200
```

Then:
1. Capture the live URL with the `screenshot` tool: `screenshot(url="https://<live-url>")`
2. Push to canvas: `canvas(type="url", content="https://<live-url>")`
3. Visually confirm it is the real app (not a build error / 404 / placeholder)
4. Record the live URL as an artifact, then `project_gate(action="advance", phase="deploy")`
5. Update PROJECT.md with the live URL
6. Add the health check to HEARTBEAT.md for ongoing monitoring
