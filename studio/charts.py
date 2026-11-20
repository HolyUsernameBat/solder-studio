from __future__ import annotations

import pandas as pd

from studio.schema import ShearUnit, SolderRow


def rows_to_dataframe(rows: list[SolderRow], paper_titles: dict[int, str] | None = None) -> pd.DataFrame:
    records = []
    for r in rows:
        rec = r.model_dump()
        rec["shear_unit"] = r.shear_unit.value
        rec["aging_type"] = r.aging_type.value
        rec["imc_phase"] = r.imc_phase.value
        if paper_titles and r.paper_id is not None:
            rec["paper_title"] = paper_titles.get(r.paper_id, "")
        records.append(rec)
    return pd.DataFrame(records)


def shear_mpa_chart_frame(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    mask = (
        df["shear_value"].notna()
        & df["imc_thickness_um"].notna()
        & (df["shear_unit"] == ShearUnit.MPA.value)
    )
    return df.loc[mask].copy()


def uts_chart_frame(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    mask = df["uts_mpa"].notna() & df["imc_thickness_um"].notna()
    return df.loc[mask].copy()