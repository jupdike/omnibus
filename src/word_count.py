#!/usr/bin/env python3
"""Count the words in an EPUB (ignoring all markup), with a per-book breakdown.

Usage:
    python3 -I src/word_count.py [EPUB_OR_DIR ...] [--files]

    EPUB_OR_DIR  a .epub file or an extracted EPUB folder
                 (default: build/the-complete-sherlock-holmes.epub)
    --files      also list the word count of every spine document

Reads the spine in reading order and extracts the text of each XHTML <body>,
skipping <script>/<style> and note-reference markers (the superscript numbers
that link to endnotes). Each document is classified by the epub:type on its
<body> (Standard Ebooks marks every file frontmatter / bodymatter / backmatter),
so you get both a grand total and a "body text only" total.

For an omnibus built by build_omnibus.py, documents under epub/books/<slug>/
are grouped per source book; everything else is reported as "(omnibus)".

Word rule: a run of letters/digits, allowing internal apostrophes, hyphens,
en dashes and number punctuation ("don't", "well-known", "1,000", "10:30").
Em dashes split words, so "word—word" counts as two.
"""
import argparse
import posixpath
import re
import sys
import urllib.parse
import xml.etree.ElementTree as ET
import zipfile
from collections import OrderedDict
from pathlib import Path

NS = {
    "c": "urn:oasis:names:tc:opendocument:xmlns:container",
    "opf": "http://www.idpf.org/2007/opf",
    "x": "http://www.w3.org/1999/xhtml",
    "epub": "http://www.idpf.org/2007/ops",
}
EPUB_TYPE = "{%s}type" % NS["epub"]
XHTML_TYPES = {"application/xhtml+xml", "text/html"}
SKIP_TAGS = {"{%s}script" % NS["x"], "{%s}style" % NS["x"]}
SECTIONS = ("frontmatter", "bodymatter", "backmatter")

WORD_RE = re.compile(r"\w+(?:['’\-–.,:/]\w+)*")
BOOK_RE = re.compile(r"(?:^|/)books/([^/]+)/")

DEFAULT_EPUB = Path(__file__).resolve().parent.parent / "build" / "the-complete-sherlock-holmes.epub"


class Source:
    """Uniform read access to a zipped or extracted EPUB."""

    def __init__(self, path):
        self.path = Path(path)
        self.zip = None if self.path.is_dir() else zipfile.ZipFile(self.path)

    def read(self, name):
        if self.zip:
            return self.zip.read(name)
        return (self.path / name).read_bytes()


def iter_text(el):
    """Yield the text of el, skipping scripts, styles and noteref markers
    (but keeping the tail text that follows them)."""
    skip = el.tag in SKIP_TAGS or "noteref" in el.get(EPUB_TYPE, "").split()
    if not skip:
        if el.text:
            yield el.text
        for child in el:
            yield from iter_text(child)
    if el.tail:
        yield el.tail


def count_words(text):
    return len(WORD_RE.findall(text))


def resolve(base_dir, href):
    href = urllib.parse.unquote(href.split("#", 1)[0])
    return posixpath.normpath(posixpath.join(base_dir, href))


def book_titles(src, opf_dir, manifest):
    """Map books/<slug> -> title using the top level of the EPUB 3 nav doc."""
    titles = {}
    nav = next((it for it in manifest.values() if "nav" in it["props"]), None)
    if not nav:
        return titles
    nav_path = nav["path"]
    root = ET.fromstring(src.read(nav_path))
    for navel in root.iter("{%s}nav" % NS["x"]):
        if "toc" not in navel.get(EPUB_TYPE, "").split():
            continue

        def walk(ol):
            for li in ol.findall("x:li", NS):
                a = li.find("x:a", NS)
                if a is not None and a.get("href"):
                    m = BOOK_RE.search(resolve(posixpath.dirname(nav_path), a.get("href")))
                    if m and m.group(1) not in titles:
                        titles[m.group(1)] = " ".join("".join(a.itertext()).split())
                sub = li.find("x:ol", NS)
                if sub is not None:
                    walk(sub)

        ol = navel.find("x:ol", NS)
        if ol is not None:
            walk(ol)
    return titles


def analyze(path):
    src = Source(path)
    container = ET.fromstring(src.read("META-INF/container.xml"))
    opf_path = container.find(".//c:rootfile", NS).get("full-path")
    opf_dir = posixpath.dirname(opf_path)
    opf = ET.fromstring(src.read(opf_path))

    title_el = opf.find(".//{http://purl.org/dc/elements/1.1/}title")
    title = title_el.text.strip() if title_el is not None and title_el.text else Path(path).stem

    manifest = {}
    for it in opf.findall("opf:manifest/opf:item", NS):
        manifest[it.get("id")] = {
            "path": resolve(opf_dir, it.get("href")),
            "type": it.get("media-type"),
            "props": (it.get("properties") or "").split(),
        }
    titles = book_titles(src, opf_dir, manifest)

    docs = []
    for ref in opf.findall("opf:spine/opf:itemref", NS):
        item = manifest.get(ref.get("idref"))
        if not item or item["type"] not in XHTML_TYPES:
            continue
        root = ET.fromstring(src.read(item["path"]))
        body = root.find("x:body", NS)
        if body is None:
            continue
        types = body.get(EPUB_TYPE, "").split()
        section = next((s for s in SECTIONS if s in types), "other")
        if "nav" in item["props"]:
            section = "other"
        m = BOOK_RE.search(item["path"])
        slug = m.group(1) if m else None
        docs.append({
            "path": item["path"],
            "book": titles.get(slug, slug) if slug else "(omnibus)",
            "section": section,
            "words": count_words(" ".join(iter_text(body))),
        })
    return title, docs


def fmt(n):
    return f"{n:,}"


def report(path, show_files):
    title, docs = analyze(path)

    books = OrderedDict()
    for d in docs:
        b = books.setdefault(d["book"], {s: 0 for s in SECTIONS + ("other",)})
        b[d["section"]] += d["words"]

    name_w = max([len(b) for b in books] + [len("Total"), 30])
    cols = ("body", "front", "back", "other", "total")
    header = f"{'Book':<{name_w}}" + "".join(f"{c:>11}" for c in cols)

    print(f"{title}  ({path})\n")
    print(header)
    print("-" * len(header))
    totals = dict.fromkeys(cols, 0)
    for name, s in books.items():
        row = {
            "body": s["bodymatter"], "front": s["frontmatter"],
            "back": s["backmatter"], "other": s["other"],
        }
        row["total"] = sum(row.values())
        for c in cols:
            totals[c] += row[c]
        print(f"{name:<{name_w}}" + "".join(f"{fmt(row[c]):>11}" for c in cols))
    print("-" * len(header))
    print(f"{'Total':<{name_w}}" + "".join(f"{fmt(totals[c]):>11}" for c in cols))
    print()
    print(f"Body text (bodymatter): {fmt(totals['body'])} words")
    print(f"Everything:             {fmt(totals['total'])} words in {len(docs)} spine documents")

    if show_files:
        print()
        w = max(len(d["path"]) for d in docs)
        for d in docs:
            print(f"{d['path']:<{w}}  {d['section']:<11} {fmt(d['words']):>8}")


def main():
    ap = argparse.ArgumentParser(description="Word count for an EPUB, ignoring markup.")
    ap.add_argument("paths", nargs="*", default=[str(DEFAULT_EPUB)],
                    help="EPUB file(s) or extracted EPUB folder(s)")
    ap.add_argument("--files", action="store_true", help="list every spine document")
    args = ap.parse_args()
    for i, p in enumerate(args.paths):
        if i:
            print("\n")
        if not Path(p).exists():
            sys.exit(f"Not found: {p}")
        report(p, args.files)


if __name__ == "__main__":
    main()
