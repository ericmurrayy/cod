# Build progress notes (working notes, delete before final PR merge)

Goal: finish the Chelmsford Overhead Door website from the Claude Design project
(3a857b2c-76df-4118-9289-aac9f662a91c, "Chelmsford Overhead Door Redesign").
User asks: finish the website; needs a MENU and BETTER MOBILE FORMATTING.

## Pipeline
1. Fetch all sources into design-src/ via DesignSync get_file (main session only —
   subagents do NOT have DesignSync). For each file: if tool result is persisted to
   a .txt file, decode JSON {path,content} and write design-src/<path>; if inline,
   Write content verbatim.
   After each fetch batch run: python3 extract_from_transcript.py (writes results from the transcript to design-src/), then python3 build.py --missing to see what remains.
2. Compile: `python3 build.py` → outputs site/ (index.html + pages/*.html + assets/).
3. Verify with headless Chromium at 375px and 1280px widths.
4. Commit + push branch claude/seo-mega-prompt-5kh3r0, open draft PR.

## Compiler rules (build.py)
- "COD Homepage v2.dc.html" → site/index.html; "pages/X.dc.html" → site/pages/X.html
- Strip <script src="./support.js"> and the trailing <script data-dc-script> block.
- Merge <helmet> children into <head>; drop <x-dc> wrapper tags.
- Props: {{ phone }} → "(978) 555-0100", {{ tel }} → "tel:+19785550100".
- {{ openLabel }} → <span data-open-label>Open Mon–Sat 7am–7pm</span> (site.js updates it live).
- <sc-if value="{{ isDesktop }}" ...> → <div class="cod-desktop"> ... </sc-if> → </div>
  <sc-if value="{{ showCallBar }}" ...> → <div class="cod-mobile"> (sticky call bar)
  Homepage booking sc-ifs: bookingPending → <div data-booking-pending>,
  bookingDone → <div data-booking-done hidden>; {{ submitBooking }} etc handled by site.js.
- style-hover="css" → class hv-N + generated .hv-N:hover{css} rules in assets/site.css.
- Links: rewrite *.dc.html → *.html; "../COD Homepage v2.dc.html" and
  "COD Homepage v2.dc.html" → ../index.html / index.html as appropriate.
- Add <link rel="canonical"> per page (https://chelmsfordoverheaddoor.com/...).
- Inject MENU: hamburger button in header (mobile), slide-down panel with site nav;
  desktop keeps inline nav (now .cod-desktop). site.js toggles panel.
- Inject <link assets/site.css> + <script assets/site.js defer> into every page.
- Generate sitemap.xml + robots.txt.

## Status
- [x] design-src/COD Homepage v2.dc.html, design-src/support.js, and
      design-src/pages/garage-door-repair-chelmsford.dc.html still needed from scratchpad? NO —
      homepage+support.js copied already; garage-door-repair-chelmsford must be fetched (was only
      in context, then agent batch M was killed — re-fetch it).
- [ ] Fetch remaining pages (see MANIFEST)
- [ ] build.py complete + site built
- [ ] browser verify mobile+desktop
- [ ] commit/push/PR
