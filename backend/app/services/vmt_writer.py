"""Generate the ``.vmt`` material file that pairs with a spray ``.vtf``.

A spray VMT is a minimal ``UnlitGeneric`` material that points at the texture in
``materials/vgui/logos`` and enables translucency so transparent sprays render
correctly. The ``$basetexture`` path is relative to ``materials/`` and must use
forward slashes and no extension.
"""
from __future__ import annotations

import re

#: Characters Source treats safely in a material/texture name.
_SAFE_NAME = re.compile(r"[^A-Za-z0-9 _\-.]")


def sanitize_spray_name(name: str) -> str:
    """Reduce an arbitrary name to a safe spray/material base name.

    Strips path separators and unusual characters, collapses whitespace, and
    falls back to ``spray`` if nothing usable remains.
    """
    name = name.strip().rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    for ext in (".vtf", ".vmt"):
        if name.lower().endswith(ext):
            name = name[: -len(ext)]
    name = _SAFE_NAME.sub("", name).strip().replace(" ", "_")
    return name or "spray"


def build_vmt(name: str, *, translucent: bool = True) -> str:
    """Return VMT text for a spray named ``name`` (without extension)."""
    base = sanitize_spray_name(name)
    lines = [
        '"UnlitGeneric"',
        "{",
        f'\t"$basetexture" "vgui/logos/{base}"',
        '\t"$ignorez" "1"',
        '\t"$vertexcolor" "1"',
        '\t"$vertexalpha" "1"',
    ]
    if translucent:
        lines.append('\t"$translucent" "1"')
    lines.append("}")
    return "\n".join(lines) + "\n"


def build_ui_vmt(name: str) -> str:
    """VMT matching the ``logos/ui`` thumbnail TF2 writes when importing a spray."""
    base = sanitize_spray_name(name)
    return (
        '"UnlitGeneric"\n{\n'
        '\t"$translucent" 1\n'
        f'\t"$basetexture" "vgui/logos/{base}"\n'
        '\t"$vertexcolor" 1\n'
        '\t"$vertexalpha" 1\n'
        '\t"$no_fullbright" 1\n'
        '\t"$ignorez" 1\n'
        "}\n"
    )
