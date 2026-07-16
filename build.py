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
import html
import json
import os
import re
import sys

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
    # Skip-link target right after the sticky header.
    body = body.replace("</header>", '</header>\n<span id="cod-main" tabindex="-1"></span>', 1)

    head = (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n"
        + head_inner + "\n"
        + helmet + "\n"
        + f'<link rel="canonical" href="{canonical}">\n'
        + '<meta name="theme-color" content="#18242e">\n'
        + f'<link rel="icon" type="image/svg+xml" href="{prefix}assets/favicon.svg">\n'
        + f'<link rel="apple-touch-icon" href="{prefix}assets/apple-touch-icon.png">\n'
        + f'<meta property="og:url" content="{canonical}">\n'
        + '<meta property="og:site_name" content="Chelmsford Overhead Door">\n'
        + f'<meta property="og:image" content="{DOMAIN}/assets/og-image.png">\n'
        + '<meta property="og:image:width" content="1200">\n'
        + '<meta property="og:image:height" content="630">\n'
        + '<meta name="twitter:card" content="summary_large_image">\n'
        + breadcrumb_jsonld(body, out_rel)
        + f'<link rel="stylesheet" href="{prefix}assets/site.css">\n'
        + f'<script src="{prefix}assets/site.js" defer></script>\n'
        + "</head>\n<body>\n"
        + '<a class="cod-skip" href="#cod-main">Skip to content</a>\n'
    )

    out_file = os.path.join(OUT, out_rel)
    os.makedirs(os.path.dirname(out_file), exist_ok=True)
    with open(out_file, "w") as f:
        f.write(head + body.strip() + "\n</body>\n</html>\n")
    return out_rel


def breadcrumb_jsonld(body, out_rel):
    """Emit BreadcrumbList JSON-LD parsed from the page's visible breadcrumb
    trail (the hero's 'Home / Services / …' line). Empty for pages without one."""
    m = re.search(r"<p[^>]*>(<a [^>]*>Home</a>.*?)</p>", body, re.S)
    if not m:
        return ""
    trail = m.group(1)
    items = []
    for a in re.finditer(r'<a href="([^"]+)"[^>]*>([^<]+)</a>', trail):
        href, label = a.group(1), a.group(2).strip()
        # Resolve the page-relative href against the site root.
        base = os.path.dirname(out_rel)
        path = os.path.normpath(os.path.join(base, href)).replace(os.sep, "/")
        url = DOMAIN + "/" + ("" if path == "index.html" else path)
        items.append((label, url))
    tail = re.findall(r"<span[^>]*>([^<]+)</span>", trail)
    leaf = next((t.strip() for t in reversed(tail) if t.strip() != "/"), None)
    if leaf:
        items.append((leaf, None))
    if len(items) < 2:
        return ""
    entries = []
    for i, (label, url) in enumerate(items, 1):
        entry = {"@type": "ListItem", "position": i, "name": label}
        if url:
            entry["item"] = url
        entries.append(entry)
    data = {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": entries}
    return '<script type="application/ld+json">' + json.dumps(data, ensure_ascii=False) + "</script>\n"


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

/* Accessibility: skip link + visible keyboard focus */
.cod-skip {
  position: absolute; left: -9999px; top: 0; z-index: 100;
  background: #ffaa1d; color: #18242e; text-decoration: none;
  font-family: 'Barlow Condensed', 'Arial Narrow', sans-serif; font-weight: 700;
  text-transform: uppercase; letter-spacing: .05em; font-size: 16px; padding: 10px 18px;
}
.cod-skip:focus { left: 0; }
a:focus-visible, button:focus-visible, input:focus-visible, textarea:focus-visible {
  outline: 2px solid #ffaa1d; outline-offset: 2px;
}

/* Current page highlighted in navs (set by site.js) */
.cod-menu a[aria-current="page"],
.cod-desktop nav a[aria-current="page"] { color: #ffaa1d !important; }

/* FAQ accordion: rotate the + marker when open */
details > summary > span:last-child { transition: transform .18s ease; }
details[open] > summary > span:last-child { transform: rotate(45deg); }

@media (prefers-reduced-motion: no-preference) {
  html { scroll-behavior: smooth; }
}

/* Paint the canvas dark so overscroll past the footer (or above the header)
   never flashes white against the dark chrome. Body keeps the light ground. */
html { background: #101a21; overscroll-behavior-y: none; }
/* Belt-and-suspenders for iOS rubber-band: bleed the footer's color far past
   its box so any viewport area revealed below the document stays dark. */
footer { box-shadow: 0 80vh 0 80vh #101a21; }

/* Photo placeholders: a touch of depth + amber threshold line */
.cod-photo { position: relative; overflow: hidden; }
.cod-photo::before {
  content: ""; position: absolute; inset: 0;
  background: linear-gradient(120deg, rgba(255,255,255,.05) 0%, transparent 45%);
}
.cod-photo::after {
  content: ""; position: absolute; left: 0; right: 0; bottom: 0; height: 5px;
  background: #ffaa1d; opacity: .85;
}

/* Generated :hover rules (compiled from style-hover attributes) */
"""

SITE_JS = """// Generated by build.py — menu toggle, open-hours label, booking form.
(function () {
  'use strict';

  // Mobile menu
  var btn = document.getElementById('cod-menu-btn');
  var menu = document.getElementById('cod-menu');
  function setMenu(open) {
    btn.setAttribute('aria-expanded', String(open));
    btn.setAttribute('aria-label', open ? 'Close menu' : 'Open menu');
    menu.hidden = !open;
  }
  if (btn && menu) {
    btn.addEventListener('click', function () {
      setMenu(btn.getAttribute('aria-expanded') !== 'true');
    });
    menu.addEventListener('click', function (e) {
      if (e.target.closest('a')) setMenu(false);
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && !menu.hidden) { setMenu(false); btn.focus(); }
    });
    document.addEventListener('click', function (e) {
      if (!menu.hidden && !e.target.closest('header')) setMenu(false);
    });
  }

  // Mark the current page in the menu and desktop nav
  var here = location.pathname.replace(/\\/+$/, '');
  document.querySelectorAll('#cod-menu a, .cod-desktop nav a').forEach(function (a) {
    var target = new URL(a.getAttribute('href'), location.href).pathname.replace(/\\/+$/, '');
    if (target === here) a.setAttribute('aria-current', 'page');
  });


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


FAVICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
<rect width="64" height="64" fill="#18242e"/>
<rect x="7" y="7" width="50" height="50" fill="none" stroke="#ffaa1d" stroke-width="6"/>
<rect x="18" y="21" width="28" height="6" fill="#ffaa1d"/>
<rect x="18" y="32" width="28" height="6" fill="#ffaa1d"/>
<rect x="18" y="43" width="28" height="6" fill="#ffaa1d"/>
</svg>
"""


def write_icons():
    """favicon.svg (brand mark), apple-touch-icon.png, og-image.png."""
    assets = os.path.join(OUT, "assets")
    os.makedirs(assets, exist_ok=True)
    with open(os.path.join(assets, "favicon.svg"), "w") as f:
        f.write(FAVICON_SVG)

    from PIL import Image, ImageDraw, ImageFont

    dark, amber, panel = (24, 36, 46), (255, 170, 29), (44, 63, 80)

    def mark(draw, x, y, s):
        """The square-and-bars logo at box size s."""
        bw = max(2, s // 10)
        draw.rectangle([x, y, x + s, y + s], outline=amber, width=bw)
        bar_w, bar_h = int(s * 0.44), max(2, int(s * 0.09))
        bx = x + (s - bar_w) // 2
        for i in range(3):
            by = y + int(s * (0.30 + 0.17 * i))
            draw.rectangle([bx, by, bx + bar_w, by + bar_h], fill=amber)

    # apple-touch-icon 180x180
    img = Image.new("RGB", (180, 180), dark)
    d = ImageDraw.Draw(img)
    mark(d, 30, 30, 120)
    img.save(os.path.join(assets, "apple-touch-icon.png"))

    # og-image 1200x630: dark card with panel lines, mark + wordmark + tagline
    W, H = 1200, 630
    img = Image.new("RGB", (W, H), dark)
    d = ImageDraw.Draw(img)
    for y in range(0, H, 105):  # horizontal garage-door panel seams
        d.line([(0, y), (W, y)], fill=panel, width=3)
        d.line([(0, y + 3), (W, y + 3)], fill=(255, 255, 255, 12), width=1)
    font_dir = "/usr/share/fonts/truetype/liberation"
    bold = ImageFont.truetype(os.path.join(font_dir, "LiberationSans-Bold.ttf"), 92)
    small = ImageFont.truetype(os.path.join(font_dir, "LiberationSans-Bold.ttf"), 36)
    mark(d, 90, 150, 150)
    d.text((290, 160), "CHELMSFORD", font=bold, fill=(255, 255, 255))
    d.text((290, 262), "OVERHEAD DOOR", font=bold, fill=amber)
    d.text((92, 420), "SAME-DAY GARAGE DOOR SERVICE", font=small, fill=(205, 215, 221))
    d.text((92, 472), "CHELMSFORD, MA · (978) 555-0100", font=small, fill=(159, 176, 186))
    d.rectangle([0, H - 14, W, H], fill=amber)
    img.save(os.path.join(assets, "og-image.png"))


def write_404():
    """Standalone 404 page in the site's visual language."""
    menu = menu_html("404.html")
    btn, panel = menu.split('<nav id="cod-menu"', 1)
    panel = '<nav id="cod-menu"' + panel
    links = "\n        ".join(
        f'<a href="{t}" style="color:#b7c3cb;">{l}</a>' for l, t in MENU_LINKS
    )
    doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Page Not Found | Chelmsford Overhead Door</title>
<meta name="robots" content="noindex">
<meta name="theme-color" content="#18242e">
<link rel="icon" type="image/svg+xml" href="assets/favicon.svg">
<link rel="apple-touch-icon" href="assets/apple-touch-icon.png">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@600;700;800&family=Archivo:wght@400;500;600;700&family=IBM+Plex+Mono:wght@500;600&display=swap" rel="stylesheet">
<style>
  html, body {{ margin: 0; padding: 0; background: #18242e; }}
  body {{ font-family: 'Archivo', system-ui, sans-serif; color: #e9eef1; -webkit-font-smoothing: antialiased; }}
  * {{ box-sizing: border-box; }}
  a {{ color: #d98a00; }}
</style>
<link rel="stylesheet" href="assets/site.css">
<script src="assets/site.js" defer></script>
</head>
<body>
<header style="position: sticky; top: 0; z-index: 50; background: #18242e; border-bottom: 1px solid #2c3f50;">
  <div style="max-width: 1120px; margin: 0 auto; padding: 10px 16px; display: flex; align-items: center; justify-content: space-between; gap: 12px;">
    <a href="index.html" style="display: flex; align-items: center; gap: 10px; text-decoration: none; min-width: 0;">
      <span aria-hidden="true" style="display: flex; flex-direction: column; gap: 3px; flex: none;">
        <i style="display: block; width: 26px; height: 5px; background: #ffaa1d;"></i>
        <i style="display: block; width: 26px; height: 5px; background: #ffaa1d;"></i>
        <i style="display: block; width: 26px; height: 5px; background: #ffaa1d;"></i>
      </span>
      <span style="font-family: 'Barlow Condensed', 'Arial Narrow', sans-serif; font-weight: 800; text-transform: uppercase; color: #fff; line-height: 0.95; font-size: 17px; letter-spacing: 0.03em;">Chelmsford<br>Overhead Door</span>
    </a>
    <a href="{TEL}" style="flex: none; display: flex; flex-direction: column; align-items: center; text-decoration: none; background: #ffaa1d; color: #18242e; padding: 8px 16px; line-height: 1.1;">
      <span style="font-family: 'IBM Plex Mono', monospace; font-size: 10px; font-weight: 600; letter-spacing: 0.16em; text-transform: uppercase;">Call now</span>
      <span style="font-family: 'Barlow Condensed', sans-serif; font-weight: 800; font-size: 19px; letter-spacing: 0.03em;">{PHONE}</span>
    </a>
{btn}
  </div>
{panel}
</header>
<main style="min-height: 70vh; display: flex; align-items: center; background-image: repeating-linear-gradient(to bottom, transparent 0px, transparent 71px, #2c3f50 71px, #2c3f50 73px, rgba(255,255,255,0.05) 73px, rgba(255,255,255,0.05) 74px, transparent 74px);">
  <div style="max-width: 720px; margin: 0 auto; padding: 64px 20px; text-align: center;">
    <p style="margin: 0 0 14px; font-family: 'IBM Plex Mono', monospace; font-size: 12px; font-weight: 600; letter-spacing: 0.14em; text-transform: uppercase; color: #ffaa1d;">Error 404</p>
    <h1 style="margin: 0; font-family: 'Barlow Condensed', 'Arial Narrow', sans-serif; font-weight: 800; text-transform: uppercase; line-height: 0.96; color: #fff; font-size: clamp(44px, 9vw, 76px);">This page is<br><span style="color: #ffaa1d;">off its track.</span></h1>
    <p style="margin: 20px auto 0; font-size: 17px; line-height: 1.55; color: #cdd7dd; max-width: 44ch;">The page you're looking for doesn't exist or has moved. The doors below all open just fine.</p>
    <nav aria-label="Helpful links" style="display: flex; flex-wrap: wrap; gap: 8px 22px; justify-content: center; margin-top: 26px; font-size: 15px;">
        {links}
    </nav>
    <div style="display: flex; justify-content: center; margin-top: 32px;">
      <a href="{TEL}" style="display: inline-flex; flex-direction: column; align-items: center; text-decoration: none; background: #ffaa1d; color: #18242e; padding: 14px 28px; line-height: 1.1;">
        <span style="font-family: 'IBM Plex Mono', monospace; font-size: 11px; font-weight: 600; letter-spacing: 0.16em; text-transform: uppercase;">Tap to call — we answer</span>
        <span style="font-family: 'Barlow Condensed', sans-serif; font-weight: 800; font-size: 26px; letter-spacing: 0.02em;">{PHONE}</span>
      </a>
    </div>
  </div>
</main>
</body>
</html>
"""
    with open(os.path.join(OUT, "404.html"), "w") as f:
        f.write(doc)


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
    write_icons()
    write_404()
    write_seo_files(out_rels)
    print(f"Built {len(out_rels)} pages into {OUT}")


if __name__ == "__main__":
    main()
