"""Compare HTML parser speed and a few HTML5 tree-building behaviors.

Run from the repository root:
    ./venv/bin/python py4web/benchmarks/html_parsers.py
"""

import argparse
import importlib
import json
import statistics
from collections.abc import Callable
from time import perf_counter

from bs4 import BeautifulSoup, Tag

PARSERS = ("html5_parser", "html5lib", "html.parser", "lxml", "soup5ever", "soup5ever-experimental")


def make_page(blocks: int) -> str:
    """Generate a deterministic, mostly valid HTML document."""
    articles = (
        f'<article data-id="{i}"><h2>Product {i}</h2>'
        "<p>Beschrijving met <strong>opmaak</strong> en &amp; tekens.</p>"
        f'<edwh-editable id="section-{i}"><p>Inhoud {i}</p></edwh-editable>'
        f"<table><tr><th>Vak</th><td>Waarde {i}</td></tr></table></article>"
        for i in range(blocks)
    )
    return (
        "<!doctype html><html><head><title>Benchmark</title></head><body><main>"
        + "".join(articles)
        + "</main></body></html>"
    )


def foster_parenting(doc: BeautifulSoup) -> bool:
    """Check that text misplaced inside a table moves before the table."""
    host = doc.find(id="host")
    if not isinstance(host, Tag):
        return False
    table = host.find("table")
    return bool(isinstance(table, Tag) and host.contents and str(host.contents[0]) == "outside" and table.find("td"))


def implied_tbody(doc: BeautifulSoup) -> bool:
    """Check that a row in a table gets an implicit tbody parent."""
    table = doc.find("table")
    tbody = table.find("tbody") if isinstance(table, Tag) else None
    row = tbody.find("tr") if isinstance(tbody, Tag) else None
    return bool(isinstance(tbody, Tag) and isinstance(row, Tag) and tbody.parent is table and row.parent is tbody)


def paragraph_closing(doc: BeautifulSoup) -> bool:
    """Check that a new paragraph closes the previous paragraph."""
    first, second = doc.find(id="first"), doc.find(id="second")
    return bool(
        isinstance(first, Tag)
        and isinstance(second, Tag)
        and first.name == second.name == "p"
        and first.parent is second.parent
        and first.get_text() == "one"
        and second.get_text() == "two"
    )


def formatting_reconstruction(doc: BeautifulSoup) -> bool:
    """Check reconstruction of misnested italic formatting."""
    paragraph = doc.find("p")
    if not isinstance(paragraph, Tag):
        return False
    bold = paragraph.find("b")
    italics = paragraph.find_all("i", recursive=False)
    return bool(
        isinstance(bold, Tag) and bold.get_text() == "onetwo" and len(italics) == 1 and italics[0].get_text() == "three"
    )


def option_closing(doc: BeautifulSoup) -> bool:
    """Check that a new option closes the previous option."""
    select = doc.find("select")
    if not isinstance(select, Tag):
        return False
    options = select.find_all("option", recursive=False)
    return len(options) == 2 and [option.get_text() for option in options] == ["one", "two"]


CASES = (
    ("foster parenting", '<div id="host"><table>outside<tr><td>inside</td></tr></table></div>', foster_parenting),
    ("implied tbody", "<table><tr><td>cell</td></tr></table>", implied_tbody),
    ("paragraph closing", '<p id="first">one<p id="second">two', paragraph_closing),
    ("formatting reconstruction", "<p><b>one<i>two</b>three</i></p>", formatting_reconstruction),
    ("option closing", "<select><option>one<option>two</select>", option_closing),
)


def parser_for(name: str) -> Callable[[str], BeautifulSoup]:
    """Return a parser producing a Beautiful Soup tree."""
    if name == "html5_parser":
        module = importlib.import_module("html5_parser")
        return lambda html: module.parse(html, treebuilder="soup")
    elif name.startswith("soup5ever"):
        importlib.import_module("soup5ever")

    return lambda html: BeautifulSoup(html, name)


def main() -> None:
    """Run the benchmark and emit one JSON result for the host CLI."""
    arguments = argparse.ArgumentParser(description=__doc__)
    arguments.add_argument("--blocks", type=int, default=1000, help="Article blocks, default 1000")
    arguments.add_argument("--repeat", type=int, default=3, help="Timed runs per parser, default 3")
    args = arguments.parse_args()
    if not 1 <= args.blocks <= 3000 or not 1 <= args.repeat <= 10:
        arguments.error("--blocks must be 1..3000 and --repeat must be 1..10")

    html = make_page(args.blocks)
    results = []
    for name in PARSERS:
        result = {"parser": name, "median_ms": None, "checks": [], "error": None}
        results.append(result)
        try:
            parse = parser_for(name)
            parse("<p>warmup</p>")
            times = []
            for _ in range(args.repeat):
                start = perf_counter()
                parse(html)
                times.append((perf_counter() - start) * 1000)
            result["median_ms"] = statistics.median(times)
            result["checks"] = [{"name": label, "passed": check(parse(sample))} for label, sample, check in CASES]
        except Exception as error:
            result["error"] = f"{type(error).__name__}: {error}"
    print(
        json.dumps(
            {"blocks": args.blocks, "html_bytes": len(html.encode("utf-8")), "repeat": args.repeat, "results": results}
        )
    )


if __name__ == "__main__":
    main()
