# B&B AI Landing — Deploy Guide

## Quick Deploy

```bash
# From the landing directory
cd /Users/javiercamaraportepetit/Desktop/B2B-AI-MVP/enterprise/landing

# Deploy to production
npx vercel --yes --prod
```

## Prerequisites

- Node.js 18+
- Vercel CLI (auto-installed via npx)
- Vercel account with access to `likida` team

## First-time setup

If not already authenticated:

```bash
npx vercel login
```

## Production URL

https://landing-steel-psi-83.vercel.app

## What gets deployed

The entire `landing/` directory is served as static files:

- `index.html` — main landing page
- `dashboard.html` — /dashboard route
- `assets/` — hero images, logo, video
- `icons/` — favicons and PWA icons
- `manifest.json`, `sw.js`, `sitemap.xml`, `robots.txt`

## Rewrites (vercel.json)

| Source | Destination |
|---|---|
| `/static/:path*` | `/assets/:path*` |
| `/dashboard` | `/dashboard.html` |

## Caching

- `assets/*`, `icons/*` — immutable (1 year)
- `sw.js` — no-cache (service worker)
- `manifest.json` — 24 hours

## Verification

After deploy, verify all routes return HTTP 200:

```bash
curl -s -o /dev/null -w "%{http_code}" https://landing-steel-psi-83.vercel.app/
```