# deploy.py
from starlette.requests import Request
from ray import serve
import logging, os, glob, json
from typing import Tuple, Any, Dict, List, Union

import torch
import torch.nn.functional as F
from transformers import AutoTokenizer, AutoModel, AutoModelForCausalLM

logger = logging.getLogger("ray.serve")

CACHE_ROOT = "/home/local/data/models/Embedding"   # HF cache-style root (contains models--ORG--NAME/)

def _resolve_snapshot_dir(cache_root: str, model_id: str) -> str:
    """
    Resolve a local HF snapshot directory for a repo like 'Org/Name' given a HF cache root.
    Expects: <cache_root>/models--Org--Name/snapshots/<hash>/
    """
    if "/" not in model_id:
        raise ValueError(f"Expected 'org/name' model_id, got: {model_id}")
    org, name = model_id.split("/", 1)
    base = os.path.join(cache_root, f"models--{org}--{name}", "snapshots")
    snaps = sorted(glob.glob(os.path.join(base, "*")))
    if not snaps:
        raise FileNotFoundError(
            f"No local snapshots found under {base}. "
            "Either allow online download once or pre-download/copy the repo here."
        )
    # Pick the newest snapshot (last lexicographically is fine for HF hashes)
    snap = snaps[-1]
    # Quick sanity check for expected files
    must_have = ["config.json", "tokenizer_config.json"]
    missing = [f for f in must_have if not os.path.exists(os.path.join(snap, f))]
    if missing:
        raise FileNotFoundError(f"Snapshot {snap} is missing: {missing}")
    return snap

def _mean_pool(last_hidden_state: torch.Tensor, attention_mask: torch.Tensor) -> torch.Tensor:
    # last_hidden_state: [B, T, H], attention_mask: [B, T]
    mask = attention_mask.unsqueeze(-1)                # [B, T, 1]
    summed = (last_hidden_state * mask).sum(dim=1)     # [B, H]
    counts = mask.sum(dim=1).clamp(min=1)              # [B, 1]
    return summed / counts

@serve.deployment(num_replicas=1)
class Embedder:
    """
    - Multiplexed by model: set header:  serve_multiplexed_model_id: <org/repo>
      e.g. 'Qwen/Qwen3-Embedding-0.6B'
    - GET /  -> health + usage
    - POST / -> JSON:
        {
          "prompt": "text" or ["list", "of", "texts"],
          "mode": "embed" | "gen",        # default "embed"
          "max_new_tokens": 64,            # generation pref
          "max_length": 0                  # optional fallback for generation
        }
    """

    def __init__(self):
        # If STRICT offline: export TRANSFORMERS_OFFLINE=1 (optional)
        # We still load from local snapshots either way.
        self.strict_offline = os.getenv("TRANSFORMERS_OFFLINE", "0") == "1"

    @serve.multiplexed(max_num_models_per_replica=2)
    async def get_model(self, model_id: str, mode: str) -> Tuple[Any, Any]:
        logger.info(f"Loading model '{model_id}'.")
        # Resolve a local snapshot path (no network hits)
        snap_dir = _resolve_snapshot_dir(CACHE_ROOT, model_id)
        logger.info(f"Using local snapshot: {snap_dir}")

        # IMPORTANT: Do NOT pass device_map to the tokenizer.
        tokenizer = AutoTokenizer.from_pretrained(snap_dir)  # local path

        if mode == "gen":
            model = AutoModelForCausalLM.from_pretrained(
                snap_dir,
                device_map="auto",  # let HF place it
            )
        else:
            model = AutoModel.from_pretrained(
                snap_dir,
                device_map="auto",
            )

        model.eval()
        return model, tokenizer

    async def __call__(self, http_request: Request):
        # Health check
        if http_request.method == "GET":
            return {
                "status": "ok",
                "message": "Ray Serve is running.",
                "ready": True,
                "usage": {
                    "headers": {"serve_multiplexed_model_id": "Qwen/Qwen3-Embedding-0.6B"},
                    "embed_json": {"prompt": "hello world"},
                    "gen_json": {
                        "prompt": "Write a haiku about Ray Serve",
                        "mode": "gen",
                        "max_new_tokens": 32
                    }
                }
            }

        # POST only beyond this point
        model_id = serve.get_multiplexed_model_id()
        if not model_id:
            return {"error": "Missing 'serve_multiplexed_model_id' header."}, 400

        try:
            data: Dict[str, Union[str, int, List[str]]] = await http_request.json()
        except Exception:
            return {"error": "Body must be application/json."}, 400

        prompt = data.get("prompt")
        if prompt is None:
            return {"error": "Missing 'prompt'."}, 400

        mode = str(data.get("mode", "embed")).lower()
        if mode not in {"embed", "gen"}:
            return {"error": "Invalid 'mode'. Use 'embed' or 'gen'."}, 400

        # Load model/tokenizer (cached across calls by multiplexing)
        try:
            model, tokenizer = await self.get_model(model_id, mode)
        except Exception as e:
            logger.exception("Model load failed.")
            return {
                "error": "Failed to load local snapshot for the requested model.",
                "detail": str(e),
                "hint": (
                    f"Ensure the HF cache-style path exists under {CACHE_ROOT}/models--<org>--<name>/snapshots/<hash> "
                    "and contains config.json / tokenizer files / model *.safetensors. "
                    "Alternatively, set HF_HOME to your cache root and use from_pretrained(model_id)."
                ),
            }, 500

        # === Generation path ===
        if mode == "gen":
            max_new = int(data.get("max_new_tokens", 64))
            max_len = int(data.get("max_length", 0)) or None  # legacy fallback
            inputs = tokenizer(prompt, return_tensors="pt")
            with torch.inference_mode():
                if max_len is not None:
                    ids = model.generate(**inputs, max_length=max_len)
                else:
                    ids = model.generate(**inputs, max_new_tokens=max_new)
            text = tokenizer.batch_decode(
                ids, skip_special_tokens=True, clean_up_tokenization_spaces=False
            )[0]
            return {"text": text}

        # === Embedding path (default) ===
        texts = [prompt] if isinstance(prompt, str) else prompt
        if not isinstance(texts, list) or not texts:
            return {"error": "'prompt' must be a non-empty string or list of strings."}, 400

        inputs = tokenizer(texts, return_tensors="pt", padding=True, truncation=True)
        with torch.inference_mode():
            outputs = model(**inputs)

        # Prefer pooler_output if available; otherwise mean-pool
        if hasattr(outputs, "pooler_output") and outputs.pooler_output is not None:
            emb = outputs.pooler_output
        else:
            emb = _mean_pool(outputs.last_hidden_state, inputs["attention_mask"])
        emb = F.normalize(emb, p=2, dim=-1).cpu()

        if isinstance(prompt, str):
            return emb[0].tolist()
        return [v.tolist() for v in emb]

app = Embedder.bind()
# Run:  serve run deploy:app

