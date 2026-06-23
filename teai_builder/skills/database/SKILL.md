---
name: database
description: Database selection (SQLite/Postgres/Supabase/PlanetScale), schema migrations, Railway/Supabase setup, backups, and connection pooling.
metadata: {"teai_builder": {"emoji": "🗄️"}}
---

# Database Guide

## Decision: Choosing a Database

| Database | Best For | Free Tier | Notes |
|----------|---------|-----------|-------|
| SQLite | Personal tools, demos, <1k users | Always free | File-based, zero infrastructure |
| PostgreSQL (Railway) | Most production apps | 512MB free | Full SQL, great ecosystem |
| Supabase | Apps needing real-time + auth | 500MB free | Postgres + REST + Auth built in |
| PlanetScale | High-traffic, MySQL-compatible | Free tier | Branching, serverless-friendly |
| MongoDB Atlas | Flexible schema, document data | 512MB free | NoSQL, good for content/logs |

**Default recommendation:** PostgreSQL on Railway for most production apps.

## PostgreSQL on Railway

```bash
railway add --plugin postgresql
# DATABASE_URL is auto-injected
```

Connect locally for testing:
```bash
railway connect postgresql
# Opens psql session
```

## Supabase Setup

```bash
npm install @supabase/supabase-js
```

```typescript
import { createClient } from '@supabase/supabase-js';
const supabase = createClient(
  process.env.SUPABASE_URL!,
  process.env.SUPABASE_ANON_KEY!
);
```

Get SUPABASE_URL and SUPABASE_ANON_KEY from Supabase dashboard → Project Settings → API.

## Migrations with Drizzle ORM (Node.js)

```bash
npm install drizzle-orm pg
npm install -D drizzle-kit @types/pg
```

Schema:
```typescript
// db/schema.ts
import { pgTable, text, timestamp, uuid } from 'drizzle-orm/pg-core';

export const users = pgTable('users', {
  id: uuid('id').primaryKey().defaultRandom(),
  email: text('email').notNull().unique(),
  passwordHash: text('password_hash').notNull(),
  createdAt: timestamp('created_at').defaultNow(),
});
```

Run migrations:
```bash
npx drizzle-kit generate
npx drizzle-kit migrate
```

## Migrations with Alembic (Python/SQLAlchemy)

```bash
pip install alembic sqlalchemy psycopg2-binary
alembic init alembic
alembic revision --autogenerate -m "initial"
alembic upgrade head
```

## Connection Pooling

For production, always use a connection pool:

```typescript
// Node.js — pg with pool
import { Pool } from 'pg';
const pool = new Pool({
  connectionString: process.env.DATABASE_URL,
  max: 10,
  idleTimeoutMillis: 30000,
  connectionTimeoutMillis: 2000,
});
```

For serverless (Vercel, Fly.io): use `@neondatabase/serverless` or Supabase's `pg` adapter with HTTP mode.

## Backup Strategy

**Railway:** Automatic daily backups on paid plans. For free tier: export manually.
**Supabase:** Automatic daily backups. Point-in-time recovery on Pro plan.
**Self-hosted Postgres:**
```bash
# Backup
pg_dump $DATABASE_URL > backup_$(date +%Y%m%d).sql

# Add to cron / HEARTBEAT.md for weekly backups
pg_dump $DATABASE_URL | gzip > backup_$(date +%Y%m%d).sql.gz
```

## Security Checklist

- [ ] Never expose DATABASE_URL in frontend code or logs
- [ ] Use row-level security in Supabase for multi-tenant apps
- [ ] Use parameterized queries — never string-concatenate user input into SQL
- [ ] Limit database user permissions (app user should not have DROP TABLE)
- [ ] Enable SSL for database connections in production
