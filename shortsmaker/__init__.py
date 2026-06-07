"""Standalone vertical-shorts maker (self-contained engine).

Reads a chNN_bundle (script/images/audio/subtitles) and renders a 9:16 ~30s
teaser with a modern 3-band layout whose split + content varies per beat.
The per-beat text (top hook / bottom caption) is editable via a spec, so the
web UI can let the user finalize wording before rendering.
"""
__version__ = "0.1.0"
