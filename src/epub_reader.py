"""Parse an extracted EPUB 3 (with optional NCX) into a simple in-memory model.

Generic enough for any EPUB 3, tuned for Standard Ebooks output.
"""
import posixpath
import re
import urllib.parse
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

NS = {
    "c": "urn:oasis:names:tc:opendocument:xmlns:container",
    "opf": "http://www.idpf.org/2007/opf",
    "dc": "http://purl.org/dc/elements/1.1/",
    "x": "http://www.w3.org/1999/xhtml",
    "epub": "http://www.idpf.org/2007/ops",
}
EPUB_TYPE = "{%s}type" % NS["epub"]

ET.register_namespace("", NS["x"])
ET.register_namespace("epub", NS["epub"])


@dataclass
class ManifestItem:
    id: str
    href: str            # path relative to the OPF directory (decoded)
    media_type: str
    properties: list = field(default_factory=list)


@dataclass
class NavNode:
    label: str
    href: str            # path relative to the OPF directory, may contain #fragment
    children: list = field(default_factory=list)

    @property
    def file(self):
        return self.href.split("#", 1)[0]


@dataclass
class SourceBook:
    slug: str
    root: Path           # extraction folder
    opf_dir: str         # e.g. "epub"
    title: str = ""
    title_file_as: str = ""
    language: str = ""
    identifier: str = ""
    sources: list = field(default_factory=list)
    subjects: list = field(default_factory=list)
    contributors: list = field(default_factory=list)   # [(name, [roles])]
    manifest: dict = field(default_factory=dict)       # id -> ManifestItem
    spine: list = field(default_factory=list)          # [(idref, linear)]
    nav: list = field(default_factory=list)            # [NavNode]
    epub_types: dict = field(default_factory=dict)     # href -> set(words)

    @property
    def content_dir(self):
        return self.root / self.opf_dir

    def item_by_href(self, href):
        for item in self.manifest.values():
            if item.href == href:
                return item
        return None

    def files_with_type(self, word):
        return [h for h, types in self.epub_types.items() if word in types]


def safe_extract(epub_path, dest):
    """Extract a zip, refusing absolute paths and parent-directory escapes."""
    dest = Path(dest).resolve()
    with zipfile.ZipFile(epub_path) as z:
        for info in z.infolist():
            name = info.filename
            target = (dest / name).resolve()
            inside = target == dest or str(target).startswith(str(dest) + "/")
            if name.startswith("/") or not inside:
                raise RuntimeError(f"unsafe path in {epub_path}: {name}")
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(z.read(info))


def resolve(base_dir, href):
    """Resolve an href relative to base_dir (both posix, relative to OPF dir)."""
    path, _, frag = href.partition("#")
    path = urllib.parse.unquote(path)
    full = posixpath.normpath(posixpath.join(base_dir, path)) if path else ""
    return full + ("#" + frag if frag else "")


def _text(el):
    return re.sub(r"\s+", " ", "".join(el.itertext())).strip() if el is not None else ""


def read_book(slug, root):
    root = Path(root)
    container = ET.parse(root / "META-INF" / "container.xml")
    opf_rel = container.find(".//c:rootfile", NS).get("full-path")
    opf_dir = posixpath.dirname(opf_rel)
    book = SourceBook(slug=slug, root=root, opf_dir=opf_dir)

    opf = ET.parse(root / opf_rel).getroot()
    md = opf.find("opf:metadata", NS)

    # refinements: id -> {property: [values]}
    refines = {}
    for meta in md.findall("opf:meta", NS):
        ref = meta.get("refines")
        if ref and meta.get("property"):
            refines.setdefault(ref.lstrip("#"), {}).setdefault(meta.get("property"), []).append(_text(meta))

    title_el = md.find("dc:title", NS)
    book.title = _text(title_el)
    book.title_file_as = refines.get(title_el.get("id"), {}).get("file-as", [book.title])[0]
    book.language = _text(md.find("dc:language", NS))
    book.identifier = _text(md.find("dc:identifier", NS))
    book.sources = [_text(e) for e in md.findall("dc:source", NS)]
    book.subjects = [_text(e) for e in md.findall("dc:subject", NS)]
    for el in md.findall("dc:contributor", NS):
        book.contributors.append((_text(el), refines.get(el.get("id"), {}).get("role", [])))

    for item in opf.find("opf:manifest", NS).findall("opf:item", NS):
        book.manifest[item.get("id")] = ManifestItem(
            id=item.get("id"),
            href=resolve("", item.get("href")),
            media_type=item.get("media-type"),
            properties=(item.get("properties") or "").split(),
        )
    for ref in opf.find("opf:spine", NS).findall("opf:itemref", NS):
        book.spine.append((ref.get("idref"), ref.get("linear", "yes")))

    # epub:type words on <body> and top-level <section>/<article> of each XHTML file
    for item in book.manifest.values():
        if item.media_type != "application/xhtml+xml" or "nav" in item.properties:
            continue
        doc = ET.parse(book.content_dir / item.href).getroot()
        body = doc.find("x:body", NS)
        words = set((body.get(EPUB_TYPE) or "").split())
        for child in body:
            words.update((child.get(EPUB_TYPE) or "").split())
        book.epub_types[item.href] = words

    nav_item = next((i for i in book.manifest.values() if "nav" in i.properties), None)
    if nav_item:
        book.nav = _read_nav(book.content_dir / nav_item.href, posixpath.dirname(nav_item.href))
    return book


def _read_nav(path, nav_dir):
    doc = ET.parse(path).getroot()
    for nav in doc.iter("{%s}nav" % NS["x"]):
        if "toc" in (nav.get(EPUB_TYPE) or "").split():
            ol = nav.find("x:ol", NS)
            return _read_ol(ol, nav_dir) if ol is not None else []
    return []


def _read_ol(ol, nav_dir):
    nodes = []
    for li in ol.findall("x:li", NS):
        a = li.find("x:a", NS)
        if a is None:
            a = li.find("x:span", NS)
        sub = li.find("x:ol", NS)
        nodes.append(NavNode(
            label=_text(a),
            href=resolve(nav_dir, a.get("href", "")) if a is not None else "",
            children=_read_ol(sub, nav_dir) if sub is not None else [],
        ))
    return nodes


# --- reference scanning (to prune unreferenced images/css) -------------------

_ATTR_RE = re.compile(r'\b(?:href|src|xlink:href|poster|data)\s*=\s*"([^"]+)"')
_SRCSET_RE = re.compile(r'\bsrcset\s*=\s*"([^"]+)"')
_CSS_URL_RE = re.compile(r'url\(\s*[\'"]?([^\'")]+)[\'"]?\s*\)|@import\s+[\'"]([^\'"]+)[\'"]')


def local_refs(text, base_dir, is_css=False):
    """Return resolved local paths (relative to OPF dir) referenced by a file."""
    raw = []
    if is_css:
        for m in _CSS_URL_RE.finditer(text):
            raw.append(m.group(1) or m.group(2))
    else:
        raw += _ATTR_RE.findall(text)
        for srcset in _SRCSET_RE.findall(text):
            raw += [part.strip().split()[0] for part in srcset.split(",") if part.strip()]
        for style in re.findall(r"<style[^>]*>(.*?)</style>", text, re.S):
            raw += [m.group(1) or m.group(2) for m in _CSS_URL_RE.finditer(style)]
    out = set()
    for r in raw:
        if re.match(r"^[a-z][a-z0-9+.-]*:", r, re.I) or r.startswith("#"):
            continue
        out.add(resolve(base_dir, r).split("#", 1)[0])
    return out
