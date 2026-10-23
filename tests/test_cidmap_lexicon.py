import gzip

from cidmap.lexicon import NepaliLexicon


def test_lexicon_loads_text_and_deduplicates(tmp_path):
    path = tmp_path / "words.txt"
    path.write_text("# comment\nव्यय\nविवरण\nव्यय\nnot-devanagari\n",
                    encoding="utf-8")
    lexicon = NepaliLexicon.load(path)
    assert lexicon.words == ("व्यय", "विवरण")
    assert "व्यय" in lexicon
    assert lexicon.score("व्यय") == 1.0


def test_lexicon_loads_gzip(tmp_path):
    path = tmp_path / "words.txt.gz"
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write("व्यय\nविवरण\n")
    lexicon = NepaliLexicon.load(path)
    assert len(lexicon) == 2
    assert lexicon.score("व्यय") == 1.0
    assert lexicon.score("व्ययन") < 1.0


def test_lexicon_canonicalizes_joiners(tmp_path):
    path = tmp_path / "words.txt"
    path.write_text("व्‍यय\n", encoding="utf-8")
    lexicon = NepaliLexicon.load(path)
    assert "व्यय" in lexicon


def test_build_lexicon_writes_gzip_and_provenance(tmp_path):
    import sqlite3

    from cidmap.build_lexicon import build

    source = tmp_path / "words.sqlite3"
    with sqlite3.connect(source) as conn:
        conn.execute("create table word (id integer primary key, value text)")
        conn.executemany(
            "insert into word(value) values (?)",
            [("व्यय",), ("विवरण",), ("व्यय",), ("english",)],
        )
    output = tmp_path / "lexicon.txt.gz"
    provenance = tmp_path / "lexicon.json"
    meta = build(source, output, provenance)
    assert meta["rows"] == 2
    assert output.exists()
    assert provenance.exists()
    lexicon = NepaliLexicon.load(output)
    assert lexicon.words == ("विवरण", "व्यय")
