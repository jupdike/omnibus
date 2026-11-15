#!/usr/bin/env python3
"""Download the source EPUBs listed in an omnibus recipe into the input folder.

Usage: python3 -I src/fetch_epubs.py recipes/sherlock-holmes.toml [--force]
"""
import argparse
import html
import re
import sys
import tomllib
import urllib.parse
import urllib.request
from pathlib import Path

USER_AGENT = "omnibus-builder/1.0 (python urllib)"


def load_recipe(path):
    path = Path(path).resolve()
    with open(path, "rb") as f:
        recipe = tomllib.load(f)
    # Project root = parent of the recipes/ folder
    recipe["_root"] = path.parent.parent
    return recipe


def epub_path(recipe, book):
    return recipe["_root"] / recipe.get("input_dir", "input") / Path(book["url"]).name


def download(url, _depth=0):
    """GET url; follow an HTML meta-refresh (Standard Ebooks shows a 'thank you'
    page before the real file, which lives at ...epub?source=download)."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req) as resp:
        data = resp.read()
    if data.startswith(b"PK") or _depth > 2:
        return data
    m = re.search(rb'http-equiv="refresh"\s+content="\d+;\s*url=([^"]+)"', data, re.I)
    if not m:
        return data
    return download(urllib.parse.urljoin(url, html.unescape(m.group(1).decode())), _depth + 1)


def fetch_all(recipe, force=False):
    paths = []
    for book in recipe["books"]:
        dest = epub_path(recipe, book)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists() and not force:
            print(f"  have  {dest.name}")
        else:
            print(f"  fetch {book['url']}")
            data = download(book["url"])
            if not data.startswith(b"PK"):
                raise RuntimeError(f"{book['url']} did not return a zip/epub")
            tmp = dest.with_suffix(".part")
            tmp.write_bytes(data)
            tmp.replace(dest)
        paths.append(dest)
    return paths


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("recipe")
    ap.add_argument("--force", action="store_true", help="re-download even if present")
    args = ap.parse_args()
    fetch_all(load_recipe(args.recipe), force=args.force)


if __name__ == "__main__":
    sys.exit(main())
