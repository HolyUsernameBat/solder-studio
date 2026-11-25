"""Capture README guide PNGs with red annotation boxes from live Streamlit DOM positions."""
from __future__ import annotations

import sqlite3
import sys
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "solder_lit.db"
GUIDE_DIR = ROOT / "docs" / "guide"
URL = "http://localhost:8501"
VIEWPORT = {"width": 1456, "height": 900}
PAD = 4

EXPAND_JS = """() => {
  const main = document.querySelector('[data-testid=stMain]');
  if (!main) return;
  main.scrollTop = 0;
  const h = main.scrollHeight;
  main.style.height = h + 'px';
  main.style.minHeight = h + 'px';
  main.style.overflow = 'visible';
  for (const sel of ['[data-testid=stAppViewContainer]', '[data-testid=stApp]']) {
    const el = document.querySelector(sel);
    if (el) {
      el.style.overflow = 'visible';
      el.style.minHeight = h + 140 + 'px';
    }
  }
}"""


@dataclass
class BoxSpec:
    label: str
    locator_js: str  # returns element or null


def update_example_question() -> str:
    new_text = "Replace this with your own question"
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT research_question FROM research_questions WHERE question_id = 2 AND project_id = 2"
    ).fetchone()
    if row and row[0] != new_text:
        conn.execute(
            "UPDATE research_questions SET research_question = ? WHERE question_id = 2 AND project_id = 2",
            (new_text,),
        )
        conn.commit()
    conn.close()
    return new_text


def page_box(page: Page, locator) -> dict | None:
    return locator.evaluate(
        """(el) => {
            if (!el) return null;
            const r = el.getBoundingClientRect();
            return {
                x: r.x + window.scrollX,
                y: r.y + window.scrollY,
                width: r.width,
                height: r.height,
            };
        }"""
    )


def widget_by_label(page: Page, label: str, testid: str):
    """Find Streamlit widget container whose label paragraph matches `label`."""
    return page.locator(f'div[data-testid="{testid}"]').filter(
        has=page.locator('[data-testid="stWidgetLabel"] p', has_text=label)
    ).first


def radio_by_label(page: Page, label: str):
    return widget_by_label(page, label, "stRadio")


def selectbox_by_label(page: Page, label: str):
    return widget_by_label(page, label, "stSelectbox")


def text_input_by_label(page: Page, label: str):
    return widget_by_label(page, label, "stTextInput")


def checkbox_by_label(page: Page, label: str):
    return widget_by_label(page, label, "stCheckbox")


def button_by_text(page: Page, text: str, exact: bool = False):
    return page.get_by_role("button", name=text, exact=exact).first


def tab_by_text(page: Page, text: str):
    return page.get_by_role("tab", name=text).first


def file_uploader_by_label(page: Page, label: str):
    return widget_by_label(page, label, "stFileUploader")


def codex_status_block(page: Page):
    return page.locator("section[data-testid='stSidebar']").locator("div[data-testid='stMarkdown']").filter(
        has_text="Codex idle"
    ).first


def sidebar_selectbox_nth(page: Page, n: int):
    return (
        page.locator("section[data-testid='stSidebar']")
        .locator('div[data-testid="stSelectbox"]')
        .nth(n)
    )


def subheader_block(page: Page, text: str):
    return page.locator('[data-testid="stHeading"]').filter(has_text=text).first


def prepare_tall_capture(page: Page) -> None:
    page.locator('[data-testid="stMain"]').evaluate("el => { el.scrollTop = 0; }")
    main_sh = page.locator('[data-testid="stMain"]').evaluate("el => el.scrollHeight")
    height = min(max(int(main_sh) + 140, VIEWPORT["height"]), 2800)
    page.set_viewport_size({"width": VIEWPORT["width"], "height": height})
    page.evaluate(EXPAND_JS)
    page.wait_for_timeout(250)


def prepare_viewport_capture(page: Page) -> None:
    page.set_viewport_size(VIEWPORT)
    page.locator('[data-testid="stMain"]').evaluate("el => { el.scrollTop = 0; }")
    page.wait_for_timeout(150)


def draw_annotations(
    img: Image.Image,
    boxes: list[tuple[dict, str]],
    stroke: int = 3,
) -> Image.Image:
    out = img.copy()
    draw = ImageDraw.Draw(out)
    try:
        font = ImageFont.truetype("arial.ttf", 16)
    except OSError:
        font = ImageFont.load_default()
    red = (255, 60, 60)
    for box, label in boxes:
        if not box or box["width"] < 2 or box["height"] < 2:
            print(f"WARN: missing box for {label!r}", file=sys.stderr)
            continue
        x0 = int(box["x"]) - PAD
        y0 = int(box["y"]) - PAD
        x1 = int(box["x"] + box["width"]) + PAD
        y1 = int(box["y"] + box["height"]) + PAD
        for i in range(stroke):
            draw.rectangle([x0 - i, y0 - i, x1 + i, y1 + i], outline=red)
        lx = x0
        ly = max(0, y0 - 22)
        draw.text((lx + 2, ly), label, fill=red, font=font)
    return out


def capture_page(
    page: Page,
    boxes: list[tuple[object, str]],
    out_path: Path,
    *,
    tall: bool = True,
) -> None:
    if tall:
        prepare_tall_capture(page)
    else:
        prepare_viewport_capture(page)
    items: list[tuple[dict | None, str]] = []
    for loc, label in boxes:
        try:
            loc.wait_for(state="attached", timeout=15000)
        except Exception:
            pass
        items.append((page_box(page, loc), label))
    png = page.screenshot(full_page=True)
    img = Image.open(BytesIO(png)).convert("RGB")
    annotated = draw_annotations(img, [(b, l) for b, l in items if b is not None])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    annotated.save(out_path)
    print(f"Wrote {out_path}")


def select_example_project(page: Page) -> None:
    radio = radio_by_label(page, "Active project")
    radio.get_by_text("[EXAMPLE] test", exact=False).click()
    page.wait_for_timeout(1500)


def wait_app(page: Page) -> None:
    page.goto(URL, wait_until="networkidle")
    page.wait_for_selector("text=Solder Studio", timeout=60000)


def capture_01(page: Page) -> None:
    select_example_project(page)
    boxes = [
        (radio_by_label(page, "Active project"), "Active project"),
        (radio_by_label(page, "Active research question"), "Active research question"),
    ]
    capture_page(page, boxes, GUIDE_DIR / "01-project-and-question.png", tall=False)


def capture_02(page: Page) -> None:
    select_example_project(page)
    tab_by_text(page, "Search & triage").click()
    page.wait_for_timeout(800)
    boxes: list[tuple[object, str]] = [
        (text_input_by_label(page, "Search query"), "Search query"),
        (button_by_text(page, "Search OpenAlex"), "Search OpenAlex"),
        (file_uploader_by_label(page, "Upload PDFs"), "Upload PDFs"),
        (checkbox_by_label(page, "Hide abstract-only"), "Hide abstract-only"),
    ]
    paper_detail = selectbox_by_label(page, "Paper detail")
    if paper_detail.count() > 0:
        try:
            paper_detail.wait_for(state="visible", timeout=2000)
            boxes.append((paper_detail, "Paper detail"))
        except Exception:
            pass
    capture_page(page, boxes, GUIDE_DIR / "02-search-and-triage.png", tall=True)


def capture_03(page: Page) -> None:
    select_example_project(page)
    page.evaluate("window.scrollTo(0, 0)")
    boxes: list[tuple[object, str]] = []
    codex = codex_status_block(page)
    if codex.count() == 0:
        codex = (
            page.locator("section[data-testid='stSidebar']")
            .locator("div[data-testid='stMarkdown']")
            .last
        )
    boxes.append((codex, "Codex status"))
    labels = [
        "Extract / audit",
        "Physical Metallurgist",
        "Interface & Mechanisms",
        "Reliability Skeptic",
    ]
    for label in labels:
        sb = selectbox_by_label(page, label)
        if sb.count() == 0:
            # signed-out UI: skip with warning
            print(f"WARN: sidebar selectbox {label!r} not found (Codex signed in?)", file=sys.stderr)
            continue
        boxes.append((sb, label))
    capture_page(page, boxes, GUIDE_DIR / "03-sidebar-models.png", tall=False)


def capture_04(page: Page) -> None:
    select_example_project(page)
    tab_by_text(page, "Measurements").click()
    page.wait_for_timeout(800)
    area = page.locator('[data-testid="stAlert"]').filter(
        has_text="No rows yet. Audit a PDF from tab 1."
    )
    if area.count() == 0:
        area = page.locator('[data-testid="stDataFrame"]')
    boxes = [
        (tab_by_text(page, "Measurements"), "Measurements tab"),
        (area, "Extracted measurements"),
    ]
    capture_page(page, boxes, GUIDE_DIR / "04-measurements.png", tall=True)


def capture_05(page: Page) -> None:
    select_example_project(page)
    tab_by_text(page, "Synthesis").click()
    page.wait_for_timeout(800)
    boxes = [
        (tab_by_text(page, "Synthesis"), "Synthesis tab"),
        (button_by_text(page, "Run synthesis"), "Run synthesis"),
    ]
    capture_page(page, boxes, GUIDE_DIR / "05-synthesis.png", tall=True)


def main() -> int:
    new_q = update_example_question()
    print(f"Example question: {new_q!r}")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport=VIEWPORT)
        page.emulate_media(color_scheme="dark")
        try:
            wait_app(page)
            capture_01(page)
            page.goto(URL, wait_until="networkidle")
            wait_app(page)
            capture_02(page)
            page.goto(URL, wait_until="networkidle")
            wait_app(page)
            capture_03(page)
            page.goto(URL, wait_until="networkidle")
            wait_app(page)
            capture_04(page)
            page.goto(URL, wait_until="networkidle")
            wait_app(page)
            capture_05(page)
        finally:
            browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())