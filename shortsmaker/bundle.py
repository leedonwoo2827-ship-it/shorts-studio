"""Load and validate a chNN_bundle directory."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

IMG_EXTS = (".png", ".jpg", ".jpeg", ".webp")
AUD_EXTS = (".wav", ".mp3", ".m4a", ".flac")


@dataclass
class Scene:
    index: int                       # 1-based scene number from JSON
    title: str
    narration_text: str
    narration_seconds_hint: float    # JSON hint, real duration comes from ffprobe
    image_path: Optional[Path]
    audio_path: Optional[Path]
    subtitle_path: Optional[Path]    # individual SRT if present
    scene_meta: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


@dataclass
class Bundle:
    root: Path
    chapter: int                     # e.g. 4
    chapter_id: str                  # e.g. "ch04"
    title: str
    subtitle: str
    aspect_ratio: str
    total_duration_hint: float
    scenes: list[Scene]
    combined_srt_path: Optional[Path]
    script_json_path: Path
    warnings: list[str] = field(default_factory=list)

    @property
    def draft_dir(self) -> Path:
        return self.root / "draft"

    @property
    def work_dir(self) -> Path:
        return self.draft_dir / "_work"


def _find_image(images_dir: Path, chapter_id: str, scene_idx: int, hint: str) -> Optional[Path]:
    """Find image file. Try JSON hint first, then fall back across naming variants.

    Handles cases where:
    - JSON says .png but actual is .jpeg                            (stem fallback)
    - Actual file has _1/_2/... suffix the JSON doesn't             (stem_N fallback)
    - Actual file is just chNN_XX.jpeg without descriptive suffix   (prefix glob)
    - Actual files dropped the 'ch' prefix entirely (e.g. 22_08_*)  (alt-prefix glob)
    """
    if hint:
        exact = images_dir / hint
        if exact.exists():
            return exact
        stem = Path(hint).stem
        # 2a) same stem, different extension
        for ext in IMG_EXTS:
            cand = images_dir / f"{stem}{ext}"
            if cand.exists():
                return cand
        # 2b) same stem + _N suffix (FlowGenie variants like name_1.jpeg, name_2.jpeg)
        for ext in IMG_EXTS:
            variants = sorted(
                p for p in images_dir.glob(f"{stem}_*{ext}") if p.is_file()
            )
            if variants:
                return variants[0]  # lexical order picks _1 first

    # Try both "ch22_08*" and "22_08*" prefix variants (some authors drop the 'ch')
    numeric_part = chapter_id[2:] if chapter_id.startswith("ch") else chapter_id
    prefixes = [
        f"{chapter_id}_{scene_idx:02d}",       # ch22_08
        f"{numeric_part}_{scene_idx:02d}",     # 22_08
    ]
    matches: list[Path] = []
    for prefix in prefixes:
        for ext in IMG_EXTS:
            matches.extend(p for p in images_dir.glob(f"{prefix}*{ext}") if p.is_file())
    if not matches:
        return None
    # Dedupe while preserving lexical "_1 before _2" preference, prefer shorter names first.
    seen: set[Path] = set()
    deduped: list[Path] = []
    for p in matches:
        if p in seen:
            continue
        seen.add(p)
        deduped.append(p)
    deduped.sort(key=lambda p: (len(p.name), p.name))
    return deduped[0]


def _find_audio(audio_dir: Path, chapter_id: str, scene_idx: int) -> Optional[Path]:
    prefix = f"{chapter_id}_{scene_idx:02d}"
    for ext in AUD_EXTS:
        cand = audio_dir / f"{prefix}_narration{ext}"
        if cand.exists():
            return cand
    matches: list[Path] = []
    for ext in AUD_EXTS:
        matches.extend(p for p in audio_dir.glob(f"{prefix}*{ext}") if p.is_file())
    return matches[0] if matches else None


def _find_subtitle(subs_dir: Path, chapter_id: str, scene_idx: int) -> Optional[Path]:
    prefix = f"{chapter_id}_{scene_idx:02d}"
    for name in (f"{prefix}_narration.srt", f"{prefix}.srt"):
        cand = subs_dir / name
        if cand.exists():
            return cand
    matches = list(subs_dir.glob(f"{prefix}*.srt"))
    return matches[0] if matches else None


def _find_combined_srt(subs_dir: Path, chapter_id: str) -> Optional[Path]:
    cand = subs_dir / f"{chapter_id}.srt"
    return cand if cand.exists() else None


def load_bundle(bundle_root: Path) -> Bundle:
    """Load a chNN_bundle directory, validating that script/images/audio/subtitles exist.

    Returns a Bundle dataclass. Raises FileNotFoundError or ValueError on hard errors.
    Soft issues (missing-for-a-scene) are recorded in Scene.warnings and Bundle.warnings.
    """
    bundle_root = bundle_root.resolve()
    if not bundle_root.is_dir():
        raise FileNotFoundError(f"Bundle root not found: {bundle_root}")

    script_dir = bundle_root / "script"
    images_dir = bundle_root / "images"
    audio_dir = bundle_root / "audio"
    subs_dir = bundle_root / "subtitles"

    for required in (script_dir, images_dir, audio_dir, subs_dir):
        if not required.is_dir():
            raise FileNotFoundError(f"Required subdir missing: {required}")

    script_files = list(script_dir.glob("*_script.json"))
    if not script_files:
        raise FileNotFoundError(f"No *_script.json in {script_dir}")
    if len(script_files) > 1:
        script_files.sort()
    script_json_path = script_files[0]

    data = json.loads(script_json_path.read_text(encoding="utf-8"))
    chapter = int(data.get("chapter") or 0)
    if not chapter:
        m = re.search(r"ch(\d{1,3})", script_json_path.stem)
        chapter = int(m.group(1)) if m else 0
    chapter_id = f"ch{chapter:02d}"

    raw_scenes = data.get("scenes") or []
    if not raw_scenes:
        raise ValueError(f"No scenes[] in {script_json_path}")

    scenes: list[Scene] = []
    bundle_warnings: list[str] = []
    for pos, raw in enumerate(raw_scenes):
        # ScriptForge schema evolved: older bundles used 'scene', newer ones use
        # 'scene_number'. Accept either; fall back to array position (1-based).
        raw_idx = raw.get("scene")
        if raw_idx is None:
            raw_idx = raw.get("scene_number")
        if raw_idx is None:
            raw_idx = pos + 1
        idx = int(raw_idx)
        img = _find_image(images_dir, chapter_id, idx, raw.get("image_filename") or "")
        aud = _find_audio(audio_dir, chapter_id, idx)
        sub = _find_subtitle(subs_dir, chapter_id, idx)

        scene_warnings: list[str] = []
        if img is None:
            scene_warnings.append("image not found")
        if aud is None:
            scene_warnings.append("audio not found")

        scenes.append(Scene(
            index=idx,
            title=raw.get("title") or "",
            narration_text=raw.get("narration_text") or "",
            narration_seconds_hint=float(raw.get("narration_seconds") or 0.0),
            image_path=img,
            audio_path=aud,
            subtitle_path=sub,
            scene_meta=raw.get("scene_meta") or {},
            warnings=scene_warnings,
        ))

    combined_srt = _find_combined_srt(subs_dir, chapter_id)
    if combined_srt is None and any(s.subtitle_path is None for s in scenes):
        bundle_warnings.append(
            f"No per-scene SRT for some scenes and no combined {chapter_id}.srt either"
        )

    hard_missing = [s.index for s in scenes if s.image_path is None or s.audio_path is None]
    if hard_missing:
        raise ValueError(
            f"Scenes missing image/audio (cannot render): {hard_missing}. "
            f"Run with --probe to see details."
        )

    return Bundle(
        root=bundle_root,
        chapter=chapter,
        chapter_id=chapter_id,
        title=data.get("title") or "",
        subtitle=data.get("subtitle") or "",
        aspect_ratio=data.get("aspect_ratio") or "16:9",
        total_duration_hint=float(data.get("total_duration_seconds") or 0.0),
        scenes=scenes,
        combined_srt_path=combined_srt,
        script_json_path=script_json_path,
        warnings=bundle_warnings,
    )
