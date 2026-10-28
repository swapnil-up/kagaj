"""Structure-preserving extraction of PDF schedule tables via marked regions.

Pipeline for one PDF branch file:

1. render pages to PNG (cached in ``output/water/rendered/<branch>/``);
2. OCR to coordinate lines (cached in ``output/water/ocr/<stem>.ocr.json``);
3. for each marked region, assemble records by column geometry
   (:mod:`water_parser.spatial`);
4. parse numeric/date/time fields deterministically (:mod:`water_parser.fields`);
5. translate area names with one focused Gemini call per branch;
6. validate (:mod:`water_parser.validate`) and emit the same reservoir/zone
   shape that the LLM path produces, so ``build`` is unchanged.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from . import columns as colmod
from . import fields, ocr, render, schema, spatial, validate

_TOKEN_SPLIT = re.compile(r"[,;/|।\n]+")

_PERIOD_WORDS = {
    w for words in fields.PERIODS.values() for w in words
} | set(fields.TOMORROW)

_NOISE = {
    "स्थान", "समय", "गते", "देखि", "सम्म", "डीएमए", "डिएमए", "डी.एम.ए",
    "पालो", "सिनं", "सि.नं", "सि.नं.", "कैफियत", "नोट", "सम्पर्क", "नाम",
    "बार", "मिति", "दिन", "क्षेत्र", "एरिया", "पानी", "बितरण", "हुने",
    "टंकी", "पोखरी", "शाखा", "कार्यालय", "समयसीमा", "समूह", "एसएन",
}


def _lines_text(lines: list[str]) -> str:
    return " ".join(lines or []).strip()


_TANK_WORDS = ("टयांकी", "ट्यांकी", "ट्यांकीबाट", "टंकी", "टंकीबाट", "पोखरी",
               "व्यांकी", "व्यांकीबाट", "व्याकी", "यांकी", "टयाँकी", "ट्याँकी")
_RESERVOIR_CUT = re.compile(r"\s*(?:बाट|बाटै|\||।)")

# A time expression at the start of an area token, left behind when OCR merges a
# time cell with the adjacent area cell (e.g. "दिउसो १२:००जानेस्वोर").
_LEAD_TIME = re.compile(
    r"^(?:(?:बिहान|विहान|दिउँसो|दिउसो|दिउंसो|बेलुका|बेलुकी|साँझ|राति|रात|भोलि|भोलिपल्ट)\s*)*"
    r"(?:\d{1,2}\s+)*"
    r"\d{1,2}\s*[:.।]\s*\d{1,2}\s*(?:बजे)?\s*"
)


def split_leading_time(token: str) -> tuple[str | None, str]:
    """Split an OCR token into a leading time phrase and the remaining text."""
    m = _LEAD_TIME.match(token)
    if not m:
        return None, token
    return m.group(0).strip(), token[m.end():].strip()


def detect_reservoir(lines: list[dict], region: dict) -> str | None:
    """Find the tank/reservoir heading printed above the table on this page."""
    header_skip = region["row_scan"]["header_skip_y"]
    best = None
    for ln in lines:
        if ln["page"] != region.get("page") or ln["y"] >= header_skip:
            continue
        if any(w in ln["text"] for w in _TANK_WORDS):
            if best is None or len(ln["text"]) > len(best):
                best = ln["text"]
    if not best:
        return None
    name = _RESERVOIR_CUT.split(best)[0].strip(" |।")
    name = re.sub(r"पानी$", "", name).strip()
    return name or None


def clean_areas(lines: list[str], recover_times: bool = False) -> tuple[list[str], list[str]]:
    """Split raw cell lines into place-name tokens, dropping noise.

    When ``recover_times`` is set, a leading time phrase (from an OCR box that
    merged a time cell with the area cell) is stripped off and collected.
    """
    out: list[str] = []
    times: list[str] = []
    for line in lines or []:
        for tok in _TOKEN_SPLIT.split(line or ""):
            tok = tok.strip(" .|-–—*")
            if recover_times:
                t, tok = split_leading_time(tok)
                if t:
                    times.append(t)
            if len(tok) < 2:
                continue
            if tok in _NOISE or tok in _PERIOD_WORDS:
                continue
            if re.fullmatch(r"[\d.:ः]+", tok):
                continue
            if fields._DMA.fullmatch(fields.to_ascii_digits(tok)):
                continue
            if tok not in out:
                out.append(tok)
    return out, times


_TIME_SPLIT = re.compile(r"देखि|देखे|देख")


def _split_time(rec: dict) -> tuple[str, str]:
    """Return (from_text, to_text) from either separate or combined time cells."""
    if "time" in rec:
        combined = _lines_text(rec.get("time"))
        m = _TIME_SPLIT.search(combined)
        if m:
            return combined[:m.start()].strip(), combined[m.end():].strip()
        return combined, ""
    return _lines_text(rec.get("time_from")), _lines_text(rec.get("time_to"))


def _record_to_zone(rec: dict, region: dict) -> dict:
    days, _ = fields.parse_days(_lines_text(rec.get("days")))
    from_text, to_text = _split_time(rec)
    areas_np, recovered_times = clean_areas(rec.get("areas"), recover_times=True)
    if not to_text and recovered_times:
        to_text = recovered_times[0]
    win = fields.resolve_window(from_text, to_text)
    contacts, _ = clean_areas(rec.get("contacts"))
    cols = sorted(region.get("columns") or {})
    zone = {
        "dma": fields.parse_dma(_lines_text(rec.get("dma"))),
        "label": _lines_text(rec.get("label")) or None,
        "days": days,
        "time_from": win["time_from"],
        "time_to": win["time_to"],
        "areas_np": areas_np,
        "areas_en": [],
        "contacts": contacts,
        "notes": _lines_text(rec.get("notes")) or None,
        "time_tags": win["flags"],
        "source_columns": cols,
    }
    return validate.validate_zone(zone)


def _forward_fill(zones: list[dict], fields_to_fill: list[str]) -> None:
    """Inherit merged-cell values (e.g. DMA, days) down from the prior zone."""
    prev: dict = {}
    for z in zones:
        for f in fields_to_fill:
            cur = z.get(f)
            if cur in (None, "", []) and prev.get(f) not in (None, "", []):
                z[f] = list(prev[f]) if isinstance(prev[f], list) else prev[f]
        z["review_flags"] = validate.flag_zone(z, set(z.get("source_columns") or []) or None)
        prev = z


def translate_areas(areas_np: list[str], log=None) -> dict[str, str]:
    """One focused Gemini call: unique Nepali area names -> Roman names."""
    unique = [a for a in dict.fromkeys(areas_np) if a]
    if not unique:
        return {}
    try:
        result = _call_areas(unique)
    except Exception as err:  # translation is best-effort
        if log:
            log(f"[extract]   area translation failed: {err}")
        return {}
    mapping = result.get("map") or {}
    if not isinstance(mapping, dict):
        if log:
            log("[extract]   area translation returned no map — skipping")
        return {}
    hit = sum(1 for u in unique if mapping.get(u))
    if log:
        log(f"[extract]   translated {hit}/{len(unique)} area names")
    return {u: mapping[u] for u in unique if mapping.get(u)}


def _call_areas(unique: list[str]) -> dict:
    from . import gemini

    return gemini.call_structured(schema.build_areas_prompt(unique))


def _load_or_make_lines(raw_path: Path, branch: str, log=None) -> list[dict]:
    stem = raw_path.stem
    ocr_cache = _ocr_cache_path(stem)
    if ocr_cache.exists():
        if log:
            log(f"[extract]   cached OCR: {ocr_cache.name}")
        return ocr.load_lines(ocr_cache)

    pngs = sorted(_render_dir(branch).glob(f"{stem}_page*.png"))
    if not pngs:
        pngs = render.render_pdf(raw_path, _render_dir(branch), log=log)
    lines = ocr.ocr_pngs(pngs, log=log)
    ocr.save_lines(lines, ocr_cache)
    return lines


def _render_dir(branch: str) -> Path:
    from . import paths

    return paths.RENDER_DIR / branch


def _ocr_cache_path(stem: str) -> Path:
    from . import paths

    return paths.OCR_DIR / f"{stem}.ocr.json"


def extract_pdf(raw_path: str | Path, regions: dict, branch: str,
                branch_np: str | None = None, branch_en: str | None = None,
                month_bs: str | None = None, log=None) -> dict:
    """Extract one PDF branch file into the standard reservoir/zone document."""
    raw_path = Path(raw_path)
    branch_regions = colmod.regions_for(regions, branch)
    if not branch_regions:
        raise ValueError(f"no column regions marked for branch {branch!r}")

    lines = _load_or_make_lines(raw_path, branch, log=log)

    grouped: dict[tuple, dict] = {}
    for region in branch_regions:
        records = spatial.extract_records(lines, region)
        res_np = region.get("reservoir_np") or detect_reservoir(lines, region)
        key = (res_np, region.get("reservoir_en"))
        reservoir = grouped.setdefault(key, {
            "name_np": res_np,
            "name_en": region.get("reservoir_en"),
            "zones": [],
        })
        region_zones = []
        for rec in records:
            zone = _record_to_zone(rec, region)
            if not (zone["areas_np"] or zone["dma"] or zone["time_from"]):
                continue
            region_zones.append(zone)
        if region.get("forward_fill"):
            _forward_fill(region_zones, region["forward_fill"])
        reservoir["zones"].extend(region_zones)
        if log:
            log(f"[extract]   region {region['key']}: {len(records)} records")

    reservoirs = [grouped[k] for k in grouped]

    all_areas = [a for r in reservoirs for z in r["zones"] for a in z["areas_np"]]
    area_map = translate_areas(all_areas, log=log) if all_areas else {}
    missing = sorted({a for a in all_areas if not area_map.get(a)})
    if missing and log:
        log(f"[extract]   {len(missing)} area name(s) left untranslated: "
            + ", ".join(missing[:8]) + ("…" if len(missing) > 8 else ""))
    for r in reservoirs:
        for z in r["zones"]:
            z["areas_en"] = [area_map.get(a, "") for a in z["areas_np"]]
            z["review_flags"] = validate.flag_zone(z, set(z.get("source_columns") or []) or None)

    return {
        "branch_np": branch_np,
        "branch_en": branch_en or branch,
        "month_bs": month_bs,
        "reservoirs": reservoirs,
    }


def dumps(doc: dict) -> str:
    return json.dumps(doc, ensure_ascii=False, indent=2) + "\n"
