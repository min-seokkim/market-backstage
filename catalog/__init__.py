"""Catalog read API.

Wraps YAML data + the dynamic *_dyn registry behind a single
`all_active_*(con)` interface that runtime code reads. Static YAML data
seeds the registry; LLM agenda extractor adds proposals; trust gate
promotes them.
"""
