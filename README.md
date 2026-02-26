# translate

A self-hosted AI translation service powered by Google's TranslateGemma 12B multimodal model. Translates text and images between 55 languages through a clean web UI and an OpenAI-compatible REST API.

---

## Features

- Text translation between 55 languages
- Image translation — upload a photo, screenshot, or document and translate the text within it
- OpenAI-compatible `/v1/chat/completions` API — drop-in compatible with clients that support custom endpoints
- Dark-themed single-page web UI with drag-and-drop image support
- Optional API key authentication
- Self-hosted — all inference runs locally on your GPU; no data leaves your machine

---

## Requirements

- Docker and Docker Compose
- NVIDIA GPU with at least 16 GB VRAM (the 12B model runs in `bfloat16`)
- [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html) installed on the host
- A [HuggingFace account](https://huggingface.co) with access granted to the [google/translategemma-12b-it](https://huggingface.co/google/translategemma-12b-it) gated model
- A HuggingFace API token with read access

---

## Quick Start

### 1. Clone and configure

```bash
git clone <repo-url>
cd translate
cp .env.example .env
```

Edit `.env` and set your HuggingFace token:

```
HF_TOKEN=hf_your_token_here
```

### 2. Start the services

```bash
docker compose up --build -d
```

The first run downloads the 12B model (~24 GB). Subsequent starts load from the
local cache at `/storage-models` on the host. The backend takes 1–2 minutes to
become ready after the image starts.

### 3. Open the UI

Navigate to [http://localhost:11438](http://localhost:11438) in your browser.

The status indicator in the top-right corner of the UI turns green once the
model is fully loaded and ready to accept requests.

---

## Services

| Service            | Host port | Internal port | Description                        |
|--------------------|-----------|---------------|------------------------------------|
| `translate-ui`     | 11438     | 80            | nginx serving the web UI           |
| `translate-backend`| 12434     | 8080          | FastAPI inference server           |

The UI proxies all `/api/*` requests to the backend, so the browser never needs
direct access to port 12434.

---

## API Usage

The backend exposes an OpenAI-compatible API. All `/v1/*` endpoints require the
`Authorization: Bearer <API_KEY>` header (default key is set in `docker-compose.yaml`).

### Health check

```bash
curl http://localhost:12434/health
# {"status": "ok"}
```

### List available models

```bash
curl -H "Authorization: Bearer 2f8d430a0f17b3eaa957cf7ae188a3db71a2df6d30cf0a9766eddbb0b70421c8" \
     http://localhost:12434/v1/models
```

### Translate text

```bash
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
```

### Translate an image (via URL)

```bash
curl -s -X POST http://localhost:12434/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer 2f8d430a0f17b3eaa957cf7ae188a3db71a2df6d30cf0a9766eddbb0b70421c8" \
  -d '{
    "messages": [{
      "role": "user",
      "content": [{
        "type": "image",
        "source_lang_code": "ja",
        "target_lang_code": "en",
        "url": "https://example.com/image.jpg"
      }]
    }]
  }'
```

Images can also be sent as base64 data URLs: `"url": "data:image/jpeg;base64,<base64data>"`.

### Request schema

| Field                        | Type    | Default              | Description                              |
|------------------------------|---------|----------------------|------------------------------------------|
| `messages[].content[].type`  | string  | required             | `"text"` or `"image"`                    |
| `messages[].content[].source_lang_code` | string | required  | BCP-47 language code of the source       |
| `messages[].content[].target_lang_code` | string | required  | BCP-47 language code of the target       |
| `messages[].content[].text`  | string  | —                    | Source text (required when type=`text`)  |
| `messages[].content[].url`   | string  | —                    | Image URL or data URL (type=`image`)     |
| `max_tokens`                 | integer | 2048                 | Maximum tokens to generate               |
| `temperature`                | float   | 0.0                  | Sampling temperature (0 = greedy)        |
| `stream`                     | bool    | false                | Not supported — returns 400 if true      |

### Response schema

The response follows the OpenAI chat completion format, with one additional field:

```json
{
  "id": "chatcmpl-...",
  "object": "chat.completion",
  "created": 1234567890,
  "model": "translategemma-12b-Q8",
  "choices": [{
    "index": 0,
    "message": { "role": "assistant", "content": "Bonjour, monde !" },
    "finish_reason": "stop"
  }],
  "usage": {
    "prompt_tokens": 42,
    "completion_tokens": 8,
    "total_tokens": 50
  },
  "timings": {
    "predicted_ms": 1340.5
  }
}
```

---

## Configuration

All runtime configuration is managed through environment variables in `docker-compose.yaml`.

| Variable      | Default                          | Description                                         |
|---------------|----------------------------------|-----------------------------------------------------|
| `HF_TOKEN`    | _(from `.env`)_                  | HuggingFace Hub token for downloading the gated model |
| `MODEL_ID`    | `google/translategemma-12b-it`   | HuggingFace model repository                        |
| `MODEL_ALIAS` | `translategemma-12b-Q8`          | Model name returned by `/v1/models`                 |
| `API_KEY`     | `2f8d430a0f17...`                | Bearer token for `/v1/*` endpoints; set to empty string to disable auth |
| `HF_HOME`     | `/models/hf_cache`               | HuggingFace cache directory inside the container    |

To disable API key authentication, set `API_KEY` to an empty string in `docker-compose.yaml`.

To use a different model, change `MODEL_ID` to any HuggingFace model compatible
with `AutoModelForImageTextToText`.

---

## Architecture

```
Browser (port 11438)
  └── nginx (translate-ui)
        ├── GET /          →  serves index.html
        └── /api/*         →  proxied to translate-backend:8080
                                └── FastAPI (translate-backend, port 8080)
                                      └── TranslateGemma 12B (GPU, bfloat16)
                                            └── model cache at /storage-models
```

**Backend** (`backend/server.py`):
- FastAPI application with a lifespan context manager that loads the model once at startup.
- Accepts the OpenAI message format with a custom `ContentItem` schema that carries
  `source_lang_code` and `target_lang_code` fields alongside the content.
- Converts the request to HuggingFace's `apply_chat_template` format, runs
  greedy decoding under `torch.inference_mode()`, and decodes only the newly
  generated tokens.

**Frontend** (`ui/index.html`):
- Single self-contained file — no build step, no npm, no framework.
- Polls `/api/v1/models` every 15 seconds to reflect model readiness in the UI.
- Supports text input, file upload (click or drag-and-drop), and clipboard paste for images.
- Language swap button swaps both selectors and the current text content simultaneously.
- `Ctrl+Enter` / `Cmd+Enter` triggers translation.

**nginx** (`ui/nginx.conf`):
- Serves the static UI from `/usr/share/nginx/html`.
- Proxies `/api/` to `http://translate-backend:8080/` on the internal Docker network.
- Enforces a 20 MB `client_max_body_size` for image uploads; sets 120s read/send timeouts.

---

## Limitations

- **No streaming** — the model generates the full translation before responding.
- **One content item per request** — only `messages[*].content[0]` is processed;
  additional items in the array are ignored.
- **Effective image upload limit ~15 MB** — nginx allows 20 MB but base64 encoding
  inflates raw image size by ~33%.
- **GPU required** — CPU inference is technically possible but impractically slow
  for a 12B parameter model.
- **Model load time** — expect 1–2 minutes from container start before the first
  request can be served.

---

## Development

### Modifying the backend

Edit `backend/server.py`, then rebuild and restart the backend container:

```bash
docker compose up -d --build translate-backend
docker compose logs -f translate-backend
```

For a faster iteration loop without Docker, run the server directly (requires
a local Python environment with the dependencies installed):

```bash
cd backend
pip install -r requirements.txt
uvicorn server:app --host 0.0.0.0 --port 8080 --reload
```

Note: without the model weights present at `HF_HOME`, the server will attempt
to download them from HuggingFace on startup.

### Modifying the frontend

Edit `ui/index.html`, then rebuild and restart the UI container:

```bash
docker compose up -d --build translate-ui
```

Because the UI is a single static file served by nginx, changes are visible
immediately after the container restarts (no cache busting needed in development).

### Adding Python dependencies

Add the package to `backend/requirements.txt`, then rebuild:

```bash
docker compose build --no-cache translate-backend
docker compose up -d translate-backend
```

---

## File Reference

| File                      | Purpose                                                      |
|---------------------------|--------------------------------------------------------------|
| `docker-compose.yaml`     | Service definitions, environment variables, GPU allocation   |
| `backend/server.py`       | FastAPI app — models, helpers, endpoints (~215 lines)        |
| `backend/Dockerfile`      | PyTorch 2.7 / CUDA 12.6 image, installs requirements        |
| `backend/requirements.txt`| Python dependencies                                          |
| `ui/index.html`           | Complete web UI — HTML, CSS, JS (~865 lines)                 |
| `ui/nginx.conf`           | nginx config — static serving and API proxy                  |
| `ui/Dockerfile`           | nginx:alpine image, copies conf and index.html               |
| `.env.example`            | Template for the required `.env` file                        |
| `.env`                    | Local secrets (gitignored — never commit)                    |
