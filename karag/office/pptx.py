"""Minimal valid .pptx writer (PresentationML) using only the stdlib.

Produces a deck with one title + bullet-list content box per slide, plus the
required presentation / slide-master / slide-layout / theme boilerplate. Every
part is well-formed OOXML and the package relationships are internally
consistent, so the file opens in PowerPoint / LibreOffice / Google Slides.

Layout uses explicit shape geometry (EMU) rather than inheriting placeholder
positions, which keeps rendering predictable across viewers.
"""

from __future__ import annotations

from ._pkg import build_package, xml_escape

_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_P = "http://schemas.openxmlformats.org/presentationml/2006/main"
_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_CT = "http://schemas.openxmlformats.org/package/2006/content-types"
_REL = "http://schemas.openxmlformats.org/package/2006/relationships"

# 16:9 slide, in EMU (914400 EMU = 1 inch).
_CX, _CY = 12192000, 6858000
_MARGIN = 685800  # 0.75"

# Brand palette (hex, no leading '#'), matching the KARAG console.
_BAR = "27409E"     # title-bar background
_ACCENT = "3554D1"  # accent rule under the title bar
_INK = "0F1B2D"     # body text
_MUT = "64748B"     # footer / subtitle text
_WHITE = "FFFFFF"

_BAR_H = 1143000    # title-bar height
_RULE_H = 45720     # accent rule thickness

_XML = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'


def _content_types(n_slides: int) -> str:
    slide_overrides = "".join(
        f'<Override PartName="/ppt/slides/slide{i}.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>'
        for i in range(1, n_slides + 1)
    )
    return (
        f'{_XML}<Types xmlns="{_CT}">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/ppt/presentation.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>'
        '<Override PartName="/ppt/slideMasters/slideMaster1.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"/>'
        '<Override PartName="/ppt/slideLayouts/slideLayout1.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/>'
        '<Override PartName="/ppt/theme/theme1.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>'
        f"{slide_overrides}</Types>"
    )


def _root_rels() -> str:
    return (
        f'{_XML}<Relationships xmlns="{_REL}">'
        f'<Relationship Id="rId1" Type="{_R}/officeDocument" Target="ppt/presentation.xml"/>'
        "</Relationships>"
    )


def _presentation(n_slides: int) -> str:
    sld_ids = "".join(
        f'<p:sldId id="{256 + i}" r:id="rId{i + 1}"/>' for i in range(n_slides)
    )
    return (
        f'{_XML}<p:presentation xmlns:a="{_A}" xmlns:r="{_R}" xmlns:p="{_P}">'
        '<p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst>'
        f"<p:sldIdLst>{sld_ids}</p:sldIdLst>"
        f'<p:sldSz cx="{_CX}" cy="{_CY}"/>'
        '<p:notesSz cx="6858000" cy="9144000"/>'
        "</p:presentation>"
    )


def _presentation_rels(n_slides: int) -> str:
    slides = "".join(
        f'<Relationship Id="rId{i + 1}" Type="{_R}/slide" Target="slides/slide{i + 1}.xml"/>'
        for i in range(n_slides)
    )
    return (
        f'{_XML}<Relationships xmlns="{_REL}">'
        f'<Relationship Id="rId1" Type="{_R}/slideMaster" Target="slideMasters/slideMaster1.xml"/>'
        f"{slides}</Relationships>"
    )


_CLR_MAP = (
    '<p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" '
    'accent2="accent2" accent3="accent3" accent4="accent4" accent5="accent5" '
    'accent6="accent6" hlink="hlink" folHlink="folHlink"/>'
)

_EMPTY_SPTREE = (
    "<p:spTree>"
    '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
    "<p:grpSpPr/></p:spTree>"
)


def _slide_master() -> str:
    return (
        f'{_XML}<p:sldMaster xmlns:a="{_A}" xmlns:r="{_R}" xmlns:p="{_P}">'
        f"<p:cSld>{_EMPTY_SPTREE}</p:cSld>"
        f"{_CLR_MAP}"
        '<p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst>'
        "</p:sldMaster>"
    )


def _slide_master_rels() -> str:
    return (
        f'{_XML}<Relationships xmlns="{_REL}">'
        f'<Relationship Id="rId1" Type="{_R}/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>'
        f'<Relationship Id="rId2" Type="{_R}/theme" Target="../theme/theme1.xml"/>'
        "</Relationships>"
    )


def _slide_layout() -> str:
    return (
        f'{_XML}<p:sldLayout xmlns:a="{_A}" xmlns:r="{_R}" xmlns:p="{_P}" type="blank" preserve="1">'
        f"<p:cSld name=\"Blank\">{_EMPTY_SPTREE}</p:cSld>"
        "<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>"
        "</p:sldLayout>"
    )


def _slide_layout_rels() -> str:
    return (
        f'{_XML}<Relationships xmlns="{_REL}">'
        f'<Relationship Id="rId1" Type="{_R}/slideMaster" Target="../slideMasters/slideMaster1.xml"/>'
        "</Relationships>"
    )


def _textbox(
    shape_id: int, name: str, x: int, y: int, cx: int, cy: int, paragraphs: str,
    *, anchor: str | None = None,
) -> str:
    body_pr = f'<a:bodyPr anchor="{anchor}"/>' if anchor else "<a:bodyPr/>"
    return (
        "<p:sp>"
        f'<p:nvSpPr><p:cNvPr id="{shape_id}" name="{xml_escape(name)}"/>'
        "<p:cNvSpPr><a:spLocks noGrp=\"1\"/></p:cNvSpPr><p:nvPr/></p:nvSpPr>"
        "<p:spPr>"
        f'<a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
        "</p:spPr>"
        f"<p:txBody>{body_pr}<a:lstStyle/>{paragraphs}</p:txBody>"
        "</p:sp>"
    )


def _rect(shape_id: int, name: str, x: int, y: int, cx: int, cy: int, fill_hex: str) -> str:
    """A solid-filled, borderless rectangle — used for the title bar / accent rule."""
    return (
        "<p:sp>"
        f'<p:nvSpPr><p:cNvPr id="{shape_id}" name="{xml_escape(name)}"/>'
        "<p:cNvSpPr/><p:nvPr/></p:nvSpPr>"
        "<p:spPr>"
        f'<a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
        f'<a:solidFill><a:srgbClr val="{fill_hex}"/></a:solidFill>'
        "<a:ln><a:noFill/></a:ln>"
        "</p:spPr>"
        "<p:txBody><a:bodyPr/><a:lstStyle/><a:p/></p:txBody>"
        "</p:sp>"
    )


def _para(
    text: str, *, size: int, bold: bool = False, bullet: bool = False,
    color: str | None = None, align: str | None = None,
) -> str:
    fill = f'<a:solidFill><a:srgbClr val="{color}"/></a:solidFill>' if color else ""
    rpr_attrs = f' sz="{size}"' + (' b="1"' if bold else "")
    rpr = (
        f'<a:rPr lang="en-US"{rpr_attrs}>{fill}</a:rPr>'
        if fill
        else f'<a:rPr lang="en-US"{rpr_attrs}/>'
    )
    ppr_attr = f' algn="{align}"' if align else ""
    if bullet:
        ppr = (
            f'<a:pPr{ppr_attr} marL="285750" indent="-285750">'
            '<a:buFont typeface="Arial"/><a:buChar char="&#8226;"/></a:pPr>'
        )
    else:
        ppr = f"<a:pPr{ppr_attr}><a:buNone/></a:pPr>"
    return f"<a:p>{ppr}<a:r>{rpr}<a:t>{xml_escape(text)}</a:t></a:r></a:p>"


def _wrap_slide(shapes: str) -> str:
    return (
        f'{_XML}<p:sld xmlns:a="{_A}" xmlns:r="{_R}" xmlns:p="{_P}">'
        "<p:cSld><p:spTree>"
        '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
        "<p:grpSpPr/>"
        f"{shapes}"
        "</p:spTree></p:cSld>"
        "<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>"
        "</p:sld>"
    )


def _title_slide(title: str, subtitle: str) -> str:
    """A cover slide: a short centered accent rule over a large centered title."""
    rule_w = 2743200
    shapes = [
        _rect(2, "Accent", (_CX - rule_w) // 2, 2011680, rule_w, _RULE_H, _ACCENT),
        _textbox(
            3, "Title", _MARGIN, 2148840, _CX - 2 * _MARGIN, 1005840,
            _para(title, size=4000, bold=True, color=_BAR, align="ctr"), anchor="ctr",
        ),
    ]
    if subtitle:
        shapes.append(
            _textbox(
                4, "Subtitle", _MARGIN, 3200400, _CX - 2 * _MARGIN, 640080,
                _para(subtitle, size=2000, color=_MUT, align="ctr"), anchor="ctr",
            )
        )
    return _wrap_slide("".join(shapes))


def _content_slide(
    title: str, bullets: list[str], *, index: int, total: int, footer: str
) -> str:
    body_paras = "".join(
        _para(b, size=1800, bullet=True, color=_INK) for b in bullets
    ) or _para("", size=1800, bullet=True, color=_INK)
    foot_y = _CY - 411480
    shapes = [
        _rect(2, "TitleBar", 0, 0, _CX, _BAR_H, _BAR),
        _rect(3, "AccentRule", 0, _BAR_H, _CX, _RULE_H, _ACCENT),
        _textbox(
            4, "Title", _MARGIN, 205740, _CX - 2 * _MARGIN, 731520,
            _para(title, size=2800, bold=True, color=_WHITE), anchor="ctr",
        ),
        _textbox(
            5, "Content", _MARGIN, 1508760, _CX - 2 * _MARGIN, _CY - 1508760 - 502920,
            body_paras,
        ),
        _textbox(
            6, "Footer", _MARGIN, foot_y, _CX - 2 * _MARGIN - 914400, 320040,
            _para(footer, size=1000, color=_MUT),
        ),
        _textbox(
            7, "PageNo", _CX - _MARGIN - 914400, foot_y, 914400, 320040,
            _para(f"{index}/{total}", size=1000, color=_MUT, align="r"),
        ),
    ]
    return _wrap_slide("".join(shapes))


def _slide(
    title: str, bullets: list[str], *, index: int = 1, total: int = 1,
    subtitle: str = "", layout: str = "content", footer: str = "",
) -> str:
    if layout == "title":
        return _title_slide(title, subtitle)
    return _content_slide(title, bullets, index=index, total=total, footer=footer)


def _slide_rels() -> str:
    return (
        f'{_XML}<Relationships xmlns="{_REL}">'
        f'<Relationship Id="rId1" Type="{_R}/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>'
        "</Relationships>"
    )


def _theme() -> str:
    def scheme_color(tag: str, val: str) -> str:
        return f'<a:{tag}><a:srgbClr val="{val}"/></a:{tag}>'

    clr = (
        "<a:clrScheme name=\"Office\">"
        '<a:dk1><a:sysClr val="windowText" lastClr="000000"/></a:dk1>'
        '<a:lt1><a:sysClr val="window" lastClr="FFFFFF"/></a:lt1>'
        + scheme_color("dk2", "44546A")
        + scheme_color("lt2", "E7E6E6")
        + scheme_color("accent1", "4472C4")
        + scheme_color("accent2", "ED7D31")
        + scheme_color("accent3", "A5A5A5")
        + scheme_color("accent4", "FFC000")
        + scheme_color("accent5", "5B9BD5")
        + scheme_color("accent6", "70AD47")
        + scheme_color("hlink", "0563C1")
        + scheme_color("folHlink", "954F72")
        + "</a:clrScheme>"
    )
    font = (
        '<a:fontScheme name="Office">'
        '<a:majorFont><a:latin typeface="Calibri Light"/><a:ea typeface=""/><a:cs typeface=""/></a:majorFont>'
        '<a:minorFont><a:latin typeface="Calibri"/><a:ea typeface=""/><a:cs typeface=""/></a:minorFont>'
        "</a:fontScheme>"
    )
    fill_ref = '<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>'
    line = (
        '<a:ln w="6350" cap="flat" cmpd="sng" algn="ctr">'
        f"{fill_ref}<a:prstDash val=\"solid\"/></a:ln>"
    )
    fmt = (
        '<a:fmtScheme name="Office">'
        f"<a:fillStyleLst>{fill_ref}{fill_ref}{fill_ref}</a:fillStyleLst>"
        f"<a:lnStyleLst>{line}{line}{line}</a:lnStyleLst>"
        "<a:effectStyleLst>"
        "<a:effectStyle><a:effectLst/></a:effectStyle>"
        "<a:effectStyle><a:effectLst/></a:effectStyle>"
        "<a:effectStyle><a:effectLst/></a:effectStyle>"
        "</a:effectStyleLst>"
        f"<a:bgFillStyleLst>{fill_ref}{fill_ref}{fill_ref}</a:bgFillStyleLst>"
        "</a:fmtScheme>"
    )
    return (
        f'{_XML}<a:theme xmlns:a="{_A}" name="Office Theme">'
        f"<a:themeElements>{clr}{font}{fmt}</a:themeElements>"
        "<a:objectDefaults/><a:extraClrSchemeLst/>"
        "</a:theme>"
    )


def build_pptx(slides: list[dict]) -> bytes:
    """``slides`` is a list of ``{"title": str, "bullets": list[str]}``."""
    if not slides:
        slides = [{"title": "", "bullets": []}]
    n = len(slides)

    parts: dict[str, str | bytes] = {
        "[Content_Types].xml": _content_types(n),
        "_rels/.rels": _root_rels(),
        "ppt/presentation.xml": _presentation(n),
        "ppt/_rels/presentation.xml.rels": _presentation_rels(n),
        "ppt/slideMasters/slideMaster1.xml": _slide_master(),
        "ppt/slideMasters/_rels/slideMaster1.xml.rels": _slide_master_rels(),
        "ppt/slideLayouts/slideLayout1.xml": _slide_layout(),
        "ppt/slideLayouts/_rels/slideLayout1.xml.rels": _slide_layout_rels(),
        "ppt/theme/theme1.xml": _theme(),
    }
    for i, s in enumerate(slides, start=1):
        parts[f"ppt/slides/slide{i}.xml"] = _slide(
            s.get("title", ""), list(s.get("bullets", [])),
            index=i, total=n,
            subtitle=s.get("subtitle", ""),
            layout=s.get("layout", "content"),
            footer=s.get("footer", ""),
        )
        parts[f"ppt/slides/_rels/slide{i}.xml.rels"] = _slide_rels()
    return build_package(parts)
