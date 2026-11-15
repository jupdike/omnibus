"""XHTML/XML templates for the omnibus's own pages, written in Standard Ebooks style."""
from html import escape

EPUB_PREFIX = ("z3998: http://www.daisy.org/z3998/2012/vocab/structure/, "
               "se: https://standardebooks.org/vocab/1.0")


def e(s):
    return escape(s, quote=True)


def xhtml(title, lang, body_type, inner, css):
    links = "\n".join(
        f'\t\t<link href="{e(href)}" rel="stylesheet" type="text/css"/>' for href in css)
    return f"""<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="{lang}" epub:prefix="{EPUB_PREFIX}" xml:lang="{lang}">
	<head>
		<title>{e(title)}</title>
{links}
	</head>
	<body epub:type="{body_type}">
{inner}
	</body>
</html>
"""


LOCAL_CSS = """@charset "utf-8";
@namespace epub "http://www.idpf.org/2007/ops";

/* Omnibus cover page */
section.omnibus-cover{
	margin: 0;
	padding: 0;
	text-align: center;
}

section.omnibus-cover img{
	display: block;
	height: 100vh;
	margin: 0 auto;
	max-width: 100%;
	object-fit: contain;
}

/* Omnibus title page */
section.omnibus-titlepage{
	margin-top: 25vh;
	text-align: center;
}

section.omnibus-titlepage h1{
	font-size: 2em;
	font-variant: small-caps;
	letter-spacing: 0.05em;
	line-height: 1.2;
	margin: 0;
}

section.omnibus-titlepage p{
	margin-top: 3em;
	text-indent: 0;
}

section.omnibus-titlepage p.omnibus-contents{
	font-size: smaller;
	font-style: italic;
	margin-top: 1em;
}

/* Omnibus imprint: list of source books */
section.epub-type-contains-word-imprint ul{
	font-size: smaller;
	list-style: none;
	margin: 1em auto 0;
	padding: 0;
	text-align: center;
	width: 75%;
}

/* Omnibus colophon: one block per source book */
section.epub-type-contains-word-colophon section{
	margin-top: 3em;
}

section.epub-type-contains-word-colophon section h3{
	font-size: 1em;
	font-style: italic;
	font-variant: normal;
	margin: 0;
}
"""


def cover_page(lang, alt):
    inner = f"""		<section class="omnibus-cover" id="cover" epub:type="cover">
			<img alt="{e(alt)}" src="../images/cover.jpg"/>
		</section>"""
    return xhtml("Cover", lang, "frontmatter", inner, ["../css/local.css"])


def titlepage(lang, title, author, subtitle, css):
    sub = f'\n\t\t\t<p class="omnibus-contents">{e(subtitle)}</p>' if subtitle else ""
    inner = f"""		<section class="omnibus-titlepage" id="titlepage" epub:type="titlepage">
			<h1 epub:type="title">{e(title)}</h1>
			<p>By <b epub:type="z3998:author-name">{e(author)}</b></p>{sub}
		</section>"""
    return xhtml("Titlepage", lang, "frontmatter", inner, css)


def imprint(lang, title, books, css):
    """books: [(title, url)]"""
    items = "\n".join(
        f'\t\t\t\t<li><a href="{e(url)}"><i>{e(t)}</i></a></li>' if url else f"\t\t\t\t<li><i>{e(t)}</i></li>"
        for t, url in books)
    inner = f"""		<section class="epub-type-contains-word-imprint" id="imprint" epub:type="imprint">
			<header>
				<h2 epub:type="title">Imprint</h2>
			</header>
			<p>This omnibus edition of <i>{e(title)}</i> collects, without alteration to their text, the following {len(books)} ebooks produced by volunteers for <a href="https://standardebooks.org/">Standard Ebooks</a>:</p>
			<ul>
{items}
			</ul>
			<p>Each book’s own title page has been retained; the individual imprints, colophons, and uncopyrights have been consolidated into a single imprint, colophon, and uncopyright for the whole volume. This omnibus was assembled independently and is not an official Standard Ebooks production.</p>
			<p>The source text and artwork in this ebook are believed to be in the United States public domain; that is, they are believed to be free of copyright restrictions in the United States. They may still be copyrighted in other countries, so users located outside of the United States must check their local laws before using this ebook. The creators of, and contributors to, these ebooks dedicate their contributions to the worldwide public domain via the terms in the <a href="https://creativecommons.org/publicdomain/zero/1.0/">CC0 1.0 Universal Public Domain Dedication</a>. For full license information, see the <a href="uncopyright.xhtml">Uncopyright</a> at the end of this ebook.</p>
		</section>"""
    return xhtml("Imprint", lang, "frontmatter", inner, css)


def colophon(lang, title, compiled_on, compiled_iso, book_blocks, closing_html, css):
    """book_blocks: [(slug, title, [paragraph_xhtml])]"""
    blocks = []
    for slug, btitle, paras in book_blocks:
        body = "\n".join("\t\t\t\t" + p for p in paras)
        blocks.append(f"""			<section id="colophon-{e(slug)}">
				<h3><i>{e(btitle)}</i></h3>
{body}
			</section>""")
    closing = f"\n\t\t\t{closing_html}" if closing_html else ""
    inner = f"""		<section class="epub-type-contains-word-colophon" id="colophon" role="doc-colophon" epub:type="colophon">
			<header>
				<h2 epub:type="title">Colophon</h2>
			</header>
			<p><i>{e(title)}</i><br/>
			was compiled on <time datetime="{compiled_iso}">{e(compiled_on)}</time><br/>
			from the {len(book_blocks)} Standard Ebooks editions credited below.</p>
{chr(10).join(blocks)}{closing}
		</section>"""
    return xhtml("Colophon", lang, "backmatter", inner, css)


def uncopyright_fallback(lang, css):
    inner = """		<section class="epub-type-contains-word-copyright-page" id="uncopyright" epub:type="copyright-page">
			<h2 epub:type="title">Uncopyright</h2>
			<p>The source text and artwork in this ebook are believed to be in the United States public domain. The contributors to this ebook release their contributions under the terms in the <a href="https://creativecommons.org/publicdomain/zero/1.0/">CC0 1.0 Universal Public Domain Dedication</a>.</p>
		</section>"""
    return xhtml("Uncopyright", lang, "backmatter", inner, css)


def _nav_ol(nodes, depth):
    tabs = "\t" * depth
    out = [f"{tabs}<ol>"]
    for n in nodes:
        out.append(f"{tabs}\t<li>")
        out.append(f'{tabs}\t\t<a href="{e(n.href)}">{e(n.label)}</a>')
        if n.children:
            out.append(_nav_ol(n.children, depth + 2))
        out.append(f"{tabs}\t</li>")
    out.append(f"{tabs}</ol>")
    return "\n".join(out)


def nav_doc(lang, tree, landmarks):
    """tree: [NavNode] with hrefs relative to the nav file. landmarks: [(epub_type, href, label)]"""
    lm = "\n".join(
        f'\t\t\t\t<li>\n\t\t\t\t\t<a href="{e(h)}" epub:type="{t}">{e(l)}</a>\n\t\t\t\t</li>'
        for t, h, l in landmarks)
    return f"""<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="{lang}" epub:prefix="{EPUB_PREFIX}" xml:lang="{lang}">
	<head>
		<title>Table of Contents</title>
	</head>
	<body epub:type="frontmatter">
		<nav id="toc" role="doc-toc" epub:type="toc">
			<h2 id="toc-title" epub:type="title">Table of Contents</h2>
{_nav_ol(tree, 3)}
		</nav>
		<nav id="landmarks" epub:type="landmarks">
			<h2 id="landmarks-title" epub:type="title">Landmarks</h2>
			<ol>
{lm}
			</ol>
		</nav>
	</body>
</html>
"""


def ncx_doc(lang, uid, title, tree):
    counter = [0]

    def points(nodes, depth):
        out = []
        for n in nodes:
            counter[0] += 1
            i = counter[0]
            t = "\t" * depth
            out.append(f'{t}<navPoint id="navpoint-{i}" playOrder="{i}">')
            out.append(f"{t}\t<navLabel>\n{t}\t\t<text>{e(n.label)}</text>\n{t}\t</navLabel>")
            out.append(f'{t}\t<content src="{e(n.href)}"/>')
            if n.children:
                out.append(points(n.children, depth + 1))
            out.append(f"{t}</navPoint>")
        return "\n".join(out)

    def depth_of(nodes):
        return 1 + max((depth_of(n.children) for n in nodes), default=0) if nodes else 0

    body = points(tree, 2)
    return f"""<?xml version="1.0" encoding="utf-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1" xml:lang="{lang}">
	<head>
		<meta content="{e(uid)}" name="dtb:uid"/>
		<meta content="{depth_of(tree)}" name="dtb:depth"/>
		<meta content="0" name="dtb:totalPageCount"/>
		<meta content="0" name="dtb:maxPageNumber"/>
	</head>
	<docTitle>
		<text>{e(title)}</text>
	</docTitle>
	<navMap id="navmap">
{body}
	</navMap>
</ncx>
"""


CONTAINER_XML = """<?xml version="1.0" encoding="utf-8"?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
	<rootfiles>
		<rootfile full-path="epub/content.opf" media-type="application/oebps-package+xml"/>
	</rootfiles>
</container>
"""
