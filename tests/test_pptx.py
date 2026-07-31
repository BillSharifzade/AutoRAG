"""PPTX generation: valid zip, well-formed OOXML, consistent rels, slide text."""

import io
import os
import shutil
import subprocess
import tempfile
import xml.dom.minidom as minidom
import zipfile

import pytest

from karag.office import OfficeService
from karag.office.pptx import build_pptx


def _zip(content: bytes) -> zipfile.ZipFile:
    assert content[:2] == b"PK"
    assert zipfile.is_zipfile(io.BytesIO(content))
    return zipfile.ZipFile(io.BytesIO(content))


def test_pptx_structure_and_wellformed():
    content = build_pptx([
        {"title": "Overview", "bullets": ["one", "two"]},
        {"title": "Details", "bullets": ["three"]},
    ])
    zf = _zip(content)
    names = set(zf.namelist())
    required = {
        "[Content_Types].xml",
        "_rels/.rels",
        "ppt/presentation.xml",
        "ppt/_rels/presentation.xml.rels",
        "ppt/slideMasters/slideMaster1.xml",
        "ppt/slideLayouts/slideLayout1.xml",
        "ppt/theme/theme1.xml",
        "ppt/slides/slide1.xml",
        "ppt/slides/slide2.xml",
        "ppt/slides/_rels/slide1.xml.rels",
    }
    assert required <= names

    # every XML part must be well-formed
    for name in names:
        if name.endswith(".xml") or name.endswith(".rels"):
            minidom.parseString(zf.read(name))  # raises on malformed XML

    # slide text present
    assert "Overview" in zf.read("ppt/slides/slide1.xml").decode()
    assert "three" in zf.read("ppt/slides/slide2.xml").decode()


def test_pptx_rels_reference_existing_parts():
    content = build_pptx([{"title": "A", "bullets": []}])
    zf = _zip(content)
    names = set(zf.namelist())
    # presentation rels must point at parts that exist
    rels = zf.read("ppt/_rels/presentation.xml.rels").decode()
    assert "slideMasters/slideMaster1.xml" in rels
    assert "slides/slide1.xml" in rels
    assert "ppt/slideMasters/slideMaster1.xml" in names
    # slideId count matches slide parts
    pres = zf.read("ppt/presentation.xml").decode()
    assert pres.count("<p:sldId ") == 1


def test_pptx_layout_title_bar_footer_and_bullets():
    content = build_pptx([
        {"title": "Cover", "subtitle": "A subtitle", "layout": "title"},
        {"title": "Findings", "bullets": ["alpha", "beta"], "footer": "Confidential"},
    ])
    zf = _zip(content)
    cover = zf.read("ppt/slides/slide1.xml").decode()
    body = zf.read("ppt/slides/slide2.xml").decode()

    # title slide: no title bar, but the subtitle text renders
    assert "TitleBar" not in cover
    assert "A subtitle" in cover
    # content slide: branded title bar + accent rule, real bullets, footer + page no.
    assert 'name="TitleBar"' in body and 'name="AccentRule"' in body
    assert "27409E" in body  # bar fill colour
    assert "buChar" in body  # bulleted paragraphs
    assert "Confidential" in body and "2/2" in body  # footer + page number

    # still well-formed OOXML
    for name in zf.namelist():
        if name.endswith((".xml", ".rels")):
            minidom.parseString(zf.read(name))


@pytest.mark.skipif(
    not (os.environ.get("KARAG_TEST_LIBREOFFICE") and shutil.which("libreoffice")),
    reason="set KARAG_TEST_LIBREOFFICE=1 and install libreoffice to run",
)
def test_pptx_opens_in_libreoffice():
    content = build_pptx([
        {"title": "Q Review", "subtitle": "Koinoti", "layout": "title"},
        {"title": "Sales", "bullets": ["Store 5 — 18,450"], "footer": "Confidential"},
    ])
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "deck.pptx")
        with open(src, "wb") as fh:
            fh.write(content)
        subprocess.run(
            ["libreoffice", "--headless", "--convert-to", "pdf", "--outdir", d, src],
            check=True, capture_output=True, timeout=120,
        )
        assert os.path.exists(os.path.join(d, "deck.pdf"))


def test_service_pptx_from_table():
    svc = OfficeService()
    art = svc.report(
        title="Sales deck", headers=["store", "total"], rows=[[5, 18450]], fmt="pptx"
    )
    assert art.filename == "Sales_deck.pptx"
    assert art.mime.endswith("presentationml.presentation")
    zf = _zip(art.content)
    slide2 = zf.read("ppt/slides/slide2.xml").decode()
    assert "18450" in slide2  # the figure made it into the deck
