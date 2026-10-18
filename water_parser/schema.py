"""Gemini structured-extraction prompt for KUKL water schedules.

One prompt handles both source flavours (flat spreadsheet dump and noisy OCR)
because they share the same semantic target: a set of *reservoirs* (tanks /
pumping systems / sheets), each holding *zones* (a DMA, a "पालो" rotation, or an
area group) with delivery days, a time window, served areas, and contacts.

The prompt is deliberately strict about not inventing data and about normalising
Devanagari digits, since downstream search and date math depend on ASCII.
"""

from __future__ import annotations

PROMPT = """\
You are extracting a water-distribution schedule published by KUKL (Kathmandu Upatyaka Khanepani Limited) from ONE branch-office source file.

The source may be either (a) a flattened spreadsheet dump, where each `### sheet: NAME` block is one reservoir/pumping group and rows are `cell | cell | cell`, or (b) OCR text of a scanned/legacy-font PDF, where `### page: N` marks pages and reading order is partly scrambled. In both cases reconstruct the logical schedule.

Meaning of the columns you will encounter (Nepali → English):
- DMA / डीएमए: a zone code like 8.1, 3.2, 4.1.2
- पालो / सि.नं / S.N. / बार: rotation number, serial number, or weekday
- स्थान / पानी बितरण हुने स्थान / क्षेत्र / एरिया: served locality or street names
- गते / असोज(गते) / Date / दिन: day-of-month numbers when water is delivered
- समय / Time / देखि / From / सम्म / To: the delivery time window
- बिहान=morning, दिउसो/दिउंसो=afternoon, बेलुका/साँझ=evening, राति=night
- चाबी चालकको नाम / सम्पर्क / Contact: staff name(s) and phone number(s)
- कैफियत / Remarks / नोट / Note: free-text remarks (e.g. alternate-day rotation)

Return ONE JSON object with exactly this structure — no markdown, no code fences, pure JSON:
{
  "branch_np": "<branch office in Nepali, e.g. बानेश्वर शाखा कार्यालय>",
  "branch_en": "<branch in English/Roman, e.g. Baneshwor>",
  "month_bs": "<Nepali month + year as printed, e.g. २०८३ असोज>",
  "reservoirs": [
    {
      "name_np": "<tank/pokhari/system/sheet name in Nepali, or null>",
      "name_en": "<English/Roman name, or null>",
      "zones": [
        {
          "dma": "<ASCII digits e.g. 8.1, or null if the source has no DMA column>",
          "label": "<rotation/area/serial label in Nepali if present, else null>",
          "days": [<integers 1-32, ascending, de-duplicated>],
          "time_from": "<24h HH:MM or null>",
          "time_to": "<24h HH:MM or null>",
          "areas_np": ["<Nepali locality / street / landmark>", ...],
          "areas_en": ["<English/Roman transliteration of each areas_np entry, same order>"],
          "contacts": ["<name and phone as written>", ...],
          "notes": "<short English note, or null>"
        }
      ]
    }
  ]
}

Rules:
- Convert ALL Devanagari digits to ASCII digits in dma, days, and times.
- days: integers 1-32, ascending, de-duplicated. Split/repair obvious OCR or wrap issues (e.g. "१०१४" -> 10, 14).
- times: 24-hour "HH:MM". Abbreviated hours mean the obvious slot (e.g. "12" in an afternoon column -> 12:00; "1:00" following "दिउसो" -> 13:00; "५:००" in बेलुका -> 17:00). If the window crosses midnight (e.g. बेलुका to भोलिपल्ट बिहान), keep true clock times and add a note.
- areas_np: real Nepali locality/street/landmark names only — never time words, DMA codes, phone numbers, or column headers. Split a long run into one element per place. It is fine to include the same place in several zones if the source repeats it.
- areas_en must have exactly the same length and order as areas_np.
- Split reservations by reservoir where the source distinguishes them (sheets, tank names, "टंकीबाट", "पोखरीबाट"); if the source is a single undifferentiated table, use one reservoir with name_np = null.
- If a row has no DMA, set dma to null and use `label` for its पालो / serial / area heading; never fabricate a DMA.
- Do NOT invent zones, areas, days, contacts, or times that are not in the text. Omit rather than guess.
- Use [] for empty lists and null for missing scalars.

SOURCE TEXT for this branch file:
---
{source_text}
---
"""


def build_prompt(source_text: str) -> str:
    """Render the prompt for one source doc.

    Uses ``str.replace`` rather than ``str.format`` because the prompt embeds a
    literal JSON example full of braces.
    """
    return PROMPT.replace("{source_text}", source_text)


AREAS_PROMPT = """\
You transliterate Nepali place names from a KUKL water-distribution schedule \
into Roman/English. Input is a JSON array of Nepali locality/street/landmark \
names (already extracted; do not add or drop entries). Output ONE JSON object \
with a single key "map" whose value maps every input string to its Romanisation:

{"map": {"<nepali>": "<roman>", ...}}

Rules:
- Include EVERY input string as a key, including ones that are only partly legible.
- Transliterate names phonetically (e.g. "बानेश्वर" -> "Baneshwor"); do not translate meaning.
- Preserve well-known English spellings where standard (Kathmandu, Lalitpur, Thimi).
- Do not invent, merge, split, or reorder entries; keys must match the input exactly.
- Pure JSON only, no markdown.

INPUT:
{areas_json}
"""


def build_areas_prompt(areas: list[str]) -> str:
    import json

    return AREAS_PROMPT.replace("{areas_json}", json.dumps(areas, ensure_ascii=False))

