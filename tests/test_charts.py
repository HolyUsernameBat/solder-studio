import pandas as pd

from studio.charts import (
    plotter_metric_options,
    rows_to_dataframe,
    y_options_matching_x_unit,
)
from studio.schema import MeasurementRow, SourceSection


def test_plotter_y_options_match_x_unit_only():
    rows = [
        MeasurementRow(
            metric_name="ball shear",
            metric_value=45.0,
            metric_unit="N",
            source_section=SourceSection.TABLE,
            verbatim_quote="shear 45 N",
        ),
        MeasurementRow(
            metric_name="ball shear",
            metric_value=38.0,
            metric_unit="MPa",
            source_section=SourceSection.TABLE,
            verbatim_quote="shear 38 MPa",
        ),
        MeasurementRow(
            metric_name="IMC thickness",
            metric_value=3.0,
            metric_unit="um",
            source_section=SourceSection.RESULTS,
            verbatim_quote="thickness 3.0 um",
        ),
        MeasurementRow(
            metric_name="lap shear",
            metric_value=41.0,
            metric_unit="MPa",
            source_section=SourceSection.TABLE,
            verbatim_quote="lap shear 41 MPa",
        ),
    ]
    df = rows_to_dataframe(rows)
    options = plotter_metric_options(df)
    mpa_opts = [o for o in options if o[2] == "MPa"]
    x_name, _, x_unit = mpa_opts[0]
    y_opts = y_options_matching_x_unit(options, x_unit)
    assert all(o[2] == "MPa" for o in y_opts)
    assert not any(o[2] in ("N", "gf") for o in y_opts)
    n_opts = y_options_matching_x_unit(options, "N")
    assert n_opts and all(o[2] == "N" for o in n_opts)


def test_mixed_units_not_on_same_axis():
    options = [
        ("ball shear (N)", "ball shear", "N"),
        ("ball shear (MPa)", "ball shear", "MPa"),
        ("lap shear (gf)", "lap shear", "gf"),
    ]
    y_mpa = y_options_matching_x_unit(options, "MPa")
    assert len(y_mpa) == 1
    assert y_mpa[0][2] == "MPa"