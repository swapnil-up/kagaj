"""Structured JSON schema and prompts for Gemini translation.

Single source of truth for the JSON schema description and prompt templates
used by process_notice.py, process_verbatim.py, and test_structured_prompt.py.

The schema is parameterized by body name (House of Representatives / National
Assembly) and context (full document vs segment). Callers use:

    schema = build_schema("House of Representatives")
    prompt = NOTICE_PROMPT.format(schema=schema, ocr_text=text)
"""

# Shared field descriptions — the schema body is identical across bodies;
# only the body name and a few examples differ.
_FIELDS = """\
- full_translation_en: The complete English translation of {context}. Preserve all names, dates, numbers, and bill references exactly.
- session.date_bs: Nepali date (e.g. 2081-04-12){date_suffix}
- session.date_ad: Approximate AD date if inferrable, else null
- session.meeting_type: Type of session (e.g. {body}, Zero Hour, Special Time)
- session.meeting_number: Meeting/sitting number if mentioned
- session.chairperson: Name of presiding officer
- sections[].name: Section name (e.g. {section_examples})
- sections[].summary_en: 1-3 sentence summary of what happened in this section
- sections[].speakers[].name: Full name of the {speaker_label}
- sections[].speakers[].party: Party abbreviation if mentioned, else null
- sections[].speakers[].topic: What they spoke about in 5-10 words
- sections[].bills_discussed[].name: Full bill name
- sections[].bills_discussed[].status: introduced | discussed | passed | ratified | sent_to_committee
- sections[].reports_presented[]: Report names if any
- sections[].key_issues[]: Key issues/topics raised in this section
- agenda_tags[]: 5-15 freeform topical keywords for searching across {search_label}
- ministries_mentioned[]: Ministry names referenced
- all_speakers_mentioned[].name: Speaker name
- all_speakers_mentioned[].party: Party if mentioned
- all_speakers_mentioned[].section: Which section they appeared in
- adjournment_time: Time of adjournment if mentioned
- next_meeting_date: Next meeting date if announced"""


def build_schema(
    body: str = "House of Representatives",
    context: str = "the entire document as a single narrative string",
    *,
    date_suffix: str = "",
    section_examples: str = "Opening, Impromptu Session, Zero Hour, Main Business, Adjournment",
    speaker_label: str = "MP or minister",
    search_label: str = "notices",
) -> str:
    """Build the schema description string for a given parliamentary body.

    Args:
        body: The parliamentary body name (e.g. "House of Representatives").
        context: What is being translated (e.g. "the entire document" or
                 "this segment as a single narrative string").
        date_suffix: Extra qualifier for date_bs (e.g. " if mentioned").
        section_examples: Example section names for this body.
        speaker_label: Label for speakers (e.g. "MP or minister" or "speaker").
        search_label: What the agenda_tags help search across.
    """
    return _FIELDS.format(
        body=body,
        context=context,
        date_suffix=date_suffix,
        section_examples=section_examples,
        speaker_label=speaker_label,
        search_label=search_label,
    )


# --- Prompt templates ---

NOTICE_PROMPT = """\
You are an expert translator of Nepali parliamentary documents.

Translate the following Nepali Devanagari OCR text from a House of Representatives meeting notice into English.

Return a JSON object with exactly this structure — no markdown, no code fences, pure JSON:{schema}
Rules:
- full_translation_en must be the COMPLETE translation. Do not summarize or truncate it.
- All names, dates, amounts, and bill references must be preserved exactly.
- speakers lists per section: include every named MP or minister who spoke.
- If a party is not explicitly stated in text, set to null.
- agenda_tags: extract 5-15 topical keywords that would help someone search for this notice later.
- If a field has no data, use null or empty array — never omit the field.
- Output valid JSON only.

--- BEGIN OCR TEXT ---
{ocr_text}
--- END OCR TEXT ---"""


VERBATIM_PROMPT = """\
You are an expert translator of Nepali parliamentary documents.

A National Assembly meeting verbatim has been split into {total} segments.
This is segment {idx} of {total}. Translate the Devanagari text below into English.

Return a JSON object with exactly this structure — no markdown, no code fences, pure JSON:{schema}
Rules:
- full_translation_en must be the COMPLETE translation of this segment. Do not summarize or truncate it.
- Only fill session/meeting fields if they are mentioned in THIS segment; otherwise null.
- All names, dates, amounts, and bill references must be preserved exactly.
- speakers lists per section: include every named speaker in this segment.
- If a party is not explicitly stated in text, set to null.
- agenda_tags: extract topical keywords from this segment that would help someone search later.
- If a field has no data, use null or empty array — never omit the field.
- Output valid JSON only.

--- BEGIN SEGMENT TEXT ---
{segment_text}
--- END SEGMENT TEXT ---"""
