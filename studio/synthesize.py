from __future__ import annotations

import html
from dataclasses import dataclass
from typing import Any, Callable, Optional

from studio.briefing_html import (
    _BADGE_CONTESTED,
    claims_to_html_list,
    markdown_findings_to_html,
    render_briefing_html,
)
from studio.codex_backend import complete_structured
from studio.quote_gate import row_passes_quote_gate
from studio.schema import (
    BriefingDocument,
    ImcChemistLensOutput,
    LensClaim,
    MetallurgistLensOutput,
    ReliabilitySkepticLensOutput,
    SolderRow,
)

MIN_QUOTED_ROWS = 3

BENCHMARK_QUESTION = (
    "How do minor alloying additions (Bi, Ni, Sb, or nanoparticles) suppress "
    "Cu–Sn intermetallic growth and brittle interfacial fracture in Sn-Bi and "
    "doped SAC305 during thermal aging?"
)

LENS_PHYSICAL = "Physical Metallurgist"
LENS_IMC = "Interface and IMC Chemist"
LENS_SKEPTIC = "Reliability Skeptic"


def quoted_rows(rows: list[SolderRow]) -> list[SolderRow]:
    return [r for r in rows if r.verbatim_quote and row_passes_quote_gate(r)]


def stop_message_if_insufficient(rows: list[SolderRow]) -> Optional[str]:
    q = quoted_rows(rows)
    n = len(q)
    if n >= MIN_QUOTED_ROWS:
        return None
    missing = MIN_QUOTED_ROWS - n
    return (
        f"Synthesis needs at least {MIN_QUOTED_ROWS} quote-verified rows; "
        f"you have {n}. Add {missing} more verifiable row(s) from local PDF audit. "
        "No model call was made."
    )


def _paper_title(paper_titles: dict[int, str] | None, row: SolderRow) -> str:
    titles = paper_titles or {}
    if row.paper_id is not None:
        return titles.get(row.paper_id, "Unknown paper")
    return "Unknown paper"


def rows_to_prompt_block(
    rows: list[SolderRow],
    paper_titles: dict[int, str] | None = None,
) -> str:
    lines: list[str] = []
    for i, r in enumerate(rows, 1):
        title = _paper_title(paper_titles, r)
        parts = [
            f"Row {i}:",
            f"  paper_title: {title!r}",
            f"  source_page: {r.source_page}",
            f'  verbatim_quote: "{r.verbatim_quote}"',
            f"  alloy: {r.alloy!r}",
            f"  addition_name: {r.addition_name!r}, addition_weight_percent: {r.addition_weight_percent}",
            f"  substrate: {r.substrate!r}, reflow_temp_c: {r.reflow_temp_c}",
            f"  aging_condition: {r.aging_condition!r}, aging_type: {r.aging_type.value}",
            f"  imc_phase: {r.imc_phase.value}, imc_thickness_um: {r.imc_thickness_um}",
            f"  shear_value: {r.shear_value}, shear_unit: {r.shear_unit.value}",
            f"  uts_mpa: {r.uts_mpa}, elongation_percent: {r.elongation_percent}",
            f"  fracture_mode: {r.fracture_mode!r}, sample_size: {r.sample_size!r}",
        ]
        lines.append("\n".join(parts))
    return "\n\n".join(lines)


def _lens_system(lens_name: str, extra: str) -> str:
    return f"""You are the {lens_name} lens for a metallurgy briefing.
Benchmark: {BENCHMARK_QUESTION}

You see ONLY the quote-verified rows supplied. Each claim MUST include paper_title, source_page,
and verbatim_quote copied exactly from a row. Omit any claim you cannot tie to a row.

{extra}
"""


PHYSICAL_EXTRA = (
    "Focus on bulk solder microstructure, phase evolution, and mechanical trends tied to aging."
)
IMC_EXTRA = (
    "Focus on interface reactions, IMC phase identity, thickness trends, and chemistry."
)
SKEPTIC_EXTRA = (
    "Stress sample size, test conditions, and gaps. Fill safe_to_assert, say_with_caveat, "
    "and insufficient_data buckets. safe_to_assert and say_with_caveat entries need full citations."
)


def build_synthesis_user_prompt(
    rows: list[SolderRow],
    paper_titles: dict[int, str] | None = None,
) -> str:
    return (
        "Quote-verified rows only:\n\n"
        + rows_to_prompt_block(rows, paper_titles)
        + "\n\nReturn structured claims only where each cites a row."
    )


CompleteFn = Callable[..., Any]


@dataclass
class LensBundle:
    physical: MetallurgistLensOutput
    imc: ImcChemistLensOutput
    skeptic: ReliabilitySkepticLensOutput


def _call_lens(
    model_cls: type,
    lens_name: str,
    extra: str,
    rows: list[SolderRow],
    paper_titles: dict[int, str] | None,
    complete: CompleteFn,
    on_status: Callable[[str], None] | None = None,
) -> Any:
    instructions = _lens_system(lens_name, extra)
    user = build_synthesis_user_prompt(rows, paper_titles)
    parsed = complete(model_cls, instructions, user, on_status=on_status)
    if not isinstance(parsed, model_cls):
        raise RuntimeError(f"{lens_name} returned no parsed output.")
    return parsed


def run_lens_calls(
    rows: list[SolderRow],
    paper_titles: dict[int, str] | None = None,
    complete: CompleteFn | None = None,
    on_status: Callable[[str], None] | None = None,
) -> LensBundle:
    complete_fn = complete or complete_structured
    physical = _call_lens(
        MetallurgistLensOutput,
        LENS_PHYSICAL,
        PHYSICAL_EXTRA,
        rows,
        paper_titles,
        complete_fn,
        on_status=on_status,
    )
    imc = _call_lens(
        ImcChemistLensOutput,
        LENS_IMC,
        IMC_EXTRA,
        rows,
        paper_titles,
        complete_fn,
        on_status=on_status,
    )
    skeptic = _call_lens(
        ReliabilitySkepticLensOutput,
        LENS_SKEPTIC,
        SKEPTIC_EXTRA,
        rows,
        paper_titles,
        complete_fn,
        on_status=on_status,
    )
    return LensBundle(physical=physical, imc=imc, skeptic=skeptic)


def _contradictions_across_rows(
    rows: list[SolderRow],
    paper_titles: dict[int, str] | None,
) -> list[str]:
    notes: list[str] = []
    for i, a in enumerate(rows):
        for b in rows[i + 1 :]:
            if a.imc_thickness_um is None or b.imc_thickness_um is None:
                continue
            if a.shear_value is None or b.shear_value is None:
                continue
            if a.shear_unit != b.shear_unit and a.shear_unit.value != b.shear_unit.value:
                continue
            spread = abs(float(a.shear_value) - float(b.shear_value))
            if spread < max(5.0, 0.2 * max(float(a.shear_value), float(b.shear_value))):
                continue
            ta = _paper_title(paper_titles, a)
            tb = _paper_title(paper_titles, b)
            notes.append(
                f"Shear reports diverge: {ta} p.{a.source_page} vs {tb} p.{b.source_page} "
                f"({a.shear_value} {a.shear_unit.value} vs {b.shear_value} {b.shear_unit.value})."
            )
    return notes


def _executive_summary(bundle: LensBundle) -> str:
    settled = (
        bundle.physical.settled_observations
        + bundle.imc.settled_observations
    )
    contested = (
        bundle.physical.contested_observations
        + bundle.imc.contested_observations
        + [c.statement for c in bundle.skeptic.claims]
    )
    lines = ["Settled signals:"]
    lines.extend(f"- {s}" for s in settled[:8] if s.strip())
    if not any(s.strip() for s in settled):
        lines.append("- None clearly settled across lenses.")
    lines.append("")
    lines.append("Contested or fragile signals:")
    lines.extend(f"- {s}" for s in contested[:8] if s.strip())
    if not any(s.strip() for s in contested):
        lines.append("- No explicit contest noted.")
    return "\n".join(lines)


def _findings_markdown(bundle: LensBundle) -> str:
    sections: list[str] = []

    def section(title: str, claims: list[LensClaim], contested: list[str]) -> None:
        sections.append(f"### {title}")
        for c in claims:
            sections.append(
                f"- Supports/challenges: {c.statement} "
                f"({c.paper_title}, p.{c.source_page})"
            )
        for line in contested:
            sections.append(f"- Contested signal: {line}")
        if not claims and not contested:
            sections.append("- No cited findings returned.")

    section(LENS_PHYSICAL, bundle.physical.claims, bundle.physical.contested_observations)
    section(LENS_IMC, bundle.imc.claims, bundle.imc.contested_observations)
    section(LENS_SKEPTIC, bundle.skeptic.claims, [])
    return "\n".join(sections)


def _gaps_markdown(bundle: LensBundle) -> str:
    gaps = bundle.physical.uncaptured_by_table + bundle.imc.uncaptured_by_table
    if not gaps:
        return "No table gaps noted by the metallurgy or IMC lenses."
    return "\n".join(f"- {g}" for g in gaps)


def _buckets_markdown(skeptic: ReliabilitySkepticLensOutput) -> str:
    lines = ["### Safe to assert"]
    for c in skeptic.safe_to_assert:
        lines.append(f"- {c.statement} ({c.paper_title}, p.{c.source_page})")
    if not skeptic.safe_to_assert:
        lines.append("- None.")
    lines.append("")
    lines.append("### Say with caveat")
    for c in skeptic.say_with_caveat:
        lines.append(f"- {c.statement} ({c.paper_title}, p.{c.source_page})")
    if not skeptic.say_with_caveat:
        lines.append("- None.")
    lines.append("")
    lines.append("### Insufficient data")
    for item in skeptic.insufficient_data:
        lines.append(f"- {item}")
    if not skeptic.insufficient_data:
        lines.append("- None flagged.")
    return "\n".join(lines)


def assemble_briefing(
    bundle: LensBundle,
    rows: list[SolderRow],
    paper_titles: dict[int, str] | None = None,
) -> BriefingDocument:
    executive = _executive_summary(bundle)
    findings_md = _findings_markdown(bundle)
    contradictions = _contradictions_across_rows(rows, paper_titles)
    contradictions_md = (
        "\n".join(f"- {n}" for n in contradictions)
        if contradictions
        else "No direct numeric contradictions across cited rows."
    )
    gaps_md = _gaps_markdown(bundle)
    buckets_md = _buckets_markdown(bundle.skeptic)

    findings_html = markdown_findings_to_html(findings_md)
    contradictions_html = (
        "<ul>"
        + "".join(
            f"<li>{_BADGE_CONTESTED}{html.escape(c, quote=True)}</li>"
            for c in contradictions
        )
        + "</ul>"
        if contradictions
        else f"<p>{html.escape(contradictions_md, quote=True)}</p>"
    )
    gaps_html = markdown_findings_to_html(
        "\n".join(f"- {g}" for g in (bundle.physical.uncaptured_by_table + bundle.imc.uncaptured_by_table))
        or "- None."
    )
    buckets_html = (
        "<h3>Safe to assert</h3>"
        + claims_to_html_list(bundle.skeptic.safe_to_assert)
        + "<h3>Say with caveat</h3>"
        + claims_to_html_list(bundle.skeptic.say_with_caveat)
        + "<h3>Insufficient data</h3>"
        + markdown_findings_to_html(
            "\n".join(f"- {x}" for x in bundle.skeptic.insufficient_data) or "- None."
        )
    )

    doc = BriefingDocument(
        executive_summary=executive,
        findings_markdown=findings_md,
        contradictions_markdown=contradictions_md,
        table_gaps_markdown=gaps_md,
        buckets_markdown=buckets_md,
        html="",
    )
    # Screen HTML fragments stored in markdown fields for streamlit; full doc HTML for download.
    doc.html = render_briefing_html(
        BriefingDocument(
            executive_summary=executive,
            findings_markdown=findings_html,
            contradictions_markdown=contradictions_html,
            table_gaps_markdown=gaps_html,
            buckets_markdown=buckets_html,
            html="",
        )
    )
    return doc


def run_synthesis(
    rows: list[SolderRow],
    paper_titles: dict[int, str] | None = None,
    complete: CompleteFn | None = None,
    on_status: Callable[[str], None] | None = None,
) -> tuple[Optional[BriefingDocument], Optional[str], list[SolderRow]]:
    """
    Returns (briefing, stop_message, rows_used).
    If stop_message is set, briefing is None and Codex is not called.
    """
    usable = quoted_rows(rows)
    stop = stop_message_if_insufficient(rows)
    if stop:
        return None, stop, usable

    bundle = run_lens_calls(
        usable, paper_titles, complete=complete, on_status=on_status
    )
    briefing = assemble_briefing(bundle, usable, paper_titles)
    return briefing, None, usable