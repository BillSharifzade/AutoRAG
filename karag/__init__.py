"""KARAG — Koinot Auto RAG.

A multi-tenant, RBAC-governed retrieval + verified-skills platform.

Design principles:
  * Provider-agnostic: generation and embeddings sit behind swappable adapters
    (Fake for offline tests, Ollama for free local runs, Claude Opus 4.8 for prod).
  * Two planes: knowledge (RAG over documents) and data (verified "skills").
  * Security first: tenant isolation and access control are enforced at
    *retrieval time*, never by asking the model to withhold what it has seen.
"""

__version__ = "0.1.0"
