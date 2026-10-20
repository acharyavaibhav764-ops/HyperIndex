> **SUPERSEDED.** This stub is discarded.  v6 is now the phased PDF figure + VLM pipeline (Qwen via
> Ollama, no DeepSeek-OCR2 and no vLLM).  See `v6_plan.md`.  The text below is kept as a record only.

# v6 Scope Stub: vLLM Migration for DeepSeek-OCR2

**Status**: Planned future version — **DO NOT EXECUTE as part of any current session.**  
**Depends on**: v5 (PDF deep parser with DeepSeek-OCR2 integration) being fully functional.

---

## Goal

Migrate DeepSeek-OCR2 serving from HF Transformers (introduced in v5) to vLLM, for
production-grade batch throughput on the PDF branch's per-page OCR/VLM tier.

## Hardware Constraint

> **This version is not runnable on the current development machine (GTX 1650, 4GB VRAM).**

vLLM changes serving and batching efficiency — it does **not** reduce the model's VRAM
footprint. DeepSeek-OCR2 requires ≥8GB VRAM regardless of whether it runs under HF
Transformers or vLLM. vLLM v6 targets eventual production/deployment hardware with
adequate VRAM, not this dev laptop.

## Scope (to be detailed when v5 is near-complete)

- Replace `services/deepseek_ocr2_server.py` HF Transformers launcher with a vLLM
  `AsyncLLMEngine` serving backend.
- Update `config.py` DeepSeek-OCR2 serving settings for vLLM endpoint configuration.
- Validate batch-inference throughput improvement on PDF per-page OCR workloads.
- No changes to the parsing API, `ParserRouter`, or any v1–v4 component.

## Full Planning Deferred

Detailed plan (`parsing_arch_v6_vllm_migration.md`) to be written when v5 is near-
complete. The scope above is sufficient to reserve the version slot and document the
hardware constraint.
