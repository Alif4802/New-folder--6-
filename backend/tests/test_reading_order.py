import pytest
from app.services.pdf.reading_order import WordBox, cluster_words_into_lines, group_lines_into_blocks


def test_reading_order_sorts_lines_and_words():
    # Intentionally scrambled word order input
    words = [
        WordBox(text="Today", x0=100.0, y0=20.0, x1=140.0, y1=32.0),
        WordBox(text="English", x0=20.0, y0=20.0, x1=60.0, y1=32.0),
        WordBox(text="for", x0=65.0, y0=20.0, x1=90.0, y1=32.0),
        WordBox(text="1", x0=60.0, y0=50.0, x1=70.0, y1=62.0),
        WordBox(text="Unit", x0=20.0, y0=50.0, x1=50.0, y1=62.0),
    ]

    lines = cluster_words_into_lines(words)
    assert len(lines) == 2
    assert lines[0].text == "English for Today"
    assert lines[1].text == "Unit 1"

    blocks = group_lines_into_blocks(lines, page_number=1)
    assert len(blocks) >= 1
