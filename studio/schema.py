from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class AgingType(str, Enum):
    AS_REFLOWED = "as-reflowed"
    ISOTHERMAL = "isothermal"
    THERMAL_CYCLING = "thermal cycling"
    UNSPECIFIED = "unspecified"


class ImcPhase(str, Enum):
    CU6SN5 = "Cu6Sn5"
    CU3SN = "Cu3Sn"
    MIXED = "mixed"
    UNSPECIFIED = "unspecified"


class ShearUnit(str, Enum):
    MPA = "MPa"
    N = "N"
    GF = "gf"
    UNSPECIFIED = "unspecified"


class PaperCoverage(str, Enum):
    FULL_TEXT = "full-text"
    ABSTRACT_ONLY = "abstract-only"


class TriageTier(str, Enum):
    MUST_READ = "Must Read (Deep Dive)"
    DATA_SOURCE = "Data Source Only"
    LOW_PRIORITY = "Low Priority"


class SolderRow(BaseModel):
    alloy: Optional[str] = None
    addition_name: Optional[str] = None
    addition_weight_percent: Optional[float] = None
    substrate: Optional[str] = None
    reflow_temp_c: Optional[float] = None
    aging_condition: Optional[str] = None
    aging_type: AgingType = AgingType.UNSPECIFIED
    imc_phase: ImcPhase = ImcPhase.UNSPECIFIED
    imc_thickness_um: Optional[float] = None
    shear_value: Optional[float] = None
    shear_unit: ShearUnit = ShearUnit.UNSPECIFIED
    uts_mpa: Optional[float] = None
    elongation_percent: Optional[float] = None
    fracture_mode: Optional[str] = None
    sample_size: Optional[str] = None
    source_page: Optional[int] = None
    verbatim_quote: Optional[str] = None
    paper_id: Optional[int] = None


class PaperAudit(BaseModel):
    openalex_id: Optional[str] = None
    title: str
    authors: Optional[str] = None
    year: Optional[int] = None
    abstract: Optional[str] = None
    doi: Optional[str] = None
    pdf_path: Optional[str] = None
    coverage: PaperCoverage = PaperCoverage.ABSTRACT_ONLY
    triage_tier: Optional[TriageTier] = None
    triage_score: Optional[int] = Field(default=None, ge=1, le=5)
    triage_rationale: Optional[str] = None


class ExtractionList(BaseModel):
    rows: list[SolderRow] = Field(default_factory=list)


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


class ImcChemistLensOutput(BaseModel):
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