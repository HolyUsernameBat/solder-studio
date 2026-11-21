from __future__ import annotations

from typing import Optional

import pandas as pd

from studio.schema import MeasurementRow


def metric_axis_label(name: str, unit: Optional[str]) -> str:
    u = unit or ""
    return f"{name} ({u})".strip()


def rows_to_dataframe(
    rows: list[MeasurementRow], paper_titles: dict[int, str] | None = None
) -> pd.DataFrame:
    records = []
    for r in rows:
        rec = r.model_dump()
        if r.source_section:
            rec["source_section"] = r.source_section.value
        if paper_titles and r.paper_id is not None:
            rec["paper_title"] = paper_titles.get(r.paper_id, "")
        records.append(rec)
    return pd.DataFrame(records)


def plotter_metric_options(df: pd.DataFrame) -> list[tuple[str, str, str]]:
    """
    Return list of (axis_label, metric_name, metric_unit) for rows with value and name.
    """
    if df.empty or "metric_name" not in df.columns:
        return []
    options: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str]] = set()
    for _, row in df.iterrows():
        name = row.get("metric_name")
        unit = row.get("metric_unit") or ""
        if not name or pd.isna(row.get("metric_value")):
            continue
        key = (str(name), str(unit))
        if key in seen:
            continue
        seen.add(key)
        options.append((metric_axis_label(str(name), str(unit) if unit else ""), str(name), str(unit)))
    return sorted(options, key=lambda x: x[0].lower())


def y_options_matching_x_unit(
    options: list[tuple[str, str, str]], x_unit: str
) -> list[tuple[str, str, str]]:
    return [o for o in options if o[2] == x_unit]


def filter_plot_points(
    df: pd.DataFrame, x_name: str, x_unit: str, y_name: str, y_unit: str
) -> pd.DataFrame:
    if df.empty:
        return df
    x_rows = df[
        (df["metric_name"] == x_name)
        & (df["metric_unit"].fillna("") == x_unit)
        & df["metric_value"].notna()
    ].copy()
    y_rows = df[
        (df["metric_name"] == y_name)
        & (df["metric_unit"].fillna("") == y_unit)
        & df["metric_value"].notna()
    ].copy()
    if x_rows.empty or y_rows.empty:
        return pd.DataFrame()
    if len(x_rows) == 1 and len(y_rows) == 1:
        if x_rows.iloc[0].get("paper_id") == y_rows.iloc[0].get("paper_id"):
            row = {
                "x_value": float(x_rows.iloc[0]["metric_value"]),
                "y_value": float(y_rows.iloc[0]["metric_value"]),
                "paper_id": x_rows.iloc[0].get("paper_id"),
                "paper_title": x_rows.iloc[0].get("paper_title", ""),
                "source_page": x_rows.iloc[0].get("source_page"),
            }
            return pd.DataFrame([row])
    merged = x_rows.merge(
        y_rows,
        on=["paper_id", "composition_or_variant", "processing_or_aging_condition"],
        suffixes=("_x", "_y"),
        how="inner",
    )
    if merged.empty:
        merged = x_rows.merge(y_rows, on="paper_id", suffixes=("_x", "_y"), how="inner")
    if merged.empty:
        return pd.DataFrame()
    out = pd.DataFrame(
        {
            "x_value": merged["metric_value_x"].astype(float),
            "y_value": merged["metric_value_y"].astype(float),
            "paper_id": merged["paper_id"],
            "paper_title": merged.get("paper_title_x", merged.get("paper_title", "")),
            "source_page": merged.get("source_page_x", merged.get("source_page")),
        }
    )
    return out