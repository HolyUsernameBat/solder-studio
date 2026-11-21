from __future__ import annotations

import json
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class PaperCoverage(str, Enum):
    FULL_TEXT = "full-text"
    ABSTRACT_ONLY = "abstract-only"


class TriageTier(str, Enum):
    MUST_READ = "Must Read (Deep Dive)"
    DATA_SOURCE = "Data Source Only"
    LOW_PRIORITY = "Low Priority"


class SourceSection(str, Enum):
    RESULTS = "Results"
    TABLE = "Table"
    FIGURE = "Figure"
    ABSTRACT = "Abstract"
    INTRODUCTION = "Introduction"


DEFAULT_RESEARCH_QUESTION = (
    "In a copper joint made with a Sn-Ag-Cu solder, what does a bismuth addition "
    "do to the intermetallic thickness and to the strength?"
)

DEFAULT_PROJECT_NAME = "SAC bismuth joints"

DEFAULT_SCREENING_CRITERIA = (
    "Sn-Ag-Cu or SAC solder on copper; bismuth additions; intermetallic (IMC) "
    "thickness; joint shear or tensile strength; experimental or quantitative studies."
)

DEFAULT_TARGET_METRICS = [
    "IMC thickness (um)",
    "intermetallic layer thickness (um)",
    "ball shear strength (MPa)",
    "lap shear strength (MPa)",
    "ultimate tensile strength (MPa)",
    "UTS (MPa)",
]


class Project(BaseModel):
    project_id: Optional[int] = None
    name: str
    research_question: str = ""
    screening_criteria: str = ""
    target_metrics_json: str = Field(
        default_factory=lambda: json.dumps(DEFAULT_TARGET_METRICS)
    )
    created_at: Optional[str] = None


class ResearchQuestion(BaseModel):
    question_id: Optional[int] = None
    project_id: int
    research_question: str
    screening_criteria: str = ""
    target_metrics_json: str = Field(
        default_factory=lambda: json.dumps(DEFAULT_TARGET_METRICS)
    )
    created_at: Optional[str] = None

    def target_metrics(self) -> list[str]:
        try:
            data = json.loads(self.target_metrics_json)
            if isinstance(data, list):
                return [str(x) for x in data]
        except json.JSONDecodeError:
            pass
        return list(DEFAULT_TARGET_METRICS)


class MeasurementRow(BaseModel):
    measurement_id: Optional[int] = None
    project_id: Optional[int] = None
    question_id: Optional[int] = None
    paper_id: Optional[int] = None
    material_system: Optional[str] = None
    composition_or_variant: Optional[str] = None
    processing_or_aging_condition: Optional[str] = None
    phase_or_microstructure: Optional[str] = None
    metric_name: Optional[str] = None
    metric_value: Optional[float] = None
    metric_unit: Optional[str] = None
    sample_size: Optional[str] = None
    source_section: Optional[SourceSection] = None
    source_page: Optional[int] = None
    verbatim_quote: Optional[str] = None


class PaperAudit(BaseModel):
    openalex_id: Optional[str] = None
    title: str
    authors: Optional[str] = None
    year: Optional[int] = None
    abstract: Optional[str] = None
    doi: Optional[str] = None
    pdf_path: Optional[str] = None
    coverage: PaperCoverage = PaperCoverage.ABSTRACT_ONLY
    project_id: Optional[int] = None
    triage_tier: Optional[TriageTier] = None
    triage_score: Optional[int] = Field(default=None, ge=1, le=5)
    triage_rationale: Optional[str] = None
    relevance_justification: Optional[str] = None
    core_claim_and_mechanism: Optional[str] = None
    system_and_conditions: Optional[str] = None
    key_findings: Optional[str] = None
    limitations_and_caveats: Optional[str] = None


class ExtractionList(BaseModel):
    rows: list[MeasurementRow] = Field(default_factory=list)


class LensClaim(BaseModel):
    statement: str
    paper_title: str
    source_page: int
    verbatim_quote: str


class MetallurgistLensOutput(BaseModel):
    claims: list[LensClaim] = Field(default_factory=list)
    settled_observations: list[str] = Field(default_factory=list)
    contested_observations: list[str] = Field(default_factory=list)
    uncaptured_by_table: list[str] = Field(default_factory=list)


class InterfaceMechanismsLensOutput(BaseModel):
    claims: list[LensClaim] = Field(default_factory=list)
    settled_observations: list[str] = Field(default_factory=list)
    contested_observations: list[str] = Field(default_factory=list)
    uncaptured_by_table: list[str] = Field(default_factory=list)


class ReliabilitySkepticLensOutput(BaseModel):
    claims: list[LensClaim] = Field(default_factory=list)
    safe_to_assert: list[LensClaim] = Field(default_factory=list)
    say_with_caveat: list[LensClaim] = Field(default_factory=list)
    insufficient_data: list[str] = Field(default_factory=list)


class BriefingDocument(BaseModel):
    executive_summary: str
    findings_markdown: str
    contradictions_markdown: str
    table_gaps_markdown: str
    buckets_markdown: str
    html: str