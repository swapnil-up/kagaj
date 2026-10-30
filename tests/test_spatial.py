"""Tests for redbook page templates and schedule boundaries."""

from redbook_parser.spatial import (
    PageTemplate,
    detect_template,
    starts_annex,
    summary_table,
)


def test_mangled_toc_page_is_detected():
    text = "आर्थिक वर्ष 2082/83\nसूची - पप्र\nअनुदान संकेत\nपाना नं."
    assert detect_template(text) == PageTemplate.TOC


def test_summary_column_still_wins_over_body_text():
    text = "अनुदान संख्या\nमन्त्रालय / िनकाय\n2080/81 को यथार्थ"
    assert detect_template(text) == PageTemplate.SUMMARY


def test_annex_only_matches_page_heading():
    assert starts_annex("अनुसूचीहरू\nशीर्षक")
    assert not starts_annex("सूची - पप्र\nअनुसूची १ ...")


def test_summary_table_classification():
    assert summary_table("संघीय सञ्चित कोषबाट विनियोजन हुने") == "allocation"
    assert summary_table("संघीय सञ्चित कोषमाथि व्ययभार हुने") == "expenditure"
