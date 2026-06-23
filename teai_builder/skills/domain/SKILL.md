---
name: domain
description: Custom domain setup on Vercel/Railway/Render, Cloudflare DNS configuration, HTTPS/SSL, www redirect.
metadata: {"teai_builder": {"emoji": "🌐"}}
---

# Domain & DNS Guide

## Decision: Custom Domain vs Platform Subdomain

| Option | When to Use |
|--------|------------|
| Platform subdomain (`app.vercel.app`, `app.railway.app`) | MVP, internal tools, demos |
| Custom domain (`myapp.com`) | Production, user-facing, business apps |

Always ask the user if they have a domain before assuming. If not, suggest they buy one from Namecheap or Cloudflare Registrar.

## Cloudflare DNS Setup (Recommended)

Cloudflare is the recommended DNS provider for all custom domains:
- Free DDoS protection and CDN
- Easy DNS management
- Free SSL via Universal SSL

### Steps
1. Transfer domain to Cloudflare (or change nameservers):
   - Cloudflare dashboard → Add site → Follow nameserver instructions
2. Add DNS records based on the platform (see below)
3. Enable "Proxied" (orange cloud) for HTTP/HTTPS traffic
4. SSL/TLS mode: "Full (strict)" for platforms with their own SSL

## Vercel Custom Domain

```bash
vercel domains add yourdomain.com
```

Cloudflare DNS records:
```
Type: CNAME  Name: @    Target: cname.vercel-dns.com   Proxy: off (grey cloud)
Type: CNAME  Name: www  Target: cname.vercel-dns.com   Proxy: off (grey cloud)
```

Note: Vercel handles SSL automatically. Keep Cloudflare proxy OFF for Vercel.

## Railway Custom Domain

In Railway dashboard → your service → Settings → Domains → Add Custom Domain.

Cloudflare DNS records:
```
Type: CNAME  Name: @    Target: <railway-provided>.railway.app  Proxy: on
Type: CNAME  Name: www  Target: <railway-provided>.railway.app  Proxy: on
```

## Render Custom Domain

In Render dashboard → your service → Settings → Custom Domains → Add.

Cloudflare DNS records:
```
Type: CNAME  Name: @    Target: <service>.onrender.com  Proxy: on
Type: CNAME  Name: www  Target: <service>.onrender.com  Proxy: on
```

## Fly.io Custom Domain

```bash
fly certs create yourdomain.com
fly certs show yourdomain.com  # shows the CNAME target
```

## www Redirect

Most platforms handle this automatically. To enforce www → non-www (or vice versa) with Cloudflare:

Cloudflare → Rules → Redirect Rules → Create:
```
If: hostname is www.yourdomain.com
Then: Redirect to https://yourdomain.com/${uri_path} (301)
```

## SSL Verification

After setup, verify HTTPS is working:
```bash
curl -I https://yourdomain.com
# Expected: HTTP/2 200

# Check certificate
openssl s_client -connect yourdomain.com:443 -brief 2>/dev/null | head -5
```

## Checklist

- [ ] Domain purchased and transferred to Cloudflare
- [ ] DNS records added for www and root domain
- [ ] HTTPS working: `curl -I https://yourdomain.com` returns 200
- [ ] www redirect configured
- [ ] DNS propagation checked: `dig yourdomain.com` shows correct IP/CNAME
- [ ] Update `PROJECT.md` live URL with custom domain
