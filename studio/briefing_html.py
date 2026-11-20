from __future__ import annotations

import html
from typing import Iterable

from studio.schema import BriefingDocument, LensClaim

_BADGE_VERIFIED = (
    '<span class="badge verified">Verified citation</span>'
)
_BADGE_CONTESTED = (
    '<span class="badge contested">Contested signal</span>'
)

_STYLES = """
body { font-family: Georgia, serif; max-width: 820px; margin: 2rem auto; padding: 0 1.5rem;
  background: #fff; color: #111; line-height: 1.5; }
h1, h2 { font-family: Arial, sans-serif; }
.badge { display: inline-block; font-size: 0.75rem; font-family: Arial, sans-serif;
  padding: 0.15rem 0.45rem; border-radius: 4px; margin-right: 0.35rem; vertical-align: middle; }
.badge.verified { background: #e8f5e9; color: #1b5e20; border: 1px solid #a5d6a7; }
.badge.contested { background: #fff3e0; color: #e65100; border: 1px solid #ffcc80; }
.claim { margin: 0.5rem 0 1rem 0; }
.quote { font-size: 0.9rem; color: #444; margin-left: 1rem; border-left: 3px solid #ddd; padding-left: 0.75rem; }
ul { padding-left: 1.25rem; }
@media print { body { margin: 0; } }
"""


def _esc(text: str) -> str:
    return html.escape(text, quote=True)


def _claim_li(claim: LensClaim) -> str:
    return (
        f'<li class="claim">{_BADGE_VERIFIED}'
        f"<strong>{_esc(claim.statement)}</strong><br>"
        f"<em>{_esc(claim.paper_title)}</em>, p. {_esc(str(claim.source_page))}"
        f'<div class="quote">{_esc(claim.verbatim_quote)}</div></li>'
    )


def _lines_html(lines: Iterable[str], contested: bool = False) -> str:
    badge = _BADGE_CONTESTED if contested else ""
    items = "".join(f"<li>{badge}{_esc(line)}</li>" for line in lines if line.strip())
    return f"<ul>{items}</ul>" if items else "<p><em>None noted.</em></p>"


def render_briefing_html(doc: BriefingDocument) -> str:
    """Rebuild HTML from structured fields (screen and download share one builder)."""
    body = f"""
<h1>Solder Studio — benchmark briefing</h1>
<h2>Executive summary</h2>
<div>{_esc(doc.executive_summary).replace(chr(10), '<br>')}</div>
<h2>Findings</h2>
<div>{doc.findings_markdown}</div>
<h2>Direct contradictions</h2>
<div>{doc.contradictions_markdown}</div>
<h2>What the table failed to capture</h2>
<div>{doc.table_gaps_markdown}</div>
<h2>Assertion buckets</h2>
<div>{doc.buckets_markdown}</div>
"""
    return (
        "<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'>"
        "<title>Solder Studio briefing</title>"
        f"<style>{_STYLES}</style></head><body>{body}</body></html>"
    )


def claims_to_html_list(claims: list[LensClaim]) -> str:
    if not claims:
        return "<p><em>None.</em></p>"
    return "<ul>" + "".join(_claim_li(c) for c in claims) + "</ul>"


def markdown_findings_to_html(md: str) -> str:
    """Minimal conversion: headings and bullets produced by synthesize."""
    out = []
    for line in md.splitlines():
        if line.startswith("### "):
            out.append(f"<h3>{_esc(line[4:])}</h3>")
        elif line.startswith("- "):
            out.append(f"<li>{_esc(line[2:])}</li>")
        elif line.strip():
            out.append(f"<p>{_esc(line)}</p>")
    text = "".join(out)
    text = text.replace("<li>", '<ul><li>', 1) if "<li>" in text else text
    return text