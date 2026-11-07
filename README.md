<div align="center">

# 🔍 SearXNG AI

### Privacy-Preserving Metasearch Engine with Grounded AI Overviews

An enhanced, production-ready fork of **SearXNG** featuring a fast, asynchronous, citation-grounded **AI Overview** card above search results — powered by any OpenAI-compatible LLM (Groq, Ollama, OpenAI, OpenRouter, DeepSeek, and more).

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg?style=flat-square)](https://www.gnu.org/licenses/agpl-3.0)
[![Docker Multi-Arch](https://img.shields.io/badge/Docker-linux%2Famd64%20%7C%20linux%2Farm64-2496ED?style=flat-square&logo=docker&logoColor=white)](https://github.com/hrishikeshp7/searxng-ai-23/pkgs/container/searxng-ai-23)
[![Python Version](https://img.shields.io/badge/Python-3.10%20%7C%203.11%20%7C%203.12-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![Valkey Cache](https://img.shields.io/badge/Cache-Valkey%209-FF4438?style=flat-square)](https://valkey.io)

</div>

---

## ⚡ Highlights

- 🔒 **Zero Tracking, 100% Privacy**: No user profiling, no search history logging, no telemetry.
- 🤖 **AI Overviews (Google/Perplexity Style)**: Direct, synthesized answers generated on top of your aggregated organic results.
- ⚡ **Non-Blocking Asynchronous Hydration**: Core search results render with zero delay; the AI overview loads asynchronously via client-side fetch.
- 🛡️ **Stateless Anti-Relay Protection**: Signed with time-limited HMAC payloads (`PAYLOAD_TTL = 600s`). Third parties cannot reuse your instance as an unauthenticated LLM proxy.
- 🔗 **Deep W3C Text-Fragment Grounding**: Clicking a citation chip scrolls directly to the exact sentence on the target website and highlights it using W3C Scroll-to-Text (`#:~:text=`).
- 🧠 **Any LLM Provider**: Plug in ultra-fast cloud inference (Groq), 100% local/offline private models (Ollama), or frontier models (OpenAI, Claude via proxy, OpenRouter).
- 🎯 **Intent-Aware Triggering**: Automatically detects informational queries while cleanly skipping navigational keywords (e.g. login pages), or runs on-demand via a manual trigger button.
- 📊 **Real-time Token Governance**: Displays input/output tokens per generation and tracks daily usage directly in the interface.
- 🐳 **Turnkey Deployment**: Pre-configured `docker-compose.yml` with Valkey caching and automated multi-arch GitHub Container Registry (GHCR) images.

---

## 📸 Key Capabilities

| Feature | Description |
|---|---|
| **Asynchronous Streaming** | Search results display instantly. Overview hydrates smoothly with a shimmer placeholder. |
| **Interactive Citations** | Hover or tap citation badges `[1]`, `[2]` or `【1†L1-L4】` for domain metadata and source snippets. |
| **W3C Source Highlighting** | Auto-generates `#:~:text=start,end` text directives to land directly on cited passages. |
| **Follow-up Chips** | AI automatically suggests related exploration queries at the bottom of the overview. |
| **Token Monitor** | Built-in token counter helps administrators monitor LLM consumption and operational costs. |
| **Refreshed Typography** | Modern system font stack, improved contrast, and high-readability cards. |

---

## 🚀 Quick Start (Docker Compose)

The fastest and recommended way to deploy SearXNG AI.

### 1. Prerequisites
- Docker Engine 24.0+ and Docker Compose v2+
- An API key from an LLM provider (or a running local [Ollama](https://ollama.ai) instance)

### 2. Clone and Configure

```bash
git clone https://github.com/hrishikeshp7/searxng-ai-23.git
cd searxng-ai-23

# Create your environment file from the template
cp .env.example .env
```

### 3. Generate Secret Key & Set Provider

Generate a secure random secret for SearXNG session encryption:

```bash
openssl rand -hex 32
```

Open `.env` in your editor and configure:

```bash
# Core Settings
SEARXNG_SECRET=your_generated_hex_secret_here
SEARXNG_PORT=8080

# -------------------------------------------------------------
# Choose ONE of the configurations below:
# -------------------------------------------------------------

# OPTION A: Groq (Recommended for lightning-fast ~500 tok/s answers)
SEARXNG_AI_OVERVIEW_BASE_URL=https://api.groq.com/openai/v1
SEARXNG_AI_OVERVIEW_API_KEY=gsk_your_groq_api_key
SEARXNG_AI_OVERVIEW_MODEL=llama-3.3-70b-versatile
SEARXNG_AI_OVERVIEW_TRIGGER_MODE=auto

# OPTION B: 100% Local & Private (Ollama - No external API needed)
# SEARXNG_AI_OVERVIEW_BASE_URL=http://host.docker.internal:11434/v1
# SEARXNG_AI_OVERVIEW_API_KEY=ollama
# SEARXNG_AI_OVERVIEW_MODEL=llama3.2
# SEARXNG_AI_OVERVIEW_TRIGGER_MODE=auto

# OPTION C: OpenAI
# SEARXNG_AI_OVERVIEW_BASE_URL=https://api.openai.com/v1
# SEARXNG_AI_OVERVIEW_API_KEY=sk-proj-your_openai_key
# SEARXNG_AI_OVERVIEW_MODEL=gpt-4o-mini
# SEARXNG_AI_OVERVIEW_TRIGGER_MODE=auto

# OPTION D: OpenRouter
# SEARXNG_AI_OVERVIEW_BASE_URL=https://openrouter.ai/api/v1
# SEARXNG_AI_OVERVIEW_API_KEY=sk-or-v1-your_key
# SEARXNG_AI_OVERVIEW_MODEL=meta-llama/llama-3.3-70b-instruct
# SEARXNG_AI_OVERVIEW_TRIGGER_MODE=auto
```

### 4. Launch Container

```bash
docker compose up -d
```

Access your search engine at: **`http://localhost:8080`**

To monitor logs:
```bash
docker compose logs -f searxng
```

---

## 🛠️ Configuration Reference

### Environment Variables

| Variable | Default | Description |
|---|---|---|
| `SEARXNG_SECRET` | *(Required)* | 32-byte hex secret for HMAC session signing and payload verification. |
| `SEARXNG_PORT` | `8080` | Host port mapped to the SearXNG web container. |
| `SEARXNG_BASE_URL` | *(Empty)* | Public domain/URL (e.g. `https://search.yourdomain.com/`). |
| `SEARXNG_AI_OVERVIEW_BASE_URL` | `https://api.openai.com/v1` | Base URL of any OpenAI-compatible API (without trailing `/chat/completions`). |
| `SEARXNG_AI_OVERVIEW_API_KEY` | *(Required)* | Authentication bearer token or API key for the LLM service. |
| `SEARXNG_AI_OVERVIEW_MODEL` | `gpt-4o-mini` | Name of the model to query. |
| `SEARXNG_AI_OVERVIEW_TRIGGER_MODE` | `auto` | `auto` (smart query intent detection) or `manual` (on-demand button). |

---

## 🏗️ Architecture & Security Model

```
   User Browser              SearXNG Engine              LLM Provider (Groq/Ollama/OpenAI)
        │                           │                                    │
   1.   ├─ Search Request ─────────►│                                    │
        │                           ├─ Aggregate 70+ Engines             │
        │                           ├─ Generate HMAC Signature           │
   2.   │◄─ HTML + Signed Token ────┤  (Results render immediately)      │
        │                           │                                    │
   3.   ├─ POST /ai_overview ──────►│                                    │
        │  (Payload + Signature)    ├─ Verify HMAC + Timestamp           │
        │                           ├─ Extract Grounding Context         │
        │                           ├─ POST /chat/completions ──────────►│
        │                           │◄─ Structured JSON Response ────────┤
   4.   │◄─ Rendered AI Summary ────┤                                    │
```

1. **Stateless Anti-Relay**: When SearXNG renders search results, it constructs a cryptographically signed payload containing candidate result snippets and a timestamp.
2. **Payload TTL**: Requests are valid only within `600 seconds`. Replay attempts after the TTL are rejected.
3. **No Key Exposure**: The browser never sees your LLM API keys; all outbound AI requests are securely executed by the backend worker.

---

## 💻 Manual / Local Development Setup

If running directly without Docker:

```bash
# 1. Create a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 2. Install dependencies
pip install -U pip setuptools wheel
pip install -r requirements.txt

# 3. Export configuration
export SEARXNG_SECRET=$(openssl rand -hex 32)
export SEARXNG_AI_OVERVIEW_BASE_URL="https://api.groq.com/openai/v1"
export SEARXNG_AI_OVERVIEW_API_KEY="your_groq_api_key"
export SEARXNG_AI_OVERVIEW_MODEL="llama-3.3-70b-versatile"
export SEARXNG_AI_OVERVIEW_TRIGGER_MODE="auto"

# 4. Start SearXNG
python -m searx.webapp
```

---

## 🤝 Contributing

Contributions, feedback, and bug reports are welcome!
1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

---

## 📜 License & Credits

- Based on the open-source [SearXNG](https://github.com/searxng/searxng) project.
- Licensed under **AGPL-3.0-or-later** in compliance with upstream licensing.
