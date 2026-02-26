import base64
import io
import os
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any

import torch
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from PIL import Image
from pydantic import BaseModel
from transformers import AutoModelForImageTextToText, AutoProcessor

MODEL_ID = os.getenv("MODEL_ID", "google/translategemma-12b-it")
MODEL_ALIAS = os.getenv("MODEL_ALIAS", "translategemma-12b-Q8")
API_KEY = os.getenv("API_KEY", "")

processor = None
model = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global processor, model
    print(f"Loading model: {MODEL_ID}", flush=True)
    processor = AutoProcessor.from_pretrained(MODEL_ID)
    model = AutoModelForImageTextToText.from_pretrained(
        MODEL_ID,
        device_map="auto",
        dtype=torch.bfloat16,
    )
    model.eval()
    print("Model loaded.", flush=True)
    yield


app = FastAPI(lifespan=lifespan)


def check_api_key(request: Request):
    if not API_KEY:
        return
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer ") or auth[len("Bearer "):] != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")


# ---- Request / response models ----

class ContentItem(BaseModel):
    type: str                        # "text" or "image"
    source_lang_code: str
    target_lang_code: str
    text: str | None = None          # for type="text"
    url: str | None = None           # for type="image" (data URL or http URL)


class Message(BaseModel):
    role: str
    content: list[ContentItem] | str


class ChatRequest(BaseModel):
    model: str = MODEL_ALIAS
    messages: list[Message]
    max_tokens: int = 2048
    temperature: float = 0.0
    stream: bool = False


# ---- Helpers ----

def load_image_from_url(url: str) -> Image.Image:
    if url.startswith("data:"):
        # data:[<mediatype>][;base64],<data>
        header, encoded = url.split(",", 1)
        data = base64.b64decode(encoded)
        return Image.open(io.BytesIO(data)).convert("RGB")
    else:
        import httpx
        resp = httpx.get(url, timeout=30)
        resp.raise_for_status()
        return Image.open(io.BytesIO(resp.content)).convert("RGB")


def build_hf_messages(messages: list[Message]) -> list[dict]:
    """Convert OpenAI-style messages to the HuggingFace TranslateGemma format."""
    hf_messages = []

    for msg in messages:
        if isinstance(msg.content, str):
            hf_messages.append({"role": msg.role, "content": msg.content})
            continue

        if msg.role == "assistant":
            # Assistant messages are plain strings in TranslateGemma
            text = msg.content[0].text if msg.content else ""
            hf_messages.append({"role": "assistant", "content": text or ""})
            continue

        # User message — structured content
        item = msg.content[0]

        if item.type == "text":
            hf_messages.append({
                "role": "user",
                "content": [{
                    "type": "text",
                    "source_lang_code": item.source_lang_code,
                    "target_lang_code": item.target_lang_code,
                    "text": item.text or "",
                }],
            })

        elif item.type == "image":
            if not item.url:
                raise HTTPException(status_code=400, detail="Image content requires a 'url' field")
            image = load_image_from_url(item.url)
            # Pass the PIL image under "image" key — apply_chat_template extracts it
            # from there automatically; do NOT also pass images= to avoid duplicates.
            hf_messages.append({
                "role": "user",
                "content": [{
                    "type": "image",
                    "image": image,
                    "source_lang_code": item.source_lang_code,
                    "target_lang_code": item.target_lang_code,
                }],
            })

        else:
            raise HTTPException(status_code=400, detail=f"Unknown content type: {item.type!r}")

    return hf_messages


# ---- Endpoints ----

@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/v1/models")
async def list_models(request: Request):
    check_api_key(request)
    return {
        "object": "list",
        "data": [{
            "id": MODEL_ALIAS,
            "object": "model",
            "owned_by": "google",
            "created": int(time.time()),
        }],
    }


@app.post("/v1/chat/completions")
async def chat_completions(request: Request, body: ChatRequest):
    check_api_key(request)

    if body.stream:
        raise HTTPException(status_code=400, detail="Streaming is not supported")

    hf_messages = build_hf_messages(body.messages)

    # apply_chat_template extracts images from the content dict's "image" key automatically
    inputs = processor.apply_chat_template(
        hf_messages,
        tokenize=True,
        add_generation_prompt=True,
        return_dict=True,
        return_tensors="pt",
    )

    inputs = {k: v.to(model.device) for k, v in inputs.items()}
    input_len = inputs["input_ids"].shape[1]

    t0 = time.time()
    with torch.inference_mode():
        generation = model.generate(
            **inputs,
            do_sample=False,
            max_new_tokens=body.max_tokens,
        )
    elapsed = time.time() - t0

    # Decode only the newly generated tokens
    new_tokens = generation[0][input_len:]
    result = processor.decode(new_tokens, skip_special_tokens=True).strip()

    prompt_tokens = input_len
    completion_tokens = len(new_tokens)

    return {
        "id": f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": MODEL_ALIAS,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": result},
            "finish_reason": "stop",
        }],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
        "timings": {
            "predicted_ms": elapsed * 1000,
        },
    }
