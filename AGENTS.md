# AGENTS.md — Coding Agent Reference

This file documents conventions, commands, and architecture for AI coding agents
working in this repository.

---

## Project Overview

A self-hosted AI translation service built around Google's **TranslateGemma 12B**
multimodal model. Two services, orchestrated by Docker Compose:

- **translate-backend** — FastAPI (Python) server exposing an OpenAI-compatible
  `/v1/chat/completions` endpoint. Loads the model once at startup via the
  HuggingFace `transformers` library; runs inference on GPU with `bfloat16`.
- **translate-ui** — Static HTML/CSS/JS single-file app served by nginx, which
  also reverse-proxies `/api/*` to the backend.

---

## Repository Layout

```
translate/
├── .env                  # HF_TOKEN (gitignored — never commit)
├── .env.example          # Template for .env
├── docker-compose.yaml   # Top-level service orchestration
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── server.py         # Entire backend (~215 lines)
└── ui/
    ├── Dockerfile
    ├── nginx.conf
    └── index.html        # Entire frontend (~865 lines, vanilla JS)
```

---

## Build & Run Commands

```bash
# First-time setup — copy and populate the HuggingFace token
cp .env.example .env
# edit .env and set HF_TOKEN=<your_hf_token>

# Build and start both services (detached)
docker compose up --build -d

# View logs (follow)
docker compose logs -f

# Backend logs only
docker compose logs -f translate-backend

# Stop services
docker compose down

# Rebuild a single service without cache
docker compose build --no-cache translate-backend
docker compose build --no-cache translate-ui

# Restart a single service after code changes
docker compose up -d --build translate-backend
docker compose up -d --build translate-ui
```

Service ports exposed on the host:
- UI:      http://localhost:11438
- Backend: http://localhost:12434  (direct, bypasses nginx)

---

## Testing

There is no automated test suite. Functional verification is done manually:

```bash
# Health check (no auth required)
curl http://localhost:12434/health

# List models (requires API key)
curl -H "Authorization: Bearer 2f8d430a0f17b3eaa957cf7ae188a3db71a2df6d30cf0a9766eddbb0b70421c8" \
     http://localhost:12434/v1/models

# Translate a text snippet
curl -s -X POST http://localhost:12434/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer 2f8d430a0f17b3eaa957cf7ae188a3db71a2df6d30cf0a9766eddbb0b70421c8" \
  -d '{
    "messages": [{
      "role": "user",
      "content": [{
        "type": "text",
        "source_lang_code": "en",
        "target_lang_code": "fr",
        "text": "Hello, world!"
      }]
    }]
  }' | python3 -m json.tool

# Docker healthcheck status
docker inspect --format='{{.State.Health.Status}}' translate-backend
```

When adding new backend features, test via `curl` against the running container.
If iterating locally without Docker, you can run the backend directly:

```bash
cd backend
pip install -r requirements.txt
uvicorn server:app --host 0.0.0.0 --port 8080 --reload
```

---

## Linting & Formatting

No linter or formatter is currently configured. Follow these conventions manually:

**Python** — use `ruff` if you add a linter:
```bash
ruff check backend/server.py
ruff format backend/server.py
```

**HTML/JS** — `index.html` is a single self-contained file; use `prettier` if needed:
```bash
prettier --write ui/index.html
```

---

## Python Code Style (`backend/server.py`)

### Imports
- Standard library first, then third-party — one blank line between groups.
- Lazy imports inside functions are acceptable only to avoid optional heavy
  dependencies (e.g., `import httpx` inside `load_image_from_url`).

### Type Annotations
- Use Python 3.10+ union syntax: `str | None`, `list[ContentItem] | str`.
- Do **not** use `Optional[X]` or `List[X]` from `typing`; import only `Any`
  when genuinely needed.
- All Pydantic model fields must be typed.

### Naming Conventions
- `snake_case` for functions, variables, module-level globals, and filenames.
- `PascalCase` for Pydantic models and classes.
- Module-level constants in `UPPER_SNAKE_CASE` (e.g., `MODEL_ID`, `API_KEY`).

### Error Handling
- Raise `fastapi.HTTPException` directly with an appropriate HTTP status code
  and a plain-English `detail` string. Do not create custom exception classes.
- Validate inputs early; raise `400` for bad input, `401` for auth failures.

### Comments
- Do **not** add inline comments or block comments to code. Write code that is
  self-explanatory through clear naming and structure instead.
- The only permitted comments are the section-delimiter lines used to separate
  top-level groups (e.g., `# ---- Section name ----`). Do not add new ones
  unless introducing a genuinely new top-level section.
- Do not add docstrings to functions unless the function is part of a public API
  and the signature alone is insufficient to understand its contract.

### Code Organisation
- Keep the file flat — avoid splitting into multiple modules unless the file
  grows significantly beyond ~400 lines.

### Global State
- The `processor` and `model` globals are set once during the FastAPI `lifespan`
  context manager. Do not reassign them outside of `lifespan`.

### Async vs Sync
- FastAPI route handlers are `async def`; pure-compute helpers (e.g., image
  loading, message building) are plain `def`.
- Use `torch.inference_mode()` as a context manager for all model inference.

---

## Frontend Code Style (`ui/index.html`)

- Everything lives in a single `index.html` — inline `<style>` and `<script>`.
  Do not split into separate files unless there is a strong reason.
- Vanilla JavaScript only — no frameworks, no build step, no npm.
- Use `const` for DOM references and fixed values; `let` for mutable state.
- Use `async/await` for all `fetch()` calls; handle errors with `try/catch`.
- Use `camelCase` for variables and functions.
- CSS theming via custom properties (`--bg`, `--accent`, etc.) defined on `:root`.
- The API base URL is derived at runtime from `window.location.origin` — do not
  hardcode hostnames.

---

## Environment Variables

| Variable      | Where set            | Purpose                                      |
|---------------|----------------------|----------------------------------------------|
| `HF_TOKEN`    | `.env` (host)        | HuggingFace Hub token for gated model access |
| `MODEL_ID`    | `docker-compose.yaml`| HuggingFace model repo (default: translategemma-12b-it) |
| `MODEL_ALIAS` | `docker-compose.yaml`| Alias returned by `/v1/models`               |
| `API_KEY`     | `docker-compose.yaml`| Bearer token for all `/v1/*` endpoints; empty = no auth |
| `HF_HOME`     | `docker-compose.yaml`| Cache directory inside the models volume     |

**Never commit `.env`** — it is listed in `.gitignore`.

---

## Key Architectural Constraints

- **No streaming** — the `/v1/chat/completions` endpoint returns a 400 if
  `stream: true` is requested. Do not implement streaming without also updating
  the UI to consume SSE.
- **Single image per request** — the model processes one content item per user
  message; the backend takes only `messages[*].content[0]`.
- **Image size limit** — nginx enforces a 20 MB `client_max_body_size`; base64
  encoding inflates size by ~33%, so effective image limit is ~15 MB.
- **Model loaded once** — the 12B model takes 1–2 minutes to load. The Docker
  healthcheck has a `start_period: 120s` grace period; do not reduce this.
- **GPU required** — `device_map="auto"` with `bfloat16` targets CUDA; the
  service will be very slow or fail without an NVIDIA GPU and the NVIDIA
  Container Toolkit installed on the host.
