"""Repair PDF ToUnicode CMaps from the canonical font-scoped store.

The repair is deliberately narrow: it only adds or replaces entries in
``/ToUnicode`` streams for embedded Identity-H/Identity-V Type0 fonts. It does
not touch page content, rendering, ``/ActualText``, or the mapping store.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from .fonts import cmap_mapping, document_fonts, font_identity


@dataclass
class FontRepair:
    font_xref: int
    base_font: str
    font_id: str
    cmap_entries: int
    additions: dict[int, str] = field(default_factory=dict)
    conflicts: dict[int, tuple[str, str]] = field(default_factory=dict)
    existing: dict[int, str] = field(default_factory=dict)

    def changed(self, replace_conflicts: bool = False) -> bool:
        return bool(self.additions or (replace_conflicts and self.conflicts))

    def result(self, replace_conflicts: bool = False) -> dict[int, str]:
        out = dict(self.existing)
        out.update(self.additions)
        if replace_conflicts:
            out.update({cid: new for cid, (_old, new)
                        in self.conflicts.items()})
        return out

    def to_dict(self, replace_conflicts: bool = False) -> dict:
        return {
            "font_xref": self.font_xref,
            "base_font": self.base_font,
            "font_id": self.font_id,
            "cmap_entries": self.cmap_entries,
            "additions": {str(cid): value
                          for cid, value in sorted(self.additions.items())},
            "conflicts": {
                str(cid): {"cmap": old, "store": new}
                for cid, (old, new) in sorted(self.conflicts.items())
            },
            "changed": self.changed(replace_conflicts),
        }


@dataclass
class RepairPlan:
    pdf: str
    fonts: list[FontRepair] = field(default_factory=list)
    issues: list[dict] = field(default_factory=list)
    replace_conflicts: bool = False

    @property
    def additions(self) -> int:
        return sum(len(font.additions) for font in self.fonts)

    @property
    def conflicts(self) -> int:
        return sum(len(font.conflicts) for font in self.fonts)

    @property
    def changed(self) -> bool:
        return any(font.changed(self.replace_conflicts) for font in self.fonts)

    def to_dict(self) -> dict:
        return {
            "pdf": self.pdf,
            "replace_conflicts": self.replace_conflicts,
            "additions": self.additions,
            "conflicts": self.conflicts,
            "changed": self.changed,
            "fonts": [font.to_dict(self.replace_conflicts)
                      for font in self.fonts],
            "issues": list(self.issues),
        }


def _codepoints_text(codepoints) -> str | None:
    try:
        return "".join(chr(int(cp)) for cp in codepoints)
    except (TypeError, ValueError):
        return None


def _key_name(doc, xref: int, key: str) -> str:
    try:
        kind, value = doc.xref_get_key(xref, key)
    except Exception:
        return ""
    if kind != "name":
        return ""
    return str(value or "").lstrip("/")


def _font_refs(doc, max_pages=None):
    found = document_fonts(doc, max_pages=max_pages)
    refs = []
    for xref, base in sorted(found.items()):
        refs.append({
            "font_xref": int(xref),
            "font_type": _key_name(doc, int(xref), "Subtype"),
            "base_font": base or "unknown",
            "encoding": _key_name(doc, int(xref), "Encoding"),
        })
    return refs


def build_repair_plan(doc, store: dict, *, replace_conflicts: bool = False,
                      max_pages=None) -> RepairPlan:
    plan = RepairPlan(
        pdf=getattr(doc, "name", "") or "",
        replace_conflicts=replace_conflicts,
    )
    store_fonts = store.get("fonts", {})
    undecodable = set(store.get("undecodable", []))
    for ref in _font_refs(doc, max_pages=max_pages):
        xref = ref["font_xref"]
        base = ref["base_font"]
        if ref["font_type"] != "Type0" or ref["encoding"] not in (
                "Identity-H", "Identity-V"):
            continue
        mapping = cmap_mapping(doc, xref)
        if not mapping:
            plan.issues.append({
                "font_xref": xref,
                "base_font": base,
                "reason": "no ToUnicode CMap",
            })
            continue
        identity = font_identity(doc, base, xref)
        store_map = store_fonts.get(identity.font_id) or {}
        if not store_map:
            continue
        existing = {}
        for cid, codepoints in mapping.items():
            value = _codepoints_text(codepoints)
            if value is not None:
                existing[cid] = value
        font = FontRepair(
            font_xref=xref,
            base_font=base,
            font_id=identity.font_id,
            cmap_entries=len(existing),
            existing=existing,
        )
        for cid, value in sorted(store_map.items()):
            cid = int(cid)
            if not value or f"{identity.font_id}\u2571{cid}" in undecodable:
                continue
            current = existing.get(cid)
            if current is None:
                font.additions[cid] = value
            elif current != value:
                font.conflicts[cid] = (current, value)
        plan.fonts.append(font)
    return plan


def _utf16_hex(value: str) -> str:
    return value.encode("utf-16-be", errors="surrogatepass").hex().upper()


def cmap_bytes(mapping: dict[int, str]) -> bytes:
    entries = []
    for cid, value in sorted(mapping.items()):
        cid = int(cid)
        if cid < 0 or cid > 0xFFFF or not value:
            continue
        encoded = _utf16_hex(value)
        if not encoded:
            continue
        entries.append((cid, encoded))

    lines = [
        "%!PS-Adobe-3.0 Resource-CMap",
        "%%DocumentNeededResources: ProcSet (CIDInit)",
        "%%IncludeResource: ProcSet (CIDInit)",
        "%%BeginResource: CMap (Adobe-Identity-UCS)",
        "%%Title: (Adobe-Identity-UCS Adobe Identity 0)",
        "%%Version: 1",
        "%%EndComments",
        "/CIDInit /ProcSet findresource begin",
        "12 dict begin",
        "begincmap",
        "/CIDSystemInfo 3 dict dup begin",
        "/Registry (Adobe) def",
        "/Ordering (UCS) def",
        "/Supplement 0 def",
        "end def",
        "/CMapName /Adobe-Identity-UCS def",
        "/CMapType 2 def",
        "1 begincodespacerange",
        "<0000> <FFFF>",
        "endcodespacerange",
    ]
    for start in range(0, len(entries), 100):
        chunk = entries[start:start + 100]
        lines.append(f"{len(chunk)} beginbfchar")
        for cid, encoded in chunk:
            lines.append(f"<{cid:04X}> <{encoded}>")
        lines.append("endbfchar")
    lines.extend([
        "endcmap",
        "CMapName currentdict /CMap defineresource pop",
        "end",
        "end",
        "%%EndResource",
        "%%EOF",
        "",
    ])
    return "\n".join(lines).encode("ascii")


def _install_cmap(doc, font_xref: int, mapping: dict[int, str]) -> int:
    data = cmap_bytes(mapping)
    xref = doc.get_new_xref()
    doc.update_object(xref, "<<>>")
    doc.update_stream(xref, data, compress=1)
    doc.xref_set_key(font_xref, "ToUnicode", f"{xref} 0 R")
    return xref


def write_repair(doc, plan: RepairPlan, output: str | Path) -> int:
    changed = [font for font in plan.fonts
               if font.changed(plan.replace_conflicts)]
    if not changed:
        return 0
    for font in changed:
        _install_cmap(doc, font.font_xref,
                       font.result(plan.replace_conflicts))
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(f".{out.name}.{os.getpid()}.tmp")
    try:
        doc.save(str(tmp), garbage=0, deflate=True)
        os.replace(tmp, out)
    finally:
        if tmp.exists():
            tmp.unlink()
    return len(changed)


def format_plan(plan: RepairPlan) -> str:
    lines = [
        f"PDF: {plan.pdf or '(unknown)'}",
        f"Fonts with store mappings: {len(plan.fonts)} \u00b7 "
        f"additions: {plan.additions} \u00b7 conflicts: {plan.conflicts}"
        + (" (replace)" if plan.replace_conflicts else " (preserve)"),
    ]
    if not plan.fonts:
        lines.append("No patchable fonts.")
    for font in plan.fonts:
        state = "patch" if font.changed(plan.replace_conflicts) else "unchanged"
        lines.append(
            f"[{state}] {font.font_id} \u00b7 xref {font.font_xref} \u00b7 "
            f"{font.cmap_entries} cmap entries")
        for cid, value in sorted(font.additions.items()):
            lines.append(f"  + cid {cid}: {value!r}")
        for cid, (old, new) in sorted(font.conflicts.items()):
            note = "replace" if plan.replace_conflicts else "preserve"
            lines.append(
                f"  ! cid {cid}: cmap {old!r} -> store {new!r} ({note})")
    if plan.issues:
        shown = plan.issues[:10]
        lines.append(f"Skipped fonts: {len(plan.issues)}")
        for issue in shown:
            lines.append(
                f"  xref {issue['font_xref']} {issue['base_font']}: "
                f"{issue['reason']}")
        if len(plan.issues) > len(shown):
            lines.append(f"  \u2026 {len(plan.issues) - len(shown)} more")
    return "\n".join(lines)
