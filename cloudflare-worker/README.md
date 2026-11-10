# SearXNG Cloudflare Worker Proxy

Edge proxy worker for SearXNG "Anonymous View" feature.

### Features
- **Origin Concealment**: Fetches target sites from Cloudflare edge IPs instead of Heroku/AWS IPs.
- **Zero Dyno Load**: Bypasses Heroku dyno memory and streaming bandwidth limits entirely.
- **HMAC Authenticated**: Uses identical HMAC-SHA256 tokens as SearXNG to prevent unauthorized relay abuse.
- **Streaming HTMLRewriter**: Injects `<base>` tags and strips frame-busting headers on the fly.

---

### Deployment Option A: Cloudflare Dashboard (No CLI needed)

1. Go to [Cloudflare Dashboard](https://dash.cloudflare.com/) → **Workers & Pages** → **Create application** → **Create Worker**.
2. Name it (e.g. `searxng-proxy`) and click **Deploy**.
3. Click **Edit code**, paste the entire contents of [`worker.js`](worker.js), and click **Deploy**.
4. Go to Worker **Settings** → **Variables and Secrets**:
   - Add Secret `SEARXNG_SECRET` with the same secret key as your Heroku `SEARXNG_SECRET`.
5. Copy your worker URL (e.g. `https://searxng-proxy.<your-subdomain>.workers.dev`).

---

### Deployment Option B: Wrangler CLI

```bash
cd cloudflare-worker
npx wrangler secret put SEARXNG_SECRET
npx wrangler deploy
```

---

### Activating in SearXNG on Heroku

Once deployed, set the worker URL on Heroku:

```bash
heroku config:set SEARXNG_PROXY_WORKER_URL="https://searxng-proxy.<your-subdomain>.workers.dev"
```

To switch back to the Heroku dyno proxy anytime:
```bash
heroku config:unset SEARXNG_PROXY_WORKER_URL
```
