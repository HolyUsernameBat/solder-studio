from studio.quote_gate import filter_rows_quote_gate, row_passes_quote_gate
from studio.schema import SolderRow


def test_row_dropped_when_thickness_not_in_quote():
    row = SolderRow(
        imc_thickness_um=12.5,
        verbatim_quote="The interfacial layer was examined by SEM.",
    )
    assert not row_passes_quote_gate(row)
    assert filter_rows_quote_gate([row]) == []


def test_row_kept_when_thickness_in_quote():
    row = SolderRow(
        imc_thickness_um=12.5,
        verbatim_quote="IMC thickness was 12.5 um after 1000 h aging.",
    )
    assert row_passes_quote_gate(row)
    assert len(filter_rows_quote_gate([row])) == 1


def test_error_bar_center_value_matches():
    row = SolderRow(
        shear_value=42.3,
        verbatim_quote="Ball shear strength was 42.3 ± 3.1 MPa after aging.",
    )
    assert row_passes_quote_gate(row)


def test_newline_inside_number_still_matches():
    row = SolderRow(
        shear_value=42.3,
        verbatim_quote="Strength reached 42.\n3 MPa under load.",
    )
    assert row_passes_quote_gate(row)