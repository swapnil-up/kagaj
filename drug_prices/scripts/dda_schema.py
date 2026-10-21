"""Structured JSON schema and prompts for Gemini DDA drug price extraction.

Single source of truth for the JSON schema description and prompt templates
used by process_dda.py.

Usage:
    from dda_schema import DDA_PROMPT, build_dda_prompt
    prompt = build_dda_prompt(ocr_text)
"""

DDA_SCHEMA = """\
- source.title: Document title
- source.date_bs: Nepali date (BS) if found, else null
- source.date_ad: Approximate AD date if inferrable, else null
- source.gazette_number: Gazette serial number if found, else null
- source.document_type: "gazette" | "notice" | "bulletin"
- drugs[].drug_name_en: English drug name (e.g. "Amoxycillin")
- drugs[].drug_name_np: Nepali/Devanagari name (e.g. "अमोक्सिसिलिन") if readable
- drugs[].strength: Dosage strength (e.g. "500 mg", "250 mg/5 ml")
- drugs[].dosage_form: Form (e.g. "Tablet", "Capsule", "Syrup", "Injection", "Ointment")
- drugs[].unit: Packaging unit (e.g. "per tablet", "per 10 ml bottle", "per strip")
- drugs[].mrp_npr: Maximum Retail Price in NPR as a number (e.g. 12.50)
- drugs[].category: Drug category/class if mentioned (e.g. "Antibiotic", "Analgesic")
- drugs[].manufacturer: Manufacturer name if listed
- drugs[].pack_size: Pack size if mentioned (e.g. "10 tablets", "100 ml")
- drugs[].schedule: Drug schedule/classification if mentioned (e.g. "H", "G")
- summary.total_drugs: Total number of drugs extracted
- summary.categories_found: List of unique drug categories found
- summary.price_range: {{"min": lowest MRP found, "max": highest MRP found}}
- summary.avg_price: Average MRP across all drugs"""


DDA_SYSTEM_INSTRUCTION = (
    "You are an expert at extracting structured drug price data from Nepali "
    "government Department of Drug Administration (DDA) gazettes and price "
    "notices. You understand both English pharmaceutical names and Nepali "
    "Devanagari text. Output JSON only."
)


DDA_PROMPT = """\
You are an expert at extracting structured drug price data from Nepali government gazettes.

The following text has been OCR'd from a DDA (Department of Drug Administration) document.
The text may contain some garbled Devanagari characters — use context to reconstruct them.
English drug names, strengths, and numbers should be clear.

Extract ALL drug/MRP (Maximum Retail Price) data from this text.

Return a JSON object with exactly this structure — no markdown, no code fences, pure JSON:{schema}
Rules:
- Extract EVERY drug entry in the document. Do not skip or summarize any.
- If a Nepali field is garbled or unreadable, use null — do not guess.
- Prices MUST be numbers (not strings). Use decimal notation (e.g. 12.50, not "12.50").
- If the text contains multiple tables or sections, merge all drugs into one array.
- drug_name_en should be the standard English pharmaceutical name.
- drug_name_np should be the Devanagari script name as printed in the gazette.
- If a field is genuinely absent from the text, use null.
- summary.total_drugs must match the actual count of drugs in the array.
- summary.price_range.min and .max must be actual prices found.
- Output valid JSON only.

--- BEGIN OCR TEXT ---
{ocr_text}
--- END OCR TEXT ---"""


def build_dda_prompt(ocr_text: str) -> str:
    """Build the complete Gemini prompt with the OCR text embedded."""
    return DDA_PROMPT.format(schema=DDA_SCHEMA, ocr_text=ocr_text)


def _output_token_budget(ocr_text: str) -> int:
    """Adaptive output token budget based on input size."""
    chars = len(ocr_text)
    return max(8192, min(chars // 2, 65536))
