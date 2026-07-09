# Portfolio Freeze

This is a public portfolio snapshot of a research project, not a trading
product.

## Included

- Domain model for actor-based Korean political-economy simulation.
- SQLite schema and persistence helpers.
- Source adapters for official data feeds.
- Dynamic catalog and canonical resolution layers.
- `NarrativeAssessment` contract between Layer 1 reasoning and future
  Layer 2 position inference.
- Unit tests and health-check scripts.

## Excluded

- API keys and `.env`.
- Live SQLite databases (`data/*.db`, `data/*.db-*`).
- Run logs, local caches, generated archives, and local tool state.
- Any broker integration or execution layer.

## Current Status

Implemented:

- Schema v2 with NFKC normalization, hot identity fields, tier fields,
  relationship strength, and event impact fields.
- PR-CONTRACT-v0 `NarrativeAssessment` dataclasses and v0 minimal
  synthesizer.
- PR4-CANONICAL organization/person canonical state.
- PR-PARTY-CANONICAL party canonical state and independent handling.

Not implemented:

- Full LLM narrative extraction.
- Reality-gap detector.
- Future narrative generator.
- Verification stack stages A-F.
- Layer 2 sizing, timing, exit, risk, and execution.

## Validation Snapshot

On the local frozen workspace:

- `python -m pytest -q`: 127 tests passing.
- `python -m scripts.verify_db`: 12 / 12 on the local live DB copy.
- `python -m scripts.verify_contract`: 9 / 9 on the local live DB copy.
- `python -m scripts.verify_canonical`: 18 / 18 on the local live DB copy.

The live DB is not part of the public repository. Health checks require a
rebuilt or locally provided DB.

## Publishing Note

The public branch should not include historical blobs for `data/*.db` or
generated caches. If publishing to a new GitHub repository, use a clean
snapshot branch or rewrite/export history before pushing so large private
database blobs are not present in Git history.
