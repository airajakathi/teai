---
name: decisions
description: Decision-making protocol — generate options with pros/cons, auto-decide technical choices, ask user for brand choices, log every decision in DECISION_LOG.md.
metadata: {"teai_builder": {"emoji": "⚖️"}}
---

# Decision-Making Protocol

## When to Use This Skill

Use this skill for any significant choice that will be hard to reverse:
- Technology selections (framework, database, auth library)
- Infrastructure choices (deployment platform, cloud provider)
- Brand decisions (logo, color palette, app name)
- Architecture decisions (monolith vs microservices, REST vs GraphQL)

Skip this for trivial choices (which variable name, comment wording, minor config).

## Decision Format

Copy this template for each decision entry in `DECISION_LOG.md`:

```markdown
## [YYYY-MM-DD] {Decision Topic}

**Context:** {why this decision is needed}

**Options considered:**

| Option | Pros | Cons |
|--------|------|------|
| A. {name} | {pros} | {cons} |
| B. {name} | {pros} | {cons} |
| C. {name} | {pros} | {cons} |

**Chosen:** Option {A/B/C} — {name}
**Reason:** {one to two sentences}
**Decided by:** teai_builder | user
```

## Auto-Decide vs Ask User

| Decision Type | Who Decides | Examples |
|---------------|-------------|---------|
| Tech stack | teai_builder (auto) | Framework, database, ORM, auth library |
| Infrastructure | teai_builder (auto) | Docker base image, CI tool, server config |
| Logo / icon | Ask user (show 3 options) | Generated with generate_image → canvas |
| Color palette | Ask user (show 3 options) | HTML prototypes pushed to canvas |
| App name | Ask user if not specified | Suggest 3 options |
| Domain name | Ask user | Whether to use custom domain or platform subdomain |
| Deployment platform | Ask user if not specified | Show options with pricing comparison |
| External APIs | Ask user | Stripe vs Paddle, SendGrid vs Resend |

## Presenting Visual Options to the User

For logo/icon decisions:
1. `generate_image` × 3 with different styles
2. `canvas(type="image", path="<path1>")` for each
3. Message: "Here are 3 logo options. Which do you prefer, or should I pick the most professional one?"

For color palette decisions:
1. Write 3 HTML files showing the palettes applied to real components
2. `canvas(type="html", path="<path>")` for each
3. Message with brief description of each palette's character

## Minimum Options Rule

Never fewer than 2 options for any logged decision. 3 options is preferred for significant choices.

## After Deciding

1. Write the entry to `DECISION_LOG.md` immediately
2. Continue execution — do not wait for user acknowledgment on auto-decided choices
3. Mention the decision briefly in the next message to the user: "I chose Next.js for the frontend (see DECISION_LOG.md for the reasoning)"
