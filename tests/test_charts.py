import pandas as pd

from studio.charts import rows_to_dataframe, shear_mpa_chart_frame, uts_chart_frame
from studio.schema import ShearUnit, SolderRow


def test_shear_chart_excludes_newtons_includes_mpa():
    rows = [
        SolderRow(
            imc_thickness_um=3.0,
            shear_value=45.0,
            shear_unit=ShearUnit.N,
        ),
        SolderRow(
            imc_thickness_um=4.0,
            shear_value=38.0,
            shear_unit=ShearUnit.MPA,
        ),
    ]
    df = rows_to_dataframe(rows)
    chart = shear_mpa_chart_frame(df)
    assert len(chart) == 1
    assert chart.iloc[0]["shear_unit"] == "MPa"
    assert chart.iloc[0]["shear_value"] == 38.0


def test_shear_chart_excludes_gf():
    rows = [
        SolderRow(
            imc_thickness_um=2.5,
            shear_value=120.0,
            shear_unit=ShearUnit.GF,
        ),
        SolderRow(
            imc_thickness_um=3.5,
            shear_value=41.0,
            shear_unit=ShearUnit.MPA,
            verbatim_quote="shear 41 MPa",
        ),
    ]
    df = rows_to_dataframe(rows)
    chart = shear_mpa_chart_frame(df)
    assert len(chart) == 1
    assert chart.iloc[0]["shear_unit"] == "MPa"


def test_uts_chart_includes_mpa_pairs():
    rows = [
        SolderRow(imc_thickness_um=2.0, uts_mpa=55.0),
        SolderRow(imc_thickness_um=None, uts_mpa=60.0),
    ]
    df = rows_to_dataframe(rows)
    chart = uts_chart_frame(df)
    assert len(chart) == 1