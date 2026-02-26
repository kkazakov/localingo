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

MODEL_ID = os.getenv("MODEL_ID", "google/translategemma-12b-it")
MODEL_ALIAS = os.getenv("MODEL_ALIAS", "translategemma-12b-it")
API_KEY = os.getenv("API_KEY", "")

processor = None
model = None
model_type = None

IS_GGUF = ".gguf" in MODEL_ID.lower()


def parse_gguf_model_id(model_id):
  if ":" in model_id:
    repo, filename = model_id.split(":", 1)
    return repo, filename
  return model_id, None


def load_transformers_model(model_id):
  from transformers import AutoModelForImageTextToText, AutoProcessor
  global processor, model
  print(f"Loading transformers model: {model_id}", flush=True)
  processor = AutoProcessor.from_pretrained(model_id)
  model = AutoModelForImageTextToText.from_pretrained(
    model_id,
    device_map="auto",
    dtype=torch.bfloat16,
  )
  model.eval()
  print("Transformers model loaded.", flush=True)


def load_gguf_model(model_id):
  from llama_cpp import Llama
  from transformers import AutoTokenizer
  global processor, model
  
  repo, filename = parse_gguf_model_id(model_id)
  model_path = filename if filename else model_id
  
  print(f"Loading GGUF model: {repo}:{model_path}", flush=True)
  
  try:
    model = Llama.from_pretrained(
      repo_id=repo,
      filename=model_path,
      n_ctx=2048,
      n_gpu_layers=-1,
      verbose=False,
    )
  except Exception:
    if os.path.exists(model_path):
      model = Llama(
        model_path=model_path,
        n_ctx=2048,
        n_gpu_layers=-1,
        verbose=False,
      )
    else:
      raise
  
  try:
    processor = AutoTokenizer.from_pretrained(repo)
  except Exception:
    processor = None
  
  print("GGUF model loaded.", flush=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
  global processor, model, model_type
  
  if IS_GGUF:
    load_gguf_model(MODEL_ID)
    model_type = "gguf"
  else:
    load_transformers_model(MODEL_ID)
    model_type = "transformers"
  
  yield


app = FastAPI(lifespan=lifespan)


def check_api_key(request: Request):
  if not API_KEY:
    return
  auth = request.headers.get("Authorization", "")
  if not auth.startswith("Bearer ") or auth[len("Bearer "):] != API_KEY:
    raise HTTPException(status_code=401, detail="Invalid API key")


class ContentItem(BaseModel):
  type: str
  source_lang_code: str
  target_lang_code: str
  text: str | None = None
  url: str | None = None


class Message(BaseModel):
  role: str
  content: list[ContentItem] | str


class ChatRequest(BaseModel):
  model: str = MODEL_ALIAS
  messages: list[Message]
  max_tokens: int = 2048
  temperature: float = 0.0
  stream: bool = False


def load_image_from_url(url: str) -> Image.Image:
  if url.startswith("data:"):
    header, encoded = url.split(",", 1)
    data = base64.b64decode(encoded)
    return Image.open(io.BytesIO(data)).convert("RGB")
  else:
    import httpx
    resp = httpx.get(url, timeout=30)
    resp.raise_for_status()
    return Image.open(io.BytesIO(resp.content)).convert("RGB")


def build_hf_messages(messages: list[Message]) -> list[dict]:
  hf_messages = []

  for msg in messages:
    if isinstance(msg.content, str):
      hf_messages.append({"role": msg.role, "content": msg.content})
      continue

    if msg.role == "assistant":
      text = msg.content[0].text if msg.content else ""
      hf_messages.append({"role": "assistant", "content": text or ""})
      continue

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


def build_gguf_prompt(messages: list[Message]) -> str:
  prompt = ""
  
  for msg in messages:
    if isinstance(msg.content, str):
      text = msg.content
    elif msg.role == "assistant":
      text = msg.content[0].text if msg.content else ""
    elif msg.content and msg.content[0]:
      item = msg.content[0]
      if item.type == "text" and item.text:
        text = f"You are a professional {item.source_lang_code} to {item.target_lang_code} translator. Your goal is to accurately convey the meaning and nuances of the original text while adhering to the target language's grammar, vocabulary, and cultural sensitivities.\nProduce only the {item.target_lang_code} translation, without any additional explanations or commentary. Please translate the following {item.source_lang_code} text into {item.target_lang_code}:\n\n\n{item.text}"
      elif item.type == "image":
        text = "<image>"
      else:
        text = ""
    else:
      text = ""
    
    if msg.role == "user":
      prompt += f"<start_of_turn>user\n{text}<end_of_turn>\n"
    elif msg.role == "assistant":
      prompt += f"<start_of_turn>model\n{text}<end_of_turn>\n"
  
  prompt += "<start_of_turn>model\n"
  return prompt


@app.get("/health")
async def health():
  return {"status": "ok", "model_type": model_type}


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

  if model_type == "gguf":
    if any(c.type == "image" for msg in body.messages for c in msg.content if isinstance(msg.content, list)):
      raise HTTPException(status_code=400, detail="GGUF models do not support image input yet")
    
    prompt = build_gguf_prompt(body.messages)
    
    t0 = time.time()
    output = model.create_completion(
      prompt,
      max_tokens=body.max_tokens,
      temperature=body.temperature if body.temperature > 0 else 0.1,
      top_p=0.95,
      stop=["<end_of_turn>"],
    )
    elapsed = time.time() - t0
    
    result = output["choices"][0]["text"].strip()
    
    prompt_tokens = output["usage"]["prompt_tokens"]
    completion_tokens = output["usage"]["completion_tokens"]
  else:
    hf_messages = build_hf_messages(body.messages)

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
