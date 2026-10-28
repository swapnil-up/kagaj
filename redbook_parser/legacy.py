"""Legacy text-repair layer (behaviour-preserving port of v3).

THIS MODULE IS THE BASELINE THAT STEP 2 REPLACES.

- `CID_CHAR_MAP`: supplemental CID -> Devanagari for CIDs missing from a
  page's ToUnicode CMap. Keyed only by integer CID — NOT by font subset, which
  is the root flaw that `redbook_parser/fonts.py` fixes.
- `EXACT_FIXES`: global garbled-string -> clean-string replacements. Applied
  both pre- and post-CID mapping because some patterns match only one form.
- `fix_text`: the current order is EXACT_FIXES -> CID_CHAR_MAP -> EXACT_FIXES
  -> strip leftover `[N]` placeholders (silent glyph loss — also a Step-2 fix).

Keep this module behaviour-identical to v3 until the spatial/glyph layer lands;
do not add new fixes here.
"""

import re

DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]")

# Single-character substitutions (CID -> Devanagari).
CID_CHAR_MAP = {
    # Page 17+ (detail pages) mappings:
    4: "\u0930\u094D",    # र्
    9: "\u093F",          # ि
    14: "\u0935\u093F",   # वि
    31: "\u092A\u094D\u0930",  # प्र
    33: "\u0926\u093F",   # दि
    39: "\u092E\u094D\u092E",  # म्म
    58: "\u093F",         # ि (visual order)
    59: "\u0935\u093E",   # वा
    60: "\u0940",         # ी
    61: "\u0928\u094D",   # न्
    62: "\u0924\u094D\u0924",  # त्त
    6: "\u0938\u094D\u0930",   # स्र
    66: "\u0917\u094D\u0930\u0940",  # ग्री
    68: "\u0943",         # ृ
    69: "\u094D\u092F",   # ्‍य / व्य
    70: "\u0923\u094D\u0921",  # ण्ड
    72: "\u092D\u094D\u0930",  # भ्र
    75: "\u0942",         # ू
    77: "\u0941\u0939\u0941\u0930\u0941",  # हरू
    79: "\u0940\u0915\u0943\u0924",  # ीकृत or similar
    80: "\u093F",         # ि (P1 patterns)
    # Page 35+ (summary pages) mappings:
    12: "\u0928\u094D\u0924",  # न्त
    13: "\u094D\u0924",   # ्त
    16: "\u093F",         # ि
    18: "\u094D\u0930",   # ्र
    24: "\u094D\u0930",   # ्र (same as 18 on page 35)
    34: "\u0938\u094D\u0930",  # स्र
    35: "\u092E\u094D\u092E",  # म्म
    40: "\u0924\u094D\u0924\u093F",  # त्ति
    41: "\u092F\u094D\u092F",  # व्य
    42: "\u0938\u094D\u0925",  # स्थ
}

# Multi-character sequences needing word-level replacement (spanning CIDs).
WORD_FIXES = {
    "\x1f\x09\x24\x09\x6e\x09\xe7": "प्रतिनिधि",
    "म\x0c\rालय": "मन्त्रालय",
    "\x10नवा\x18चन": "निर्वाचन",
    "\x10नकाय": "निकाय",
    "अि\tतयार": "अनुसन्धान",
    "अनुस\x0cधान": "अनुसन्धान",
}

# Pre-compose known garbled words (exact replacements). Grows per page range —
# the step-2 font-scoped maps exist to make this table obsolete.
EXACT_FIXES = {
    "शीष\x04क": "शीर्षक",
    "\x06ोत": "स्रोत",
    "यथाथ\x04": "यथार्थ",
    "खच\x04": "खर्च",
    "संशो\tधत": "संशोधित",
    "\x1fाथ\tमकता": "प्राथमिकता",
    "!दगो": "दिगो",
    "\x0eवकास": "विकास",
    "लै\tगंक": "लैङ्गिक",
    "ज'मा": "जम्मा",
    "रा9प\tत": "राष्ट्रपति",
    "पा:र;\tमक": "पारिश्रमिक",
    "पदा\tधकार<": "पदाधिकारी",
    "अ=य": "अन्य",
    "सु\tबधा": "सुबिधा",
    "भ>ा": "भत्ता",
    "इ=धन": "इन्धन",
    "काया\x04लय": "कार्यालय",
    "सामाBी": "सामाग्री",
    "\x1fयोजन": "प्रयोजन",
    "\x0eविशD": "विशिष्ट",
    "1यिE": "व्यक्ति",
    "\x1f\tत\tन\tध": "प्रतिनिधि",
    "मFडल": "मण्डल",
    "Hमण": "भ्रमण",
    "\x0eव\x0eवध": "विविध",
    "उपरा9प\tत": "उपराष्ट्रपति",
    "सवार<": "सवारी",
    "मम\x04त": "मर्मत",
    "मूKयांकन": "मूल्यांकन",
    "\x1fदेश": "प्रदेश",
    "\x1fमुखहM": "प्रमुखहरू",
    "एकOकृत": "एकीकृत",
    "\x0eव>ीय": "वित्तीय",
    "मा\tथ": "माथि",
    "1ययभार": "व्ययभार",
    "1याज": "व्याज",
    "रा\x0e9य": "राष्ट्रिय",
    "क\tमशन": "कमिशन",
    "अथ\x04": "अर्थ",
    "म=[ालय": "मन्त्रालय",
    "भुEानी": "भुक्तानी",
    "बहुपZीय": "बहुपक्षीय",
    "`याज": "व्याज",
    "एिशयाल<": "एशियाली",
    "\x0e9य": "ाष्ट्रिय",
    "अ=तरा\x04\x0e9य": "अन्तर्राष्ट्रिय",
    "कृ\x0eष": "कृषि",
    "न\tड\x04क": "निडिक",
    "बbक": "बैंक",
    "इ=भेDमेFट": "इन्भेस्टमेण्ट",
    "युरो\x0eपयन": "युरोपियन",
    "ए.आइ.आइ.\x0eव.": "ए.आइ.आइ.वि.",
    "मुdा": "मुद्रा",
    "!eपZीय": "द्विपक्षीय",
    "\x10धकार": "अधिकार",
    "अनुस\x0cधान": "अनुसन्धान",
    "\x0cयाय": "न्याय",
    "प@रषB": "परिषद",
    "8ाकृ\x10तक": "प्राकृतिक",
    "8देश": "प्रदेश",
    "8मुखह:": "प्रमुखहरू",
    "रा\x1f1य": "राष्ट्रिय",
    "अ\x10धकार": "अधिकार",
    "सिDत": "सञ्चित",
    ")यय": "व्यय",
    "िनकासा": "विवरण",
    "मसल=द": "मसलन्द",
    "सवार<": "सवारी",
    "मेिशनर<": "मेसिनरी",
    "स'पि>": "सम्पत्तिको",
    "स0ालन": "सञ्चालन",
    "गFडकO": "गण्डकी",
    "िFडकल": "गण्डकी",
    "ि0त": "ञ्चित",
    "स0चार": "सञ्चार",
    "0योजना": "वियोजना",
    "ि0योजना": "विनियोजना",
    "ि0मय": "निर्मय",
    "वैदेिशक": "वैदेशिक",
    "ि0चार": "सञ्चार",
    "िकया": "किया",
    "भएगएको": "भए गएको",
    "रपोट": "रिपोर्ट",
    "पर=>कको": "परीक्षकको",
    "वविकास": "विविध",
    "िFडकल": "गण्डकी",
    "िस'चार": "सञ्चार",
    "स'चार": "सञ्चार",
    "वैदेिशक": "वैदेशिक",
    "भ@ा": "भत्ता",
    "कमर्चार>": "कर्मचारी",
    "बैठक भ@ा": "बैठक भत्ता",
    "प्रो^साहन": "प्रोत्साहन",
    "पुर3कार": "पुरस्कार",
    "अBय": "अन्य",
    "सवार>": "सवारी",
    "मेिशनर>": "मेसिनरी",
    "धा<रत": "धारित",
    "सुर_ा": "सुरक्षा",
    "सामाIी": "सामाग्री",
    "पु3तक": "पुस्तक",
    "शुOक": "शुल्क",
    "स'पि@": "सम्पत्ति",
    "स'भार": "सम्भार",
    "स'चालन": "सञ्चालन",
    "िFडकल": "गण्डकी",
    "पKपिKका": "पत्रपत्रिका",
    "विफXचसर्": "विफर्निचर",
    "क'`युटर": "कम्प्युटर",
    "सZटवेयर": "सफ्टवेयर",
    "खर>द": "खरीद",
    "सामाIी": "सामाग्री",
    "ि@को": "त्तिको",
    "@को": "त्तिको",
    "इBधन": "इन्धन",
    "सामािजक": "सामाजिक",
    "िनवृ@": "निवृत्त",
    "नवीकरण": "नवीकरण",
    "कमर्चार>को": "कर्मचारीको",
    "कमर्चार>": "कर्मचारी",
    "प्रो^साहन": "प्रोत्साहन",
    "िबजुल>": "बिजुली",
    "सवार>": "सवारी",
    "मसलBद": "मसलन्द",
    "सम्पत्तिहH": "सम्पत्तिहरू",
    "िवभागहH": "विभागहरू",
    "प्रणाल>": "प्रणाली",
    "सामIी": "सामाग्री",
    "परामशर्": "परामर्श",
    "िकया": "किया",
    "रपोट": "रिपोर्ट",
    "अBय": "अन्य",
    "इBधन": "इन्धन",
    "खर>द": "खरीद",
    "पु3तक": "पुस्तक",
    "शुOक": "शुल्क",
    "स'पi@": "सम्पत्ति",
    "स'पि>को": "सम्पत्तिको",
    "M.लाखमा": "रु. लाखमा",
    # Summary pages (35+) word fixes (human-corrected in page-36 gold):
    "मप्रहला": "महिला",
    "आJदवासी": "आदिवासी",
    "जनजाित": "जनजाति",
    "थाK": "थारू",
    "मुि*लम": "मुस्लिम",
    "8धानमन्त्ती": "प्रधानमन्त्रि",
    "मिन्त्तप@रषLको": "मिन्त्रिपरिशद्को",
    "काया्रलय": "कार्यालय",
    "अथ्र": "अर्थ",
    "मन्त्तालय": "मन्त्रालय",
    "उMोग": "उध्योग",
    "वािणNय": "वाणिज्य",
    "आपूित्र": "आपूर्ति",
    "उजा्र": "उर्जा",
    "जल\"ोत": "जलस्रोत",
    "िसंचाई": "सिंचाई",
    "संसद>य": "संसदीय",
    "मािमला": "मामिला",
}


def _sorted_fixes():
    return sorted(EXACT_FIXES.items(), key=lambda x: -len(x[0]))


def fix_text(text: str) -> str:
    """Apply CID->Unicode mapping and word-level fixes (current v3 behaviour)."""
    # 1. Exact word fixes first (longest match wins).
    for broken, correct in _sorted_fixes():
        text = text.replace(broken, correct)

    # 2. For remaining control chars, apply CID mapping.
    chars = []
    for c in text:
        if ord(c) < 32 and ord(c) != 10:  # control char (not newline)
            cid = ord(c)
            if cid in CID_CHAR_MAP:
                chars.append(CID_CHAR_MAP[cid])
            else:
                chars.append(f"[{cid}]")
        else:
            chars.append(c)
    result = "".join(chars)

    # 3. EXACT_FIXES again (post-CID).
    for old, new in _sorted_fixes():
        result = result.replace(old, new)

    # 4. Make unresolved CIDs visible instead of deleting them.
    result = re.sub(r"\[(\d+)\]", r"⟦cid:\1⟧", result)

    return result


def sanitize_devanagari(text: str) -> str:
    """Clean basic extraction artifacts. Preserves newlines."""
    text = text.replace("\ufffd", "⟦?⟧")
    lines = []
    for line in text.split("\n"):
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            lines.append(line)
    return "\n".join(lines)
