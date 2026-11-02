"""Canonical vocabulary for the Nepal Police bulletin crime charts."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

DEVANAGARI_DIGITS = {chr(0x0966 + i): str(i) for i in range(10)}

PROVINCES = [
    "kathmandu_valley",
    "koshi",
    "madhesh",
    "bagmati",
    "gandaki",
    "lumbini",
    "karnali",
    "sudurpashchim",
]

PROVINCE_LABELS = {
    "kathmandu_valley": "Kathmandu Valley",
    "koshi": "Koshi",
    "madhesh": "Madhesh",
    "bagmati": "Bagmati",
    "gandaki": "Gandaki",
    "lumbini": "Lumbini",
    "karnali": "Karnali",
    "sudurpashchim": "Sudurpashchim",
}

MONTHS = {
    "बैशाख": 1,
    "वैशाख": 1,
    "जेठ": 2,
    "असार": 3,
    "असाढ": 3,
    "साउन": 4,
    "साउि": 4,
    "साउन्": 4,
    "श्रावण": 4,
    "भदौ": 5,
    "भाद्र": 5,
    "भद्र": 5,
    "असोज": 6,
    "कात्तिक": 7,
    "कार्तिक": 7,
    "मंसिर": 8,
    "मङ्सिर": 8,
    "मंसीर": 8,
    "पुस": 9,
    "पौष": 9,
    "माघ": 10,
    "फागुन": 11,
    "फाल्गुन": 11,
    "चैत": 12,
    "चैत्र": 12,
}

MONTH_NAMES = {
    1: "Baishakh",
    2: "Jestha",
    3: "Ashad",
    4: "Shrawan",
    5: "Bhadra",
    6: "Ashoj",
    7: "Kartik",
    8: "Mangsir",
    9: "Poush",
    10: "Magh",
    11: "Falgun",
    12: "Chaitra",
}

# canonical -> (english, nepali, kind)
OFFENSES = {
    "murder": ("Murder", "कर्तव्य ज्यान", "heinous"),
    "trafficking": ("Human trafficking", "मा.बे.बि. तथा ओसारपसार", "heinous"),
    "rape": ("Rape", "जबरजस्ती करणी", "heinous"),
    "kidnapping": ("Kidnapping / bodily restraint", "अपहरण वा शरीर बन्दी", "heinous"),
    "attempted_murder": ("Attempted murder", "ज्यान मार्ने उद्योग", "serious"),
    "suicide_abetment": ("Abetment of suicide", "आत्महत्या दुरुत्साहन", "serious"),
    "abortion": ("Abortion-related offence", "गर्भ संरक्षण विरुद्धको कसूर", "serious"),
    "dacoity": ("Dacoity", "डाँका चोरी", "serious"),
    "burglary": ("Burglary", "नकबजनी चोरी", "serious"),
    "assault": ("Assault / grievous hurt", "कुटपिट वा अंगभंग", "serious"),
}

# Order matters: the first matching alias wins. Attempted murder before murder,
# since both labels contain "ज्यान".
PROVINCE_ALIASES = [
    ("kathmandu_valley", ("काठमाड", "काठिाड", "काठिाा", "काठमाण्", "काठिाण्", "काठमार्", "उपत्यका", "उपत्र्का")),
    ("koshi", ("कोशी", "कोिी", "कोश", "१ नं", "१ िं", "१ निं")),
    ("madhesh", ("मधेश", "मिेश", "िधेि", "मधेि", "मधेष", "िधेश", "ििेश", "ििेि", "२ नं", "२ िं")),
    ("bagmati", ("बागमती", "बाग्ििी", "बागििी", "बाग्मती", "३ नं", "३ िं")),
    ("gandaki", ("गण्डकी", "गण्ाकी", "गण्र्की", "गण्डकि", "४ नं", "४ िं")),
    ("lumbini", ("लुम्बिनी", "लुमम्बनी", "लुफम्बनी", "लुनबोबिी", "लुनम्बिी", "लुम्बनी", "लुनबोबी", "५ नं", "५ िं")),
    ("karnali", ("कर्णाली", "कणााली", "कणायली", "कणार्ली", "कर्णालि", "६ नं", "६ िं")),
    ("sudurpashchim", ("सुदूर", "सुदुर", "सुदुप", "सुदुरप", "७ नं", "७ िं")),
]

_ALIASES = [
    ("attempted_murder", ("उद्योग", "द्योग", "मार्ने", "मािे", "माने", "िाने", "मार्िे")),
    ("murder", ("कर्तव्य", "कताव्य", "कतायकर्", "किाव्र्", "कतयव्र्", "कियव्र्",
                "किाव्य", "िाव्य", "ज्र्ान", "ज्र्ाि", "ज्यान", "ज्याि", "ज्यनर", "ज्यन")),
    ("suicide_abetment", ("आत्महत", "आत्महत्र", "दुरुत्साहन", "दुरुत्साहि", "दुरुत्साह")),
    ("assault", ("कुटपिट", "कुिनपि", "कुटनपट", "कुटफपट", "अंगभंग", "अिंगभिंग", "अांगभांग")),
    ("abortion", ("गर्भ", "गभा")),
    ("trafficking", ("मा.बे", "मा.बे.", "िा.बे", "िन.बे", "बे.मब", "बे.नब", "बे.फब",
                     "ओसारपसार", "ओसनरपसनर", "ओसार", "ओसन", "बेचबिखन")),
    ("rape", ("जबरजस्ती", "जवरजस्ती", "जिरजस्िी", "जबरजस्िी", "जवरजस्िी",
              "जिरजस्ती", "िरिस्िी", "िवरिस्िी", "जस्िी", "जस्र्", "जस्", "जस्त",
              "करर्", "करण")),
    ("kidnapping", ("अपहरण",)),
    ("dacoity", ("डाँका", "र्ााँका", "डाुँका", "डाँकि")),
    ("burglary", ("नकबज", "िकबज", "नकबजि")),
]


def normalize_digits(text: str) -> str:
    out = []
    for ch in text:
        out.append(DEVANAGARI_DIGITS.get(ch, ch))
    return "".join(out)


def parse_int(text: str) -> int | None:
    text = normalize_digits(text).strip()
    text = text.replace(",", "").strip()
    if re.fullmatch(r"\d+", text):
        return int(text)
    return None


def clean_label(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = text.replace("\u200c", "").replace("\u200d", "")
    return re.sub(r"\s+", " ", text).strip()


_EXACT_OFFENSE_LABELS = {
    "कर्तव्य ज्यान": "murder",
    "कर्तब्य ज्यान": "murder",
    "ज्यान मार्ने उद्योग": "attempted_murder",
    "आत्महत्या दुरुत्साहन": "suicide_abetment",
    "आत्म हत्या गर्न दुरुत्साहन गरेको": "suicide_abetment",
    "मानव बेचबिखन तथा ओसारपसार": "trafficking",
    "मानव वेचविखन तथा ओसारपसार": "trafficking",
    "मा.बे.बि. तथा ओसारपसार": "trafficking",
    "जबरजस्ती करणी": "rape",
    "जवरजस्ती करणी": "rape",
    "अपहरण वा शरीर बन्दी": "kidnapping",
    "ब्यक्ति अपहरण": "kidnapping",
    "अपहरण": "kidnapping",
    "कुटपिट अंगभंग": "assault",
    "कुटपिट वा अंगभंग": "assault",
    "डाँका चोरी": "dacoity",
    "नकबजनी चोरी": "burglary",
    "गर्भ संरक्षण विरुद्धको कसूर": "abortion",
}


def match_offense_exact(raw: str) -> str | None:
    return _EXACT_OFFENSE_LABELS.get(clean_label(raw))


def match_offense(raw: str) -> str | None:
    label = clean_label(raw)
    if any(k in label for k in ("सवारी", "ट्राफिक", "सडक दुर्घटना")):
        return None
    for canonical, needles in _ALIASES:
        for needle in needles:
            if needle in label:
                return canonical
    return None


_OLD_NUMBERING = {
    1: "koshi",
    2: "madhesh",
    3: "bagmati",
    4: "gandaki",
    5: "lumbini",
    6: "karnali",
    7: "sudurpashchim",
}


def match_province(raw: str) -> str | None:
    label = clean_label(raw)
    for canonical, needles in PROVINCE_ALIASES:
        for needle in needles:
            if needle in label:
                return canonical
    if "प्रदेश" in label or "िं" in label or "नं" in label:
        digits = [parse_int(ch) for ch in normalize_digits(label) if ch.isdigit()]
        for number in digits:
            if number in _OLD_NUMBERING:
                return _OLD_NUMBERING[number]
    return None


def match_month(raw: str) -> int | None:
    label = clean_label(raw)
    for name, number in MONTHS.items():
        if name in label:
            return number
    return None


def parse_issue_title(title: str) -> tuple[int | None, int | None, int | None]:
    """Return (bs_year, bs_month, issue_no) from a bulletin title."""
    label = clean_label(title)
    year = None
    for token in re.findall(r"[०-९]{4}", label):
        candidate = parse_int(token)
        if candidate and 2070 <= candidate <= 2100:
            year = candidate
            break
    if year is None:
        for token in re.findall(r"\b20[0-9]{2}\b", normalize_digits(label)):
            candidate = int(token)
            if 2070 <= candidate <= 2100:
                year = candidate
                break
    month = None
    for name, number in MONTHS.items():
        if name in label:
            month = number
            break
    issue = None
    match = re.search(r"अंक[\s\-]*([०-९0-9]+)", label)
    if match:
        issue = parse_int(match.group(1))
    return year, month, issue


def fiscal_year(bs_year: int, bs_month: int) -> str:
    start = bs_year if bs_month >= 4 else bs_year - 1
    return f"{start}/{str(start + 1)[-2:]}"


def month_key(bs_year: int, bs_month: int) -> str:
    return f"{bs_year}-{bs_month:02d}"


def add_months(bs_year: int, bs_month: int, delta: int) -> tuple[int, int]:
    index = bs_year * 12 + (bs_month - 1) + delta
    return index // 12, index % 12 + 1


@dataclass(frozen=True)
class Issue:
    bs_year: int
    bs_month: int
    issue_no: int | None

    @property
    def fy(self) -> str:
        return fiscal_year(self.bs_year, self.bs_month)

    @property
    def month_key(self) -> str:
        return month_key(self.bs_year, self.bs_month)

    @property
    def month_name(self) -> str:
        return MONTH_NAMES[self.bs_month]
