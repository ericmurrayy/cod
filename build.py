#!/usr/bin/env python3
"""Compile the Claude Design sources in design-src/ into a plain static site in site/.

The .dc.html sources are Claude Design documents: an <x-dc> template with
{{ prop }} placeholders, <sc-if> conditionals, style-hover attributes and a
React "DCLogic" script. This compiler resolves all of that statically:

  {{ phone }} / {{ tel }}       -> real values
  {{ openLabel }}               -> <span data-open-label> updated by assets/site.js
  <sc-if isDesktop>             -> <div class="cod-desktop"> (CSS media query)
  <sc-if showCallBar>           -> <div class="cod-mobile">  (CSS media query)
  <sc-if bookingPending/Done>   -> data-booking-* blocks toggled by assets/site.js
  style-hover="..."             -> data-hv="N" + generated :hover rules
  <x-import image-slot>         -> styled placeholder block
  links to *.dc.html            -> *.html (homepage -> index.html)

It also injects a site-wide mobile menu (hamburger + dropdown panel) into every
page header and emits assets/site.css, assets/site.js, sitemap.xml, robots.txt.

Usage:
  python3 build.py             build everything into site/
  python3 build.py --missing   list manifest files not yet in design-src/
"""
import os
import re
import sys
import html

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, "design-src")
OUT = os.path.join(ROOT, "site")
DOMAIN = "https://chelmsfordoverheaddoor.com"
PHONE = "(978) 555-0100"
TEL = "tel:+19785550100"
OPEN_LABEL_DEFAULT = "Open Mon–Sat 7am–7pm"

HOMEPAGE_SRC = "COD Homepage v2.dc.html"

MENU_LINKS = [
    ("Home", "index.html"),
    ("Services", "pages/services.html"),
    ("Service Areas", "pages/service-areas.html"),
    ("Brands", "pages/brands.html"),
    ("Our Guarantee", "pages/guarantee.html"),
    ("About", "pages/about.html"),
    ("Contact", "pages/contact.html"),
]


def manifest_pages():
    with open(os.path.join(SRC, "MANIFEST.txt")) as f:
        return [ln.strip() for ln in f if ln.strip()]


def list_missing():
    return [p for p in manifest_pages() if not os.path.exists(os.path.join(SRC, p))]


class HoverRegistry:
    """Dedupes style-hover values into data-hv indexes shared across all pages."""

    def __init__(self):
        self.rules = {}

    def index_for(self, css):
        css = css.strip().rstrip(";")
        if css not in self.rules:
            self.rules[css] = len(self.rules) + 1
        return self.rules[css]

    def css(self):
        lines = []
        for rule, idx in sorted(self.rules.items(), key=lambda kv: kv[1]):
            decls = ";".join(d.strip() + " !important" for d in rule.split(";") if d.strip())
            lines.append(f'[data-hv="{idx}"]:hover{{{decls}}}')
        return "\n".join(lines)


HOVERS = HoverRegistry()


def sub_hover(m):
    idx = HOVERS.index_for(m.group(1))
    return f'data-hv="{idx}"'


def rel_prefix(out_rel):
    """'' for files at site root, '../' for files in site/pages/."""
    return "../" if "/" in out_rel else ""


def out_path_for(src_rel):
    if src_rel == HOMEPAGE_SRC:
        return "index.html"
    assert src_rel.startswith("pages/") and src_rel.endswith(".dc.html")
    return src_rel[: -len(".dc.html")] + ".html"


def rewrite_links(doc, out_rel):
    # Homepage references (with or without ../, space or %20).
    home = rel_prefix(out_rel) + "index.html" if out_rel != "index.html" else "index.html"
    doc = re.sub(r'href="(?:\.\./)?COD(?:%20| )Homepage(?:%20| )v2\.dc\.html"', f'href="{home}"', doc)
    # Everything else: *.dc.html -> *.html
    doc = doc.replace(".dc.html", ".html")
    return doc


def convert_sc_ifs(doc, src_rel):
    def repl(m):
        cond = m.group(1)
        if cond == "isDesktop":
            return '<div class="cod-desktop">'
        if cond == "showCallBar":
            return '<div class="cod-mobile">'
        if cond == "bookingPending":
            return '<div data-booking-pending>'
        if cond == "bookingDone":
            return '<div data-booking-done hidden>'
        raise SystemExit(f"{src_rel}: unhandled sc-if condition {cond!r}")

    doc = re.sub(r'<sc-if\s+value="\{\{\s*(\w+)\s*\}\}"[^>]*>', repl, doc)
    return doc.replace("</sc-if>", "</div>")


def convert_image_slots(doc):
    def repl(m):
        tag = m.group(0)
        style = re.search(r'style="([^"]*)"', tag)
        label = re.search(r'placeholder="([^"]*)"', tag)
        style_attr = style.group(1) if style else "width:100%;height:220px;"
        text = html.escape(label.group(1)) if label else "Photo"
        return (
            f'<div class="cod-photo" role="img" aria-label="{text}" style="{style_attr}">'
            f"<span>{text}</span></div>"
        )

    return re.sub(r"<x-import\b[^>]*></x-import>", repl, doc)


def convert_booking_handlers(doc):
    doc = doc.replace('onSubmit="{{ submitBooking }}"', "data-booking-form")
    doc = doc.replace('onClick="{{ resetBooking }}"', "data-booking-reset")
    doc = doc.replace('required="{{ true }}"', "required")
    # Literal attribute expressions like rows="{{ 3 }}" -> rows="3"
    doc = re.sub(r'="\{\{\s*(\d+)\s*\}\}"', r'="\1"', doc)
    return doc


def compile_page(src_rel):
    with open(os.path.join(SRC, src_rel)) as f:
        doc = f.read()
    out_rel = out_path_for(src_rel)
    prefix = rel_prefix(out_rel)

    m = re.search(r"<x-dc>(.*)</x-dc>", doc, re.S)
    if not m:
        raise SystemExit(f"{src_rel}: no <x-dc> template found")
    template = m.group(1)
    head_html = doc[: m.start()]

    # Pull <helmet> children up into <head>.
    hm = re.search(r"<helmet>(.*?)</helmet>", template, re.S)
    helmet = hm.group(1).strip() if hm else ""
    if hm:
        template = template[: hm.start()] + template[hm.end():]

    # Strip runtime loader + document scaffold from the captured head.
    head_html = re.sub(r'<script src="\.{1,2}/support\.js"></script>\s*', "", head_html)
    hm2 = re.search(r"<head>(.*)</head>", head_html, re.S)
    if not hm2:
        raise SystemExit(f"{src_rel}: no <head> found")
    head_inner = hm2.group(1).strip()

    canonical = DOMAIN + "/" + (out_rel if out_rel != "index.html" else "")
    head = (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n"
        + head_inner + "\n"
        + helmet + "\n"
        + f'<link rel="canonical" href="{canonical}">\n'
        + f'<link rel="stylesheet" href="{prefix}assets/site.css">\n'
        + f'<script src="{prefix}assets/site.js" defer></script>\n'
        + "</head>\n<body>\n"
    )

    body = template
    body = convert_sc_ifs(body, src_rel)
    body = convert_image_slots(body)
    body = convert_booking_handlers(body)
    body = re.sub(r'style-hover="([^"]*)"', sub_hover, body)
    body = re.sub(r'\s*data-screen-label="[^"]*"', "", body)
    body = body.replace("{{ tel }}", TEL).replace("{{ phone }}", PHONE)
    body = body.replace(
        "{{ openLabel }}", f"<span data-open-label>{OPEN_LABEL_DEFAULT}</span>"
    )
    leftover = re.search(r"\{\{\s*\w+\s*\}\}", body)
    if leftover:
        raise SystemExit(f"{src_rel}: unresolved template expression {leftover.group(0)}")

    body = inject_menu(body, out_rel)
    body = rewrite_links(body, out_rel)

    out_file = os.path.join(OUT, out_rel)
    os.makedirs(os.path.dirname(out_file), exist_ok=True)
    with open(out_file, "w") as f:
        f.write(head + body.strip() + "\n</body>\n</html>\n")
    return out_rel


def menu_html(out_rel):
    prefix = rel_prefix(out_rel)
    # From site root the prefix is "", from pages/ it is "../", so both
    # index.html and pages/*.html targets resolve correctly.
    items = [f'<a href="{prefix}{target}">{label}</a>' for label, target in MENU_LINKS]
    links = "\n      ".join(items)
    return f"""
    <button id="cod-menu-btn" class="cod-menu-btn" aria-expanded="false" aria-controls="cod-menu" aria-label="Open menu">
      <span></span><span></span><span></span>
    </button>
    <nav id="cod-menu" class="cod-menu" hidden aria-label="Site menu">
      {links}
      <a class="cod-menu-call" href="{TEL}">Call {PHONE} — same-day</a>
    </nav>"""


def inject_menu(body, out_rel):
    """Insert the hamburger button into the header flex row and the dropdown
    panel just before </header> so it stays inside the sticky bar."""
    m = re.search(r"</div>\s*</header>", body)
    if not m:
        raise SystemExit(f"{out_rel}: header structure not found for menu injection")
    menu = menu_html(out_rel)
    # Button goes inside the flex row (before its closing </div>), the panel
    # after the row but still inside <header>.
    btn, panel = menu.split('<nav id="cod-menu"', 1)
    panel = '<nav id="cod-menu"' + panel
    return body[: m.start()] + btn + "\n</div>\n" + panel + "\n</header>" + body[m.end():]


SITE_CSS_BASE = """/* Generated by build.py — shared site styles */
html { -webkit-text-size-adjust: 100%; }
img, svg, video, iframe { max-width: 100%; }

/* Desktop-only / mobile-only wrappers (compiled from <sc-if>) */
.cod-desktop { display: contents; }
.cod-mobile { display: contents; }
@media (max-width: 760px) { .cod-desktop { display: none; } }
@media (min-width: 761px) { .cod-mobile { display: none; } }

/* Hamburger button (mobile only) */
.cod-menu-btn {
  display: none; flex: none; width: 46px; height: 42px; margin-left: 2px;
  background: transparent; border: 1px solid #2c3f50; cursor: pointer;
  flex-direction: column; align-items: center; justify-content: center; gap: 5px;
  padding: 0;
}
.cod-menu-btn span { display: block; width: 20px; height: 3px; background: #ffaa1d; transition: transform .18s, opacity .18s; }
.cod-menu-btn[aria-expanded="true"] span:nth-child(1) { transform: translateY(8px) rotate(45deg); }
.cod-menu-btn[aria-expanded="true"] span:nth-child(2) { opacity: 0; }
.cod-menu-btn[aria-expanded="true"] span:nth-child(3) { transform: translateY(-8px) rotate(-45deg); }
@media (max-width: 760px) { .cod-menu-btn { display: flex; } }

/* Dropdown menu panel */
.cod-menu {
  display: flex; flex-direction: column; background: #101a21;
  border-top: 1px solid #2c3f50; padding: 8px 16px 16px;
}
.cod-menu[hidden] { display: none; }
.cod-menu a {
  color: #e9eef1; text-decoration: none; font-family: 'Barlow Condensed', 'Arial Narrow', sans-serif;
  font-weight: 700; text-transform: uppercase; letter-spacing: .05em; font-size: 20px;
  padding: 12px 4px; border-bottom: 1px solid #223343;
}
.cod-menu a:hover { color: #ffaa1d; }
.cod-menu .cod-menu-call {
  margin-top: 14px; background: #ffaa1d; color: #18242e; text-align: center;
  padding: 14px; border-bottom: none; font-size: 21px;
}

/* Photo placeholders (compiled from <x-import image-slot>) */
.cod-photo {
  display: flex; align-items: center; justify-content: center;
  background: #18242e;
  background-image: repeating-linear-gradient(to bottom, transparent 0, transparent 34px, #2c3f50 34px, #2c3f50 36px);
  border: 1px solid #2c3f50;
}
.cod-photo span {
  font-family: 'IBM Plex Mono', monospace; font-size: 11px; font-weight: 600;
  letter-spacing: .14em; text-transform: uppercase; color: #677a86;
  background: #101a21; padding: 6px 12px; border: 1px solid #2c3f50;
}

/* Mobile polish */
@media (max-width: 760px) {
  /* keep tap targets comfortable */
  a { -webkit-tap-highlight-color: rgba(255, 170, 29, .2); }
  /* the hamburger squeezes the header row; slim the call CTA so the
     wordmark never clips */
  header a[href^="tel:"] { padding: 7px 10px !important; }
  header a[href^="tel:"] > span:first-child { font-size: 9px !important; letter-spacing: .1em !important; }
  header a[href^="tel:"] > span:last-child { font-size: 16px !important; }
  header > div > a:first-child > span:last-child { font-size: 14px !important; }
}
@media (min-width: 761px) {
  /* the 96px footer padding only exists to clear the mobile call bar */
  footer { padding-bottom: 44px !important; }
}

/* Generated :hover rules (compiled from style-hover attributes) */
"""

SITE_JS = """// Generated by build.py — menu toggle, open-hours label, booking form.
(function () {
  'use strict';

  // Mobile menu
  var btn = document.getElementById('cod-menu-btn');
  var menu = document.getElementById('cod-menu');
  if (btn && menu) {
    btn.addEventListener('click', function () {
      var open = btn.getAttribute('aria-expanded') === 'true';
      btn.setAttribute('aria-expanded', String(!open));
      btn.setAttribute('aria-label', open ? 'Open menu' : 'Close menu');
      menu.hidden = open;
    });
    menu.addEventListener('click', function (e) {
      if (e.target.closest('a')) { btn.setAttribute('aria-expanded', 'false'); menu.hidden = true; }
    });
  }

  // Live open/closed label (Mon–Sat 7am–7pm)
  var now = new Date();
  var open = now.getDay() >= 1 && now.getDay() <= 6 && now.getHours() >= 7 && now.getHours() < 19;
  var label = open ? 'Open now — techs answering' : 'After hours — emergency calls answered';
  document.querySelectorAll('[data-open-label]').forEach(function (el) { el.textContent = label; });

  // Booking form (front-end confirmation; hook up Workiz/Jobber for real dispatch)
  var form = document.querySelector('[data-booking-form]');
  var pending = document.querySelector('[data-booking-pending]');
  var done = document.querySelector('[data-booking-done]');
  if (form && pending && done) {
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      pending.hidden = true;
      done.hidden = false;
    });
    var reset = document.querySelector('[data-booking-reset]');
    if (reset) reset.addEventListener('click', function () {
      form.reset();
      done.hidden = true;
      pending.hidden = false;
    });
  }
})();
"""


def write_assets():
    os.makedirs(os.path.join(OUT, "assets"), exist_ok=True)
    with open(os.path.join(OUT, "assets", "site.css"), "w") as f:
        f.write(SITE_CSS_BASE + HOVERS.css() + "\n")
    with open(os.path.join(OUT, "assets", "site.js"), "w") as f:
        f.write(SITE_JS)


def write_seo_files(out_rels):
    urls = [DOMAIN + "/"] + [DOMAIN + "/" + r for r in sorted(out_rels) if r != "index.html"]
    body = "\n".join(
        f"  <url><loc>{html.escape(u)}</loc></url>" for u in urls
    )
    with open(os.path.join(OUT, "sitemap.xml"), "w") as f:
        f.write(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            + body + "\n</urlset>\n"
        )
    with open(os.path.join(OUT, "robots.txt"), "w") as f:
        f.write(f"User-agent: *\nAllow: /\n\nSitemap: {DOMAIN}/sitemap.xml\n")


def main():
    if "--missing" in sys.argv:
        for p in list_missing():
            print(p)
        return
    missing = [p for p in list_missing() if p.endswith(".dc.html")]
    if missing:
        raise SystemExit(
            f"{len(missing)} source page(s) missing from design-src/ — run the fetch step first:\n"
            + "\n".join(missing)
        )
    sources = [p for p in manifest_pages() if p.endswith(".dc.html")]
    out_rels = []
    for src_rel in sources:
        out_rels.append(compile_page(src_rel))
    write_assets()
    write_seo_files(out_rels)
    print(f"Built {len(out_rels)} pages into {OUT}")


if __name__ == "__main__":
    main()
