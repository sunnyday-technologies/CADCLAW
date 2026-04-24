# Deploying cadclaw.ai

Static landing page served via **GitHub Pages** from `/docs` on `main`.

## One-time GitHub setup

1. Push this branch to `main`.
2. **Settings → Pages**
   - Source: `Deploy from a branch`
   - Branch: `main`  /  folder: `/docs`
   - Save
3. **Custom domain**: enter `cadclaw.ai` → Save. The `docs/CNAME` file already contains this.
4. Check **Enforce HTTPS** once the cert provisions (≈15 min after DNS resolves).

## One-time Cloudflare DNS setup

Add these records for `cadclaw.ai` in Cloudflare DNS:

| Type  | Name | Content                  | Proxy    |
|-------|------|--------------------------|----------|
| A     | @    | 185.199.108.153          | DNS only |
| A     | @    | 185.199.109.153          | DNS only |
| A     | @    | 185.199.110.153          | DNS only |
| A     | @    | 185.199.111.153          | DNS only |
| CNAME | www  | sunnyday-technologies.github.io | DNS only |

**Important:** set Proxy status to **DNS only** (grey cloud), not Proxied (orange cloud),
for GitHub Pages' Let's Encrypt cert to provision. You can switch to Proxied afterward
if you want Cloudflare caching — but only after HTTPS is working.

In Cloudflare **SSL/TLS → Overview**, set mode to **Full** (not Flexible, not Full Strict
until GitHub's cert is live).

## Files in `docs/`

```
docs/
├── index.html          # landing page
├── styles.css          # Claude Code CLI aesthetic
├── CNAME               # custom domain → cadclaw.ai
├── .nojekyll           # skip Jekyll processing
├── robots.txt
├── sitemap.xml
├── CADCLAW_logo.jpg    # wordmark shown in nav + favicon
└── media/
    └── m3crete_radial_spin.gif
```

## Logo

`docs/CADCLAW_logo.jpg` — shown in the nav bar and used as favicon. The HTML
gracefully falls back to a text wordmark if the file is missing, so the site
works even if the logo is renamed or removed.

## Local preview

Any static HTTP server works:

```bash
cd docs
python -m http.server 8000
# → http://localhost:8000
```

## Updating content

Edit `docs/index.html`. Commit to `main`. GitHub Pages redeploys in ~1 minute.
