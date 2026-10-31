"""Retrieval-augmented question answering over converted Konverter documents.

ingest -> chunk -> embed -> store -> retrieve -> answer with citations. The
converter itself is untouched: this package only reads its structured.json.
"""
