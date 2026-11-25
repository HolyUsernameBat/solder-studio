# Solder Studio: Architectural Design Rationale & Research Foundations

This document provides a comprehensive technical breakdown of the architectural design decisions, research foundations, data-verification gates, and multi-lens synthesis protocols built into **Solder Studio** (as captured in repository commit `a368444` and the system specification).

Designed specifically for metallurgy and adjacent materials science research, Solder Studio bridges the gap between high-level literature discovery and quantitative experimental auditing. Whether you choose to deploy Solder Studio as a standalone workspace, extend its Streamlit and CLI capabilities, or extract its core patterns into your own custom Codex-driven tools, this reference details the specific technical rationale behind every layer of the system.

---

## 1. Executive Architectural Thesis: Beyond Stateless RAG

Standard AI research assistants typically rely on basic Retrieval-Augmented Generation (RAG)—chunking uploaded PDF documents into a vector database and re-querying raw text fragments on every chat prompt. In physical sciences like metallurgy, this approach fails due to three fundamental flaws:

1. **Loss of Context & Memory**: Basic RAG handles each session as a stateless lookup, forcing researchers to rediscover literature from scratch rather than accumulating structured domain knowledge over time.
2. **Table & Numerical Corruption**: PDF parsers frequently scramble multi-column tables, leading standard LLMs to confuse experimental test results with background literature review citations or mix incompatible units (such as force in Newtons vs. stress in MPa).
3. **Plausible Hallucination ("Reviewer-Pleasing Consensus")**: General-purpose chatbots tend to smooth over scientific contradictions between studies, synthesizing a superficial consensus rather than highlighting conflicting experimental conditions or missing sample variables.

Solder Studio overcomes these limitations by combining a **dual-layer local architecture** (a quantitative SQLite database paired with structured Markdown research cards) with **programmatic data-verification gates** and a **multi-perspective synthesis engine**.

```
[ Unauthenticated OpenAlex Search / Local PDF Drops ]
                         │
                         ▼
           [ %PDF Magic-Byte Validation ]
                         │
                         ▼
        [ Project Brief & Active Question Scope ]
                         │
                         ▼
   [ Structured Research Audit & Triage Cards (Tab 1) ]
                         │
                         ▼
   [ Dual Verification Gates: Source-Section & Verbatim Quote ]
                         │
                         ▼
     [ Quantitative SQLite Persistence (solder_lit.db) ]
                         │
                         ▼
  ┌──────────────────────┴──────────────────────┐
  ▼                                             ▼
[ Interactive Unit-Safe Plotter (Tab 2) ]   [ 3-Lens STORM Synthesis (Tab 3) ]
```

---

## 2. Theoretical Foundations & Key Research Influences

Solder Studio’s architecture synthesizes concepts from leading AI research paradigms, scientific search infrastructure, and local execution models.

### 2.1 Andrej Karpathy’s "LLM Wiki" Pattern
* **Concept**: Computer scientist Andrej Karpathy introduced the **LLM Wiki workflow**, which treats personal research management like software engineering: Markdown files serve as the codebase, while the coding agent (such as OpenAI Codex CLI) acts as the compiler.
* **Implementation in Solder Studio**: Solder Studio separates immutable raw inputs (`pdfs/` directory) from agent-compiled structured knowledge. Rather than treating PDFs as ephemeral prompt inputs, the system parses each document once against an active research hypothesis, storing per-paper research audit cards, normalized metric rows, and extraction metadata locally in SQLite (`solder_lit.db`).

### 2.2 Stanford’s STORM Multi-Perspective Synthesis
* **Concept**: The **STORM** (Synthesis of Topic Outlines through Retrieval and Multi-perspective conversation) framework developed at Stanford University replaces single-prompt summaries with multi-agent expert debates.
* **Source Reference**: [Stanford STORM Framework & Multi-Perspective Audit](https://www.youtube.com/watch?v=Tj3018n5MVg).
* **Implementation in Solder Studio**: Solder Studio adapts STORM into a 3-lens domain audit (*Physical Metallurgist*, *Interface & Mechanisms Specialist*, and *Reliability Skeptic*). Instead of generating ungrounded roleplay prose, each lens is strictly constrained to cite primary quantitative rows extracted into SQLite.

### 2.3 OpenAlex Scholarly Catalog & Open-Access Infrastructure
* **Concept**: OpenAlex is a free, non-profit index tracking over 480 million scholarly works, offering an open API with direct links to candidate open-access PDFs, citation counts, and inverted abstracts.
* **Source Reference**: [OpenAlex Scholarly Index](https://openalex.org) | [OpenAlex API Documentation](https://api.openalex.org).
* **Implementation in Solder Studio**: Solder Studio uses unauthenticated HTTP queries to search OpenAlex without requiring paid platform API keys. It executes an automated candidate URL resolution protocol to harvest open-access PDFs directly.

### 2.4 Zero-Platform-API-Key Infrastructure via Codex CLI
* **Concept**: Scientific AI tools often create friction by requiring developer account setups, credit card billing, and OpenAI Platform API keys.
* **Implementation in Solder Studio**: Solder Studio routes all LLM work through the local OpenAI Codex CLI (`codex exec -m <slug> --output-schema`), leveraging the operator's existing ChatGPT subscription. It requires zero platform API keys, zero `.env` configuration files, and zero third-party cloud hosting.

---

## 3. System Architecture & Ingestion Engine

### 3.1 Project Brief & Multi-Question Scoping
A core failure of rigid research scripts is forcing all queries into fixed, hardcoded columns. Solder Studio introduces a **Project Brief Workspace** anchored in SQLite (`projects` and `research_questions` tables):

* **Project Scope**: Defines the shared paper library and local PDF directory (`pdfs/`) for a domain (e.g., *SAC bismuth joints*).
* **Multi-Question Flexibility**: Under a single project, researchers can define multiple hypotheses, each with custom screening criteria and target metrics (e.g., IMC thickness, shear strength, UTS, elongation).
* **Per-Question Persistence**: Switching the active question dynamically updates triage audits, extraction prompts, and synthesis outputs without duplicating or re-downloading source PDFs.

### 3.2 Candidate PDF Harvesting & %PDF Validation Gate
When searching OpenAlex, article landing pages frequently resolve to publisher HTML paywalls (e.g., Elsevier, Springer, IEEE) that block automated scraping. Solder Studio resolves this via a deterministic 4-stage candidate URL fetch protocol:

1. Inspects `locations[].pdf_url` across primary and secondary open-access locations.
2. Checks `open_access.oa_url` on the OpenAlex work object.
3. Tests direct arXiv PDF paths (`https://arxiv.org/pdf/{id}`) if an arXiv ID is present.
4. Tests direct PubMed Central PDF paths (`https://www.ncbi.nlm.nih.gov/pmc/articles/{PMCID}/pdf/`) if a PMC ID is present.

**The %PDF Magic-Byte Gate**: A downloaded file is retained only if its initial 4 bytes match `%PDF`. If an endpoint returns an HTML paywalled page or landing page, the paper is categorized as `abstract-only`. Abstract-only papers remain visible for literature triage but are strictly blocked from quantitative measurement extraction until a verified PDF is added.

### 3.3 Structured Research Audit Cards
Rather than displaying opaque 1–5 relevance scores, Solder Studio parses full-text PDFs to generate a structured JSON **Research Audit Card** for each paper:

| Audit Card Dimension | Technical Purpose & Scope |
| :--- | :--- |
| `triage_tier` | Classifies paper into *Must Read (Deep Dive)*, *Data Source Only*, or *Low Priority*. |
| `relevance_score` & Rationale | 1–5 score with a 2-sentence rationale explicitly connecting the paper to the active `research_question`. |
| `core_claim_and_mechanism` | Summarizes the underlying physical mechanism or primary claim established by the authors. |
| `system_and_conditions` | Documents alloy compositions, reflow temperatures, aging times, and testing conditions. |
| `key_findings` | Bulleted breakdown of verified experimental outcomes. |
| `limitations_and_caveats` | Identifies experimental gaps, missing sample size data, or unstated variables. |

---

## 4. Anti-Hallucination & Data-Verification Gates

To guarantee that extracted data tables remain 100% faithful to source literature, Solder Studio enforces two programmatic gates before any quantitative row is committed to SQLite.

```
[ Raw PDF Text / Table Extraction ]
                │
                ▼
  [ Gate 1: Source-Section Filter ] ──► (Rejects "Introduction" / Literature Review Citations)
                │
                ▼
   [ Gate 2: Verbatim Quote Gate ]  ──► (Verifies numeric values & ± error ranges match verbatim)
                │
                ▼
  [ Unit Normalization & Storage ]  ──► (Separates MPa, N, and gf to prevent mixed-unit plotting)
```

### 4.1 Primary Data Isolation Gate (Blocking Literature Review Citations)
A critical flaw in generic PDF extractions occurs when an LLM reads a paper's *Introduction* section and extracts background literature citations (e.g., capturing *"Liu et al.13 reported an IMC thickness of 4.2 μm..."*) as if it were the current paper's experimental result.

* **Rule**: Solder Studio inspects the `source_section` metadata. Any row originating from an `Introduction` section or background review text is programmatically rejected. Only primary data from `Results`, `Tables`, `Figures`, or `Abstracts` is saved.

### 4.2 Verbatim Quote Verification Gate
* **Rule**: For every extracted measurement row, the exact numeric value (accounting for whitespace normalization and `±` error ranges, such as matching `42.3` within `"42.3 ± 3.1"`) must exist inside the captured `verbatim_quote`.
* **Null Rejection**: Any row containing a `NULL` or missing `metric_value` is rejected, eliminating blank figure-caption artifacts.

### 4.3 Strict Unit Separation (MPa vs. Newtons vs. gf)
In ball shear testing, results are variously reported as stress (MPa), force (N), or grams-force (gf) depending on pad dimensions. 
* **Database Field**: Solder Studio stores `metric_value` alongside a normalized `metric_unit` string.
* **Plotter Guardrail**: On Tab 2 (Interactive Measurement Explorer), scatter plots enforce strict single-unit axes. Stress (MPa) and force (N) are never plotted on the same axis, preventing invalid physical comparisons.

---

## 5. Multi-Lens Synthesis Engine (STORM Adaptation)

Tab 3 executes a 3-phase multi-perspective synthesis designed specifically for physical metallurgy:

1. **Physical Metallurgist**: Evaluates phase diagrams, solid-solution kinetics, equilibrium phases, and grain-boundary segregation.
2. **Interface & Mechanisms Specialist**: Dissects intermetallic compound (IMC) growth kinetics (Cu6Sn5 vs. Cu3Sn), Kirkendall void formation, and interfacial diffusion.
3. **Reliability Skeptic**: Critiques experimental sample sizes, isothermal aging vs. thermal cycling gaps, and brittle fracture modes.

### 5.1 The 3-Row Circuit Breaker
Synthesis is explicitly forbidden from running on ungrounded roleplay prompts. If fewer than **3 quote-verified SQLite rows** exist for the active research question, Tab 3 halts execution, displays a data-gap warning, and outlines what experimental data is missing.

### 5.2 Mandatory Citation Schema
Every claim generated across all three synthesis lenses must explicitly cite its primary source using the format: `(Paper Title, Page Number, Verbatim Quote)`.

---

## 6. Security, Distribution & Handoff Integration

### 6.1 Mitigation of the "Lethal Trifecta" Vulnerability
Security researcher Simon Willison identified the **Lethal Trifecta** in autonomous agents: combining (1) private local files, (2) untrusted external web inputs, and (3) automated exfiltration tools.

Solder Studio neutralizes this vulnerability through strict isolation:
* External web content (OpenAlex metadata) is sanitized and restricted to search ingestion.
* Local files and SQLite databases remain air-gapped on disk.
* The system contains no external communication or email exfiltration tools.

### 6.2 Zero-Setup Distribution via Astral `uv`
Solder Studio eliminates complex Python virtual environment setup via a smart Windows batch launcher (`Start_Research_Studio.bat`):

```bat
@echo off
where uv >nul 2>nul
if %ERRORLEVEL% equ 0 (
    uv run streamlit run solder_studio.py
) else if exist "%USERPROFILE%\.local\bin\uv.exe" (
    "%USERPROFILE%\.local\bin\uv.exe" run streamlit run solder_studio.py
) else (
    echo Installing uv package runner...
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    "%USERPROFILE%\.local\bin\uv.exe" run streamlit run solder_studio.py
)
```

### 6.3 Handoff Summary & Integration Options

If you choose to extend or adapt Solder Studio alongside your own Codex tools, consider these key architectural options:

1. **As a Standalone Workspace**: Deploy `Solder Studio` as-is for metallurgy literature review, keeping your PDFs and SQLite database synchronized locally.
2. **As a Backend Data Engine**: Extract `studio/codex_backend.py` and the SQLite verification schema (`solder_lit.db`) into your own custom UI or terminal workspace, reusing the verbatim quote-gating and OpenAlex PDF harvester.
3. **As a Codex Skill Module**: Port the 3-lens STORM critique logic and research audit card generation directly into `.codex/skills/` as executable CLI skills.

---

## 7. Key References & Research Links

* **Solder Studio Code Repository**: [GitHub Commit `a368444`](https://github.com/HolyUsernameBat/solder-studio/commit/a368444)
* **Andrej Karpathy's LLM Wiki Pattern**: [llm-wiki Framework & Methodology](https://github.com)
* **Stanford STORM Framework**: [Multi-Perspective AI Research Pipeline](https://www.youtube.com/watch?v=Tj3018n5MVg)
* **OpenAlex Catalog & API**: [OpenAlex Scholarly Platform](https://openalex.org) | [OpenAlex API Reference](https://api.openalex.org)
* **Astral `uv` Python Package Runner**: [Astral `uv` Documentation](https://astral.sh/uv)
