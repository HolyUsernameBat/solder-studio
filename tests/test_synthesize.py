from studio.schema import (
    ImcChemistLensOutput,
    MetallurgistLensOutput,
    ReliabilitySkepticLensOutput,
    ShearUnit,
    SolderRow,
)
from studio.synthesize import (
    build_synthesis_user_prompt,
    run_synthesis,
    stop_message_if_insufficient,
)


def _quoted_row(**kwargs) -> SolderRow:
    defaults = dict(
        imc_thickness_um=1.0,
        shear_value=10.0,
        shear_unit=ShearUnit.MPA,
        verbatim_quote="thickness 1.0 um and shear 10 MPa",
    )
    defaults.update(kwargs)
    return SolderRow(**defaults)


def test_two_rows_stop_without_model(monkeypatch):
    rows = [_quoted_row(), _quoted_row(verbatim_quote="thickness 1.0 um and shear 10 MPa")]
    msg = stop_message_if_insufficient(rows)
    assert msg is not None
    calls = {"n": 0}

    def fake_complete(*_a, **_k):
        calls["n"] += 1
        raise AssertionError("Codex should not run under three rows")

    monkeypatch.setattr("studio.synthesize.complete_structured", fake_complete)
    result, stop, used = run_synthesis(rows)
    assert result is None
    assert stop is not None
    assert calls["n"] == 0
    assert len(used) == 2


def test_synthesis_prompt_includes_paper_titles():
    rows = [
        _quoted_row(paper_id=7, source_page=2),
        _quoted_row(paper_id=8, source_page=3, verbatim_quote="IMC thickness 1.0 um, shear 10 MPa"),
        _quoted_row(
            paper_id=7,
            source_page=4,
            verbatim_quote="measured 1.0 um IMC, 10 MPa ball shear",
        ),
    ]
    prompt = build_synthesis_user_prompt(
        rows, paper_titles={7: "Bi-doped SAC305 study", 8: "IMC aging paper"}
    )
    assert "Bi-doped SAC305 study" in prompt
    assert "IMC aging paper" in prompt


def test_three_rows_invoke_three_lens_calls(monkeypatch):
    rows = [
        _quoted_row(),
        _quoted_row(verbatim_quote="IMC thickness 1.0 um, shear 10 MPa"),
        _quoted_row(verbatim_quote="measured 1.0 um IMC, 10 MPa ball shear"),
    ]
    calls = {"n": 0}

    def fake_complete(model_cls, _instructions, _user, **_kwargs):
        calls["n"] += 1
        if model_cls is MetallurgistLensOutput:
            return MetallurgistLensOutput()
        if model_cls is ImcChemistLensOutput:
            return ImcChemistLensOutput()
        if model_cls is ReliabilitySkepticLensOutput:
            return ReliabilitySkepticLensOutput()
        raise AssertionError(f"unexpected model {model_cls}")

    monkeypatch.setattr("studio.synthesize.complete_structured", fake_complete)
    briefing, stop, used = run_synthesis(rows)
    assert stop is None
    assert briefing is not None
    assert briefing.html.startswith("<!DOCTYPE html>")
    assert calls["n"] == 3
    assert len(used) == 3