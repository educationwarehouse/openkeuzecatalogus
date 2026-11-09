"""The page round trip in `ContentEditableV2` must keep the page a browser would build."""

import bs4
from common.fixtures.content_editable import ContentEditableV2


def test_parse_document_carries_open_formatting_into_the_next_block() -> None:
    """An unclosed `<strong>` stays open in the next list item, as it does in a browser.

    lxml drops it there, so the second item would lose its bold after the fixture
    serializes the page back.
    """
    page = "<!DOCTYPE html><html><body><ul><li><strong>Let op</li><li>blijft vet</li></ul></body></html>"

    # parse the serialized output as the browser would, which html5lib stands in for
    output = bs4.BeautifulSoup(str(ContentEditableV2.parse_document(page)), "html5lib")

    strong = output.select_one("li:nth-of-type(2) strong")
    assert strong is not None
    assert strong.get_text() == "blijft vet"
