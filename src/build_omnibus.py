#!/usr/bin/env python3
"""Build an omnibus EPUB from several EPUBs (tuned for Standard Ebooks).

Usage: python3 -I src/build_omnibus.py recipes/sherlock-holmes.toml [--no-check]

Each source book's OPF directory is mirrored verbatim under epub/books/<slug>/,
so all of its internal links, CSS and images keep working unmodified. Only the
package document, the navigation (toc.xhtml + toc.ncx) and the omnibus's own
front/back matter are generated.
"""
import argparse
import datetime as dt
import posixpath
import re
import shutil
import subprocess
import sys
import urllib.parse
import uuid
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import templates as T  # noqa: E402
from epub_reader import NS, EPUB_TYPE, NavNode, local_refs, read_book, safe_extract  # noqa: E402
from fetch_epubs import epub_path, fetch_all, load_recipe  # noqa: E402

DEFAULT_DROP_TYPES = ["imprint", "colophon", "copyright-page"]
DEFAULT_DROP_FILES = ["onix.xml"]
XHTML = "application/xhtml+xml"
NCX = "application/x-dtbncx+xml"
KEEP_CONTRIBUTOR_ROLES = {"trc": "transcriber", "bkp": "producer"}


def file_as(title):
    m = re.match(r"^(The|A|An)\s+(.*)$", title)
    return f"{m.group(2)}, {m.group(1)}" if m else title


def href_out(path):
    return urllib.parse.quote(path, safe="/#-._~")


def strip_ns_decls(xml):
    return re.sub(r'\s+xmlns(:\w+)?="[^"]*"', "", xml)


# --- per-book processing ------------------------------------------------------

class BookPlan:
    """What to keep from one source book, and how it maps into the omnibus."""

    def __init__(self, book, recipe):
        self.book = book
        self.prefix = f"books/{book.slug}/"
        drop_types = set(recipe.get("drop_epub_types", DEFAULT_DROP_TYPES))
        drop_files = set(recipe.get("drop_files", DEFAULT_DROP_FILES))
        keep_titlepage = recipe.get("keep_titlepage", True)

        self.titlepage = next(iter(book.files_with_type("titlepage")), None)
        self.halftitles = set(book.files_with_type("halftitlepage"))

        dropped = set()
        for item in book.manifest.values():
            types = book.epub_types.get(item.href, set())
            if ("nav" in item.properties or item.media_type == NCX
                    or posixpath.basename(item.href) in drop_files
                    or types & drop_types
                    or (not keep_titlepage and item.href == self.titlepage)):
                dropped.add(item.href)
        if not keep_titlepage:
            self.titlepage = None

        # Keep every remaining XHTML doc; keep other resources only if referenced.
        docs = [i.href for i in book.manifest.values() if i.media_type == XHTML and i.href not in dropped]
        keep, queue = set(docs), list(docs)
        while queue:
            href = queue.pop()
            path = book.content_dir / href
            if not path.exists():
                continue
            is_css = href.endswith(".css")
            text = path.read_text(encoding="utf-8", errors="replace")
            for ref in local_refs(text, posixpath.dirname(href), is_css=is_css):
                item = book.item_by_href(ref)
                if item and ref not in keep and ref not in dropped:
                    keep.add(ref)
                    if item.media_type == "text/css":
                        queue.append(ref)
        self.keep = keep
        self.dropped = {i.href for i in book.manifest.values()} - keep

        self.spine = [(idref, linear) for idref, linear in book.spine
                      if book.manifest[idref].href in keep]
        first = book.manifest[self.spine[0][0]].href
        self.entry_href = self.prefix + (self.titlepage or first)
        body = next((book.manifest[i].href for i, _ in self.spine
                     if "bodymatter" in book.epub_types.get(book.manifest[i].href, ())), first)
        self.bodymatter_href = self.prefix + body

    def nav_children(self):
        def norm(s):
            return re.sub(r"\W+", " ", s).strip().lower()

        def walk(nodes):
            out = []
            for n in nodes:
                kids = walk(n.children)
                if n.file in self.dropped or n.file == self.book_titlepage_file():
                    out.extend(kids)
                elif n.file in self.halftitles and norm(n.label) == norm(self.book.title):
                    out.extend(kids)   # avoid "Book > Book > stories"
                else:
                    out.append(NavNode(n.label, self.prefix + n.href, kids))
            return out
        return walk(self.book.nav)

    def book_titlepage_file(self):
        return self.titlepage

    def colophon_paragraphs(self):
        """Reuse the source colophon's credit paragraphs; return (paras, closing)."""
        files = self.book.files_with_type("colophon")
        if not files:
            return [], None
        doc = ET.parse(self.book.content_dir / files[0]).getroot()
        section = next(s for s in doc.iter() if "colophon" in (s.get(EPUB_TYPE) or "").split())
        paras, closing = [], None
        for p in section.findall("x:p", NS):
            p.tail = None
            text = " ".join("".join(p.itertext()).split())
            html = strip_ns_decls(ET.tostring(p, encoding="unicode"))
            if re.search(r"relies on readers|anyone can contribute", text, re.I):
                closing = html
            elif re.search(r"\bcover page\b", text, re.I):
                continue    # describes the individual book's cover, which is not included
            else:
                paras.append(html)
        return paras, closing


# --- build --------------------------------------------------------------------

def build(recipe, run_check=True):
    root = recipe["_root"]
    out_name = recipe["output"]
    build_dir = root / recipe.get("build_dir", "build")
    work_dir = build_dir / "work"
    out_dir = build_dir / out_name
    epub_file = build_dir / f"{out_name}.epub"
    lang = recipe.get("language", "en")
    title, author = recipe["title"], recipe["author"]
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    uid = "urn:uuid:" + str(uuid.uuid5(uuid.NAMESPACE_URL, f"omnibus:{title}:{author}"))

    print("Fetching sources…")
    fetch_all(recipe)

    for d in (work_dir, out_dir):
        if d.exists():
            shutil.rmtree(d)
    epub_file.unlink(missing_ok=True)
    content = out_dir / "epub"
    (content / "text").mkdir(parents=True)
    (content / "css").mkdir()
    (content / "images").mkdir()
    (out_dir / "META-INF").mkdir()

    print("Reading sources…")
    plans = []
    for spec in recipe["books"]:
        slug = spec["slug"]
        if not re.match(r"^[A-Za-z][\w.-]*$", slug):
            raise SystemExit(f"slug must start with a letter and be a valid XML id: {slug!r}")
        src = work_dir / slug
        safe_extract(epub_path(recipe, spec), src)
        plan = BookPlan(read_book(slug, src), recipe)
        plans.append(plan)
        print(f"  {plan.book.title}: keep {len(plan.keep)} files, drop {len(plan.dropped)}")

    # --- copy each book's kept files into epub/books/<slug>/
    manifest = []  # (id, href, media_type, properties)
    spine = []     # (idref, linear)
    for plan in plans:
        b = plan.book
        for item in b.manifest.values():
            if item.href not in plan.keep:
                continue
            dest = content / plan.prefix / item.href
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(b.content_dir / item.href, dest)
            props = [p for p in item.properties if p not in ("nav", "cover-image")]
            manifest.append((f"{b.slug}-{item.id}", plan.prefix + item.href, item.media_type, props))

    # --- omnibus front/back matter
    first = plans[0].book
    css = []
    for name in ("core.css", "se.css"):
        src = first.content_dir / "css" / name
        if src.exists():
            shutil.copy2(src, content / "css" / name)
            manifest.append((name, f"css/{name}", "text/css", []))
            css.append(f"../css/{name}")
    (content / "css" / "local.css").write_text(T.LOCAL_CSS, encoding="utf-8")
    manifest.append(("local.css", "css/local.css", "text/css", []))
    css.append("../css/local.css")

    cover_src = root / recipe["cover"]
    cover_ext = cover_src.suffix.lower().lstrip(".")
    cover_name = f"cover.{cover_ext}"
    shutil.copy2(cover_src, content / "images" / cover_name)
    manifest.append(("cover-image", f"images/{cover_name}",
                     "image/png" if cover_ext == "png" else "image/jpeg", ["cover-image"]))

    def page(name, text):
        (content / "text" / name).write_text(text, encoding="utf-8")
        page_id = name.replace(".xhtml", "")
        manifest.append((page_id, f"text/{name}", XHTML, []))
        return page_id

    cover_html = T.cover_page(lang, f"The cover for {title}, by {author}.")
    cover_html = cover_html.replace("cover.jpg", cover_name)
    front = [page("cover.xhtml", cover_html),
             page("titlepage.xhtml", T.titlepage(lang, title, author, recipe.get("subtitle"), css)),
             page("imprint.xhtml", T.imprint(lang, title, [(p.book.title, p.book.identifier
                                                             if p.book.identifier.startswith("http") else None)
                                                            for p in plans], css))]

    blocks, closing = [], None
    for p in plans:
        paras, close = p.colophon_paragraphs()
        blocks.append((p.book.slug, p.book.title, paras))
        closing = closing or close
    back = [page("colophon.xhtml", T.colophon(lang, title, now.strftime("%B %-d, %Y"), now.isoformat().replace("+00:00", "Z"),
                                              blocks, closing, css))]

    unc = first.files_with_type("copyright-page")
    unc_text = None
    if unc:
        unc_text = (first.content_dir / unc[0]).read_text(encoding="utf-8")
        refs = local_refs(unc_text, "text")
        if not all((content / r).exists() for r in refs):
            unc_text = None
    back.append(page("uncopyright.xhtml", unc_text or T.uncopyright_fallback(lang, css)))

    # --- navigation
    book_nodes = [NavNode(p.book.title, p.entry_href, p.nav_children()) for p in plans]
    tree = ([NavNode("Titlepage", "text/titlepage.xhtml"), NavNode("Imprint", "text/imprint.xhtml")]
            + book_nodes
            + [NavNode("Colophon", "text/colophon.xhtml"), NavNode("Uncopyright", "text/uncopyright.xhtml")])
    for n in _walk(tree):
        n.href = href_out(n.href)
    landmarks = [("cover", "text/cover.xhtml", "Cover"),
                 ("frontmatter", "text/titlepage.xhtml", "Frontmatter"),
                 ("toc", "toc.xhtml", "Table of Contents"),
                 ("bodymatter", href_out(plans[0].bodymatter_href), title),
                 ("backmatter", "text/colophon.xhtml", "Backmatter")]
    (content / "toc.xhtml").write_text(T.nav_doc(lang, tree, landmarks), encoding="utf-8")
    manifest.append(("toc.xhtml", "toc.xhtml", XHTML, ["nav"]))
    (content / "toc.ncx").write_text(T.ncx_doc(lang, uid, title, tree), encoding="utf-8")
    manifest.append(("ncx", "toc.ncx", NCX, []))

    # --- spine
    spine = [(i, "yes") for i in front] + [("toc.xhtml", "yes")]
    for p in plans:
        spine += [(f"{p.book.slug}-{idref}", linear) for idref, linear in p.spine]
    spine += [(i, "yes") for i in back]

    # --- package document
    (out_dir / "mimetype").write_text("application/epub+zip", encoding="ascii")
    (out_dir / "META-INF" / "container.xml").write_text(T.CONTAINER_XML, encoding="utf-8")
    _mark_svg_and_scripted(content, manifest)
    (content / "content.opf").write_text(
        opf_doc(recipe, plans, manifest, spine, uid, now), encoding="utf-8")

    zip_epub(out_dir, epub_file)
    print(f"\nWrote {epub_file.relative_to(root)} ({epub_file.stat().st_size / 1e6:.1f} MB)")
    print_summary(book_nodes)

    if run_check:
        return epubcheck(epub_file)
    return 0


def _walk(nodes):
    for n in nodes:
        yield n
        yield from _walk(n.children)


def _mark_svg_and_scripted(content, manifest):
    """Ensure XHTML items containing inline SVG carry the 'svg' property."""
    for i, (mid, href, mt, props) in enumerate(manifest):
        if mt == XHTML and "svg" not in props and href != "toc.xhtml":
            text = (content / href).read_text(encoding="utf-8")
            if "<svg" in text:
                manifest[i] = (mid, href, mt, props + ["svg"])


def opf_doc(recipe, plans, manifest, spine, uid, now):
    e = T.e
    title, author = recipe["title"], recipe["author"]
    md = [
        f'\t\t<dc:identifier id="uid">{uid}</dc:identifier>',
        f'\t\t<meta property="dcterms:modified">{now.isoformat().replace("+00:00", "Z")}</meta>',
        f'\t\t<dc:title id="title">{e(title)}</dc:title>',
        f'\t\t<meta property="file-as" refines="#title">{e(recipe.get("title_file_as", file_as(title)))}</meta>',
        f'\t\t<dc:creator id="author">{e(author)}</dc:creator>',
        f'\t\t<meta property="file-as" refines="#author">{e(recipe.get("author_file_as", author))}</meta>',
        '\t\t<meta property="role" refines="#author" scheme="marc:relators">aut</meta>',
        f'\t\t<dc:language>{e(recipe.get("language", "en"))}</dc:language>',
    ]
    if recipe.get("description"):
        md.append(f'\t\t<dc:description>{e(recipe["description"])}</dc:description>')
    md.append('\t\t<dc:rights>The source text and artwork in this ebook are believed to be in the United States '
              'public domain. The contributors to the source ebooks dedicate their contributions to the worldwide '
              'public domain via the terms in the CC0 1.0 Universal Public Domain Dedication '
              '(https://creativecommons.org/publicdomain/zero/1.0/).</dc:rights>')
    for p in plans:
        if p.book.identifier:
            md.append(f"\t\t<dc:source>{e(p.book.identifier)}</dc:source>")
    seen = []
    for p in plans:
        for s in p.book.subjects:
            if s not in seen:
                seen.append(s)
    md += [f"\t\t<dc:subject>{e(s)}</dc:subject>" for s in seen]
    people = {}
    for p in plans:
        for name, roles in p.book.contributors:
            for r in roles:
                if r in KEEP_CONTRIBUTOR_ROLES and name != "Anonymous":
                    people.setdefault(name, [])
                    if r not in people[name]:
                        people[name].append(r)
    for n, (name, roles) in enumerate(people.items(), 1):
        md.append(f'\t\t<dc:contributor id="contributor-{n}">{e(name)}</dc:contributor>')
        md += [f'\t\t<meta property="role" refines="#contributor-{n}" scheme="marc:relators">{r}</meta>'
               for r in roles]
    md += [
        '\t\t<meta property="schema:accessMode">textual</meta>',
        '\t\t<meta property="schema:accessModeSufficient">textual</meta>',
        '\t\t<meta property="schema:accessibilityFeature">alternativeText</meta>',
        '\t\t<meta property="schema:accessibilityFeature">readingOrder</meta>',
        '\t\t<meta property="schema:accessibilityFeature">structuralNavigation</meta>',
        '\t\t<meta property="schema:accessibilityFeature">tableOfContents</meta>',
        '\t\t<meta property="schema:accessibilityHazard">none</meta>',
        '\t\t<meta property="schema:accessibilitySummary">Compiled from Standard Ebooks editions, which conform to WCAG 2.2 Level AA.</meta>',
        '\t\t<meta name="cover" content="cover-image"/>',
    ]
    items = []
    for mid, href, mt, props in manifest:
        pa = f' properties="{" ".join(props)}"' if props else ""
        items.append(f'\t\t<item href="{e(href_out(href))}" id="{e(mid)}" media-type="{mt}"{pa}/>')
    refs = [f'\t\t<itemref idref="{e(i)}"{"" if lin == "yes" else " linear=" + chr(34) + lin + chr(34)}/>'
            for i, lin in spine]
    nl = "\n"
    return f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" dir="ltr" prefix="schema: http://schema.org/" unique-identifier="uid" version="3.0" xml:lang="{recipe.get("language", "en")}">
	<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
{nl.join(md)}
	</metadata>
	<manifest>
{nl.join(items)}
	</manifest>
	<spine toc="ncx">
{nl.join(refs)}
	</spine>
	<guide>
		<reference href="text/cover.xhtml" title="Cover" type="cover"/>
		<reference href="text/titlepage.xhtml" title="Titlepage" type="title-page"/>
		<reference href="toc.xhtml" title="Table of Contents" type="toc"/>
	</guide>
</package>
"""


def zip_epub(src_dir, dest):
    with zipfile.ZipFile(dest, "w") as z:
        z.write(src_dir / "mimetype", "mimetype", compress_type=zipfile.ZIP_STORED)
        for path in sorted(src_dir.rglob("*")):
            rel = path.relative_to(src_dir).as_posix()
            if path.is_file() and rel != "mimetype" and path.name != ".DS_Store":
                z.write(path, rel, compress_type=zipfile.ZIP_DEFLATED)


def print_summary(book_nodes):
    print("\nTable of contents:")
    total = 0
    for b in book_nodes:
        print(f"  {b.label} ({len(b.children)} entries)")
        for c in b.children:
            sub = f"  [{len(c.children)} sections]" if c.children else ""
            print(f"      {c.label}{sub}")
        total += len(b.children)
    print(f"  — {len(book_nodes)} books, {total} second-level entries")


def epubcheck(epub_file):
    exe = shutil.which("epubcheck")
    if not exe:
        print("\nepubcheck not found on PATH; skipping validation.")
        return 0
    print("\nRunning epubcheck…")
    r = subprocess.run([exe, str(epub_file)], capture_output=True, text=True)
    lines = (r.stdout + r.stderr).strip().splitlines()
    issues = [l for l in lines if re.match(r"^(ERROR|WARNING|FATAL|USAGE)", l)]
    for l in issues[:50]:
        print("  " + l)
    if len(issues) > 50:
        print(f"  … {len(issues) - 50} more")
    for l in lines:
        if re.search(r"Messages:|No errors or warnings|Check finished", l):
            print("  " + l)
    return 0 if r.returncode == 0 else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("recipe")
    ap.add_argument("--no-check", action="store_true", help="skip epubcheck")
    args = ap.parse_args()
    return build(load_recipe(args.recipe), run_check=not args.no_check)


if __name__ == "__main__":
    sys.exit(main())
