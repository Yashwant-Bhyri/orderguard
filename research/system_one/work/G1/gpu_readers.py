"""G1 (lead experiment): self-hosted decision models as zero-shot readers on T05's exact evaluation set.

Runs on the GPU host. Reads items.jsonl (state + the three T05 questions, no labels) and writes, per model,
scores_<model>.jsonl with P(true) for each question. Scoring against labels happens on the Mac (score.py).

Models (each from its own Hugging Face card, native typed-decision API, bf16, nothing decoded):
  karpo9    MachinePulseAI/karpo-decision-9B   one card
  clefflash Cloudflare/clef-flash              one card
  karpo31   MachinePulseAI/karpo-decision-31B  split across the two cards
  clef27    Cloudflare/clef                    split across the two cards
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import torch

REPOS = {
    "karpo9": "MachinePulseAI/karpo-decision-9B",
    "karpo31": "MachinePulseAI/karpo-decision-31B",
    "clefflash": "Cloudflare/clef-flash",
    "clef27": "Cloudflare/clef",
}
FEATURES = ("hype", "authority_language", "support_gap")


def max_memory() -> dict:
    n = torch.cuda.device_count()
    return {i: "44GiB" for i in range(n)} | {"cpu": "200GiB"}


def split(module: torch.nn.Module, no_split: list[str]) -> torch.nn.Module:
    """Spread a model's layers over the visible cards (only when more than one is visible)."""
    if torch.cuda.device_count() < 2:
        return module.to("cuda:0")
    from accelerate import dispatch_model, infer_auto_device_map
    dmap = infer_auto_device_map(module, max_memory=max_memory(), no_split_module_classes=no_split)
    print("device map:", sorted({str(v) for v in dmap.values()}), flush=True)
    return dispatch_model(module, device_map=dmap)


class MoveIn(torch.nn.Module):
    """Wrap a small head so its input is moved to the head's own card first."""

    def __init__(self, inner: torch.nn.Module, device: torch.device) -> None:
        super().__init__()
        self.inner, self.dev = inner.to(device), device

    def forward(self, x, *a, **k):
        return self.inner(x.to(self.dev), *a, **k)


# ------------------------------------------------------------------------------------------------------------ Karpo
def karpo_runner(path: str):
    from karpo_decision import checkpoint as ck
    from karpo_decision.decider import Decider

    orig = ck.load

    def load_cpu_then_split(directory, device="cuda", dtype=torch.bfloat16):
        c = orig(directory, "cpu", dtype)
        layer_cls = sorted({type(m).__name__ for m in c.backbone.modules() if "DecoderLayer" in type(m).__name__})
        backbone = split(c.backbone, layer_cls)
        last = torch.device(f"cuda:{torch.cuda.device_count() - 1}")
        return ck.Checkpoint(c.config, c.processor, backbone, MoveIn(c.readout, last), c.directory, c.family)

    ck.load = load_cpu_then_split
    decider = Decider.from_pretrained(path)
    first = next(decider.ckpt.backbone.parameters()).device
    decider.device = first

    def run(batch):
        out = decider.decide(batch)
        return [{q: float(r["answers"][q]["noul"]) for q in FEATURES} for r in out]

    return run


# ------------------------------------------------------------------------------------------------------------- Clef
def clef_runner(path: str):
    sys.path.insert(0, path)
    from safetensors.torch import load_file
    from transformers import AutoProcessor, Qwen3_5ForConditionalGeneration
    from joint_schema_model import JointSchemaHead, collate_records, encode_record

    kw = dict(dtype=torch.bfloat16)
    if torch.cuda.device_count() > 1:
        kw.update(device_map="auto", max_memory=max_memory())
    else:
        kw.update(device_map={"": "cuda:0"})
    backbone = Qwen3_5ForConditionalGeneration.from_pretrained(path, **kw).eval()
    backbone.config.use_cache = False
    head = JointSchemaHead(**json.loads((Path(path) / "joint_head_config.json").read_text()))
    head.load_state_dict(load_file(str(Path(path) / "joint_head.safetensors")), strict=True)
    hdev = torch.device(f"cuda:{torch.cuda.device_count() - 1}")
    head = head.to(device=hdev, dtype=torch.bfloat16).eval()
    processor = AutoProcessor.from_pretrained(path)
    text_model = backbone.model.language_model if hasattr(backbone.model, "language_model") else backbone.model
    in_dev = next(text_model.parameters()).device
    emb = backbone.get_output_embeddings().weight

    @torch.inference_mode()
    def run(batch):
        enc = [encode_record(processor.tokenizer, r, max_length=16384, processor=processor) for r in batch]
        b = collate_records(enc, processor.tokenizer.pad_token_id, in_dev)
        hid = text_model(input_ids=b["input_ids"], attention_mask=b["attention_mask"], use_cache=False,
                         return_dict=True).last_hidden_state
        logits = head(hid.to(hdev), b["input_ids"].to(hdev), b["attention_mask"].to(hdev), b["records"], emb.to(hdev))
        rows = []
        for e, per_q in zip(enc, logits):
            row = {}
            for q, lg in zip(e.questions, per_q):
                probs = dict(zip(q.option_ids, lg.float().softmax(-1).tolist()))
                row[q.question_id] = float(probs["true"])
            rows.append(row)
        return rows

    return run


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True, choices=sorted(REPOS))
    ap.add_argument("--items", default="items.jsonl")
    ap.add_argument("--out-dir", default=".")
    ap.add_argument("--limit", type=int, default=0, help="smoke test: first N items only")
    ap.add_argument("--batch", type=int, default=4)
    a = ap.parse_args()

    from huggingface_hub import snapshot_download
    t0 = time.time()
    path = snapshot_download(REPOS[a.model])
    print(f"{a.model}: weights ready in {time.time() - t0:.0f}s; cards visible: {torch.cuda.device_count()}", flush=True)
    t0 = time.time()
    run = karpo_runner(path) if a.model.startswith("karpo") else clef_runner(path)
    print(f"{a.model}: loaded in {time.time() - t0:.0f}s", flush=True)

    items = [json.loads(l) for l in open(a.items)]
    if a.limit:
        items = items[: a.limit]
    out = Path(a.out_dir) / f"scores_{a.model}{'_smoke' if a.limit else ''}.jsonl"
    done = {json.loads(l)["i"] for l in out.open()} if out.exists() else set()
    lat = []
    with out.open("a") as f:
        todo = [it for it in items if it["i"] not in done]
        for k in range(0, len(todo), a.batch):
            chunk = todo[k:k + a.batch]
            reqs = [{"model": REPOS[a.model], "state": it["state"],
                     "questions": {q: {"type": "noul", "instructions": it["questions"][q]} for q in FEATURES}}
                    for it in chunk]
            t = time.time()
            rows = run(reqs)
            lat.append((time.time() - t) / len(chunk))
            for it, row in zip(chunk, rows):
                f.write(json.dumps({"i": it["i"], **row}) + "\n")
            f.flush()
            if (k // a.batch) % 25 == 0:
                print(f"{a.model}: {k + len(chunk)}/{len(todo)} done, {lat[-1] * 1000:.0f} ms/action", flush=True)
    if lat:
        lat.sort()
        print(f"{a.model}: done. median {lat[len(lat) // 2] * 1000:.0f} ms/action, "
              f"peak memory {[round(torch.cuda.max_memory_allocated(i) / 2**30, 1) for i in range(torch.cuda.device_count())]} GiB",
              flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
