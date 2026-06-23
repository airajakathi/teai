---
name: testing
description: Playwright E2E setup, unit test patterns, screenshot verification workflow, and test reporting format for the CEO.
metadata: {"teai_builder": {"emoji": "🧪"}}
---

# Testing Guide

## Playwright E2E Setup

### Install
```bash
npm init playwright@latest
# OR add to existing project:
npm install -D @playwright/test
npx playwright install --with-deps chromium
```

### playwright.config.ts
```typescript
import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  reporter: [['html', { outputFolder: 'playwright-report' }], ['list']],
  use: {
    baseURL: process.env.BASE_URL || 'http://localhost:3000',
    trace: 'on-first-retry',
    screenshot: 'on',
    video: 'on-first-retry',
  },
});
```

### Example E2E test
```typescript
import { test, expect } from '@playwright/test';

test('user can register and log in', async ({ page }) => {
  await page.goto('/register');
  await page.fill('[name=email]', 'test@example.com');
  await page.fill('[name=password]', 'SecurePass123!');
  await page.click('[type=submit]');

  await expect(page).toHaveURL('/dashboard');
  await expect(page.getByText('Welcome')).toBeVisible();
  await page.screenshot({ path: 'screenshots/dashboard.png' });
});
```

### Run tests
```bash
# All tests
npx playwright test

# With UI
npx playwright test --ui

# Specific file
npx playwright test tests/e2e/auth.spec.ts

# Generate report
npx playwright show-report
```

## Visual Screenshot Verification

After tests, push screenshots to canvas:
```python
# In teai_builder context
canvas(type="image", path="screenshots/dashboard.png")
canvas(type="image", path="screenshots/login.png")
```

## Unit Tests (Frontend — Vitest)

```typescript
// sum.test.ts
import { describe, it, expect } from 'vitest';
import { formatCurrency } from './utils';

describe('formatCurrency', () => {
  it('formats USD correctly', () => {
    expect(formatCurrency(1234.56, 'USD')).toBe('$1,234.56');
  });
  it('handles zero', () => {
    expect(formatCurrency(0, 'USD')).toBe('$0.00');
  });
});
```

Run: `npm run test` or `vitest run`

## Unit Tests (Backend — pytest)

```python
# test_auth.py
import pytest
from app.auth import hash_password, verify_password

def test_password_hash_is_not_plaintext():
    hashed = hash_password("mypassword")
    assert hashed != "mypassword"
    assert len(hashed) > 20

def test_password_verification():
    hashed = hash_password("mypassword")
    assert verify_password("mypassword", hashed)
    assert not verify_password("wrongpassword", hashed)
```

Run: `pytest --tb=short -q`

## Accessibility Testing

```typescript
import { checkA11y } from 'axe-playwright';

test('homepage has no accessibility violations', async ({ page }) => {
  await page.goto('/');
  await checkA11y(page, null, {
    runOnly: ['wcag2a', 'wcag2aa'],
    detailedReport: true,
  });
});
```

## Test Report Format (for CEO)

When reporting results back to the CEO, always use this format:

```
## QA Test Report — <Project Name>

**Run date:** YYYY-MM-DD
**Environment:** staging | production
**Base URL:** https://<url>

### E2E Tests (Playwright)
- Total: XX
- Passed: XX ✅
- Failed: XX ❌
- Skipped: XX ⏭

### Unit Tests
- Total: XX
- Passed: XX ✅
- Failed: XX ❌

### Known Failures
| Test | Error | Severity |
|------|-------|---------|
| <name> | <error> | critical/high/medium/low |

### Screenshots
(pushed to canvas)

### Recommendation
[ ] All critical tests pass → ready to deploy
[ ] Critical failures found → DO NOT deploy, fix required
```
