"""Tests for the paragraph-aware chunker (pure)."""

from vectordb.chunker import chunk_text, clean


def test_empty_returns_empty():
    assert chunk_text("") == []
    assert chunk_text("   \n\n  ") == []


def test_small_text_single_chunk():
    chunks = chunk_text("one\n\ntwo", size=2400, overlap=240)
    assert chunks == ["one\n\ntwo"]


def test_clean_strips_nul_and_control_chars():
    dirty = "a\x00b\x07c\x1fd"
    assert "\x00" not in clean(dirty)
    assert clean(dirty) == "abcd"


def test_clean_collapses_whitespace_and_blank_lines():
    assert clean("a    b") == "a b"
    assert clean("x\n\n\n\n\ny") == "x\n\ny"


def test_oversized_paragraph_sliding_window():
    # One paragraph longer than `size` must be split into multiple chunks.
    para = "x" * 1000
    chunks = chunk_text(para, size=300, overlap=0)
    assert len(chunks) > 1
    assert all(len(c) <= 300 for c in chunks)


def test_overlap_prepends_previous_tail():
    # Two paragraphs that won't fit together -> two base chunks; the 2nd carries
    # an overlap tail of the 1st.
    a = "A" * 200
    b = "B" * 200
    chunks = chunk_text(f"{a}\n\n{b}", size=250, overlap=20)
    assert len(chunks) == 2
    assert chunks[1].startswith("A" * 20)  # tail of chunk 0 prepended
    assert "B" * 200 in chunks[1]


def test_no_overlap_when_disabled():
    a = "A" * 200
    b = "B" * 200
    chunks = chunk_text(f"{a}\n\n{b}", size=250, overlap=0)
    assert chunks == [a, b]
