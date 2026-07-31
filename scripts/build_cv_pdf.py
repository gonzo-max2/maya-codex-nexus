#!/usr/bin/env python3
"""Build an ATS-readable PDF from CV.md using only the Python standard library.

The output intentionally uses PDF base fonts and uncompressed ASCII content streams.
That keeps the document selectable, deterministic, dependency-free, and suitable for
GitHub Actions.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

PAGE_WIDTH = 595.28
PAGE_HEIGHT = 841.89
MARGIN_X = 42.0
TOP_Y = 804.0
BOTTOM_Y = 42.0
CONTENT_WIDTH = PAGE_WIDTH - 2 * MARGIN_X
ACCENT = (0.075, 0.36, 0.33)
INK = (0.075, 0.09, 0.10)
SOFT = (0.25, 0.30, 0.31)
MUTED = (0.43, 0.48, 0.49)
LINE = (0.82, 0.85, 0.84)


@dataclass(frozen=True)
class Style:
    font: str
    size: float
    leading: float
    before: float = 0.0
    after: float = 0.0
    color: tuple[float, float, float] = INK
    indent: float = 0.0
    bullet: bool = False
    keep_with_next: bool = False


STYLES = {
    "h1": Style("F2", 23.0, 26.0, before=0, after=5, color=INK, keep_with_next=True),
    "title": Style("F2", 12.0, 15.0, before=0, after=4, color=ACCENT, keep_with_next=True),
    "tagline": Style("F1", 9.2, 12.0, before=0, after=5, color=SOFT, keep_with_next=True),
    "contact": Style("F1", 7.6, 9.5, before=0, after=10, color=MUTED),
    "h2": Style("F2", 10.2, 13.0, before=11, after=5, color=ACCENT, keep_with_next=True),
    "h3": Style("F2", 10.0, 12.5, before=7, after=3, color=INK, keep_with_next=True),
    "paragraph": Style("F1", 8.45, 11.2, before=0, after=4.2, color=SOFT),
    "bullet": Style("F1", 8.25, 10.8, before=0, after=2.3, color=SOFT, indent=11, bullet=True),
    "boundary": Style("F3", 7.55, 9.8, before=2, after=4.5, color=(0.17, 0.31, 0.29), indent=7),
}


def ascii_text(value: str) -> str:
    value = value.replace("·", "|").replace("–", "-").replace("—", "-").replace("→", "->")
    normalized = unicodedata.normalize("NFKD", value)
    return normalized.encode("ascii", "ignore").decode("ascii")


def strip_markdown(value: str, include_urls: bool = False) -> str:
    def link_repl(match: re.Match[str]) -> str:
        label, url = match.group(1), match.group(2)
        return f"{label}: {url}" if include_urls else label

    value = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", link_repl, value)
    value = value.replace("**", "").replace("`", "")
    return ascii_text(value).strip()


def pdf_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def estimate_width(text: str, size: float, bold: bool = False) -> float:
    total = 0.0
    for char in text:
        if char == " ":
            factor = 0.28
        elif char in "ilI.,:;!'|":
            factor = 0.25
        elif char in "MW@%#&":
            factor = 0.82
        elif char.isupper():
            factor = 0.62
        elif char.isdigit():
            factor = 0.54
        else:
            factor = 0.49
        total += factor
    if bold:
        total *= 1.035
    return total * size


def wrap_text(text: str, style: Style, width: float) -> list[str]:
    words = text.split()
    if not words:
        return [""]
    lines: list[str] = []
    current = words[0]
    bold = style.font == "F2"
    for word in words[1:]:
        candidate = f"{current} {word}"
        if estimate_width(candidate, style.size, bold) <= width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def parse_markdown(path: Path) -> list[tuple[str, str]]:
    blocks: list[tuple[str, str]] = []
    seen_h1 = False
    seen_title = False
    seen_tagline = False
    paragraph: list[str] = []

    def flush() -> None:
        nonlocal paragraph
        if paragraph:
            text = " ".join(part.strip() for part in paragraph if part.strip())
            if text:
                kind = "boundary" if text.startswith("Current boundary:") or text.startswith("Recorded validation boundary:") else "paragraph"
                blocks.append((kind, strip_markdown(text)))
            paragraph = []

    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        if not line.strip():
            flush()
            continue
        if line.startswith("# "):
            flush()
            blocks.append(("h1", strip_markdown(line[2:])))
            seen_h1 = True
            continue
        if seen_h1 and line.startswith("**") and line.endswith("**") and not seen_title:
            flush()
            blocks.append(("title", strip_markdown(line)))
            seen_title = True
            continue
        if seen_title and not seen_tagline and not line.startswith("Sofia") and not line.startswith("["):
            flush()
            blocks.append(("tagline", strip_markdown(line)))
            seen_tagline = True
            continue
        if line.startswith("Sofia") or (seen_tagline and line.startswith("[")):
            flush()
            blocks.append(("contact", strip_markdown(line, include_urls=True)))
            continue
        if line.startswith("## "):
            flush()
            blocks.append(("h2", strip_markdown(line[3:]).upper()))
            continue
        if line.startswith("### "):
            flush()
            blocks.append(("h3", strip_markdown(line[4:])))
            continue
        if line.startswith("- "):
            flush()
            blocks.append(("bullet", strip_markdown(line[2:])))
            continue
        paragraph.append(line.strip())
    flush()
    return blocks


def text_command(text: str, style: Style, x: float, y: float) -> str:
    r, g, b = style.color
    return (
        f"BT /{style.font} {style.size:.2f} Tf {r:.3f} {g:.3f} {b:.3f} rg "
        f"1 0 0 1 {x:.2f} {y:.2f} Tm ({pdf_escape(text)}) Tj ET\n"
    )


def line_command(x1: float, y1: float, x2: float, y2: float, color=LINE, width: float = 0.55) -> str:
    r, g, b = color
    return f"q {r:.3f} {g:.3f} {b:.3f} RG {width:.2f} w {x1:.2f} {y1:.2f} m {x2:.2f} {y2:.2f} l S Q\n"


def layout(blocks: list[tuple[str, str]]) -> list[str]:
    pages: list[list[str]] = [[]]
    y = TOP_Y
    page_number = 1
    current_role: str | None = None

    def new_page(continuation: str | None = None) -> None:
        nonlocal y, page_number
        pages.append([])
        page_number += 1
        pages[-1].append(text_command("SASHO ABDULRAHIM DERAMA", Style("F2", 7.0, 8.5, color=MUTED), MARGIN_X, PAGE_HEIGHT - 28))
        pages[-1].append(line_command(MARGIN_X, PAGE_HEIGHT - 34, PAGE_WIDTH - MARGIN_X, PAGE_HEIGHT - 34, LINE, 0.45))
        if continuation:
            label = f"{continuation} (CONTINUED)"
            pages[-1].append(text_command(label, Style("F2", 8.2, 10.0, color=INK), MARGIN_X, PAGE_HEIGHT - 53))
            y = PAGE_HEIGHT - 68
        else:
            y = TOP_Y

    for index, (kind, text) in enumerate(blocks):
        style = STYLES[kind]
        if kind == "h2":
            current_role = None
        elif kind == "h3":
            current_role = text
        available_width = CONTENT_WIDTH - style.indent
        wrapped = wrap_text(text, style, available_width - (8 if style.bullet else 0))
        required = style.before + len(wrapped) * style.leading + style.after
        if style.keep_with_next and index + 1 < len(blocks):
            next_kind, next_text = blocks[index + 1]
            next_style = STYLES[next_kind]
            next_lines = wrap_text(next_text, next_style, CONTENT_WIDTH - next_style.indent)
            required += min(2, len(next_lines)) * next_style.leading + next_style.before
        if y - required < BOTTOM_Y + 18:
            continuation = current_role if current_role and kind not in {"h2", "h3"} else None
            new_page(continuation)
        y -= style.before
        if kind == "h2":
            pages[-1].append(line_command(MARGIN_X, y + 4.0, PAGE_WIDTH - MARGIN_X, y + 4.0, LINE, 0.45))
        for line_index, wrapped_line in enumerate(wrapped):
            x = MARGIN_X + style.indent
            if style.bullet:
                if line_index == 0:
                    pages[-1].append(text_command("-", Style("F2", style.size, style.leading, color=ACCENT), MARGIN_X, y))
                x += 3
            pages[-1].append(text_command(wrapped_line, style, x, y))
            y -= style.leading
        y -= style.after
        if kind == "h1":
            y -= 3

    for idx, page in enumerate(pages, start=1):
        footer_y = 24.0
        page.append(line_command(MARGIN_X, footer_y + 9, PAGE_WIDTH - MARGIN_X, footer_y + 9, LINE, 0.4))
        page.append(text_command("github.com/gonzo-max2", Style("F1", 6.5, 8, color=MUTED), MARGIN_X, footer_y))
        page.append(text_command(f"PAGE {idx} / {len(pages)}", Style("F2", 6.5, 8, color=MUTED), PAGE_WIDTH - MARGIN_X - 46, footer_y))
    return ["".join(page) for page in pages]


def build_pdf(page_streams: Iterable[str], output: Path, title: str) -> bytes:
    streams = [stream.encode("ascii") for stream in page_streams]
    page_ids = [7 + 2 * idx for idx in range(len(streams))]
    content_ids = [6 + 2 * idx for idx in range(len(streams))]
    info_id = 6 + 2 * len(streams)

    objects: dict[int, bytes] = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: f"<< /Type /Pages /Count {len(streams)} /Kids [{' '.join(f'{page_id} 0 R' for page_id in page_ids)}] >>".encode("ascii"),
        3: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        4: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>",
        5: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Oblique /Encoding /WinAnsiEncoding >>",
    }

    for page_id, content_id, stream in zip(page_ids, content_ids, streams):
        objects[content_id] = f"<< /Length {len(stream)} >>\nstream\n".encode("ascii") + stream + b"endstream"
        objects[page_id] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_WIDTH:.2f} {PAGE_HEIGHT:.2f}] "
            f"/Resources << /ProcSet [/PDF /Text] /Font << /F1 3 0 R /F2 4 0 R /F3 5 0 R >> >> "
            f"/Contents {content_id} 0 R >>"
        ).encode("ascii")

    safe_title = pdf_escape(ascii_text(title))
    objects[info_id] = (
        f"<< /Title ({safe_title}) /Author (Sasho Abdulrahim Derama) "
        f"/Subject (Senior AI Product and Systems Engineer CV) "
        f"/Creator (deterministic standard-library CV builder) >>"
    ).encode("ascii")

    output_bytes = bytearray(b"%PDF-1.4\n% deterministic-ascii-pdf\n")
    offsets = [0] * (info_id + 1)
    for obj_id in range(1, info_id + 1):
        offsets[obj_id] = len(output_bytes)
        output_bytes.extend(f"{obj_id} 0 obj\n".encode("ascii"))
        output_bytes.extend(objects[obj_id])
        output_bytes.extend(b"\nendobj\n")

    xref_offset = len(output_bytes)
    output_bytes.extend(f"xref\n0 {info_id + 1}\n".encode("ascii"))
    output_bytes.extend(b"0000000000 65535 f \n")
    for obj_id in range(1, info_id + 1):
        output_bytes.extend(f"{offsets[obj_id]:010d} 00000 n \n".encode("ascii"))
    output_bytes.extend(
        f"trailer\n<< /Size {info_id + 1} /Root 1 0 R /Info {info_id} 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    )

    output.write_bytes(output_bytes)
    return bytes(output_bytes)


def validate_pdf(data: bytes) -> None:
    if not data.startswith(b"%PDF-1.4"):
        raise RuntimeError("PDF header missing")
    if not data.rstrip().endswith(b"%%EOF"):
        raise RuntimeError("PDF EOF marker missing")
    if any(byte > 127 for byte in data):
        raise RuntimeError("PDF is not ASCII deterministic")
    if b"/Type /Page" not in data or b"xref\n" not in data:
        raise RuntimeError("Required PDF structures missing")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default="CV.md")
    parser.add_argument("--output", default="Sasho-Abdulrahim-Derama-CV.pdf")
    parser.add_argument("--manifest", default="cv-build-manifest.json")
    args = parser.parse_args()

    source = Path(args.source)
    output = Path(args.output)
    manifest = Path(args.manifest)
    blocks = parse_markdown(source)
    pages = layout(blocks)
    data = build_pdf(pages, output, "Sasho Abdulrahim Derama - Curriculum Vitae")
    validate_pdf(data)

    payload = {
        "schema": "derama.cv-build.v1",
        "source": str(source),
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "output": str(output),
        "output_sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
        "pages": len(pages),
        "generator": "scripts/build_cv_pdf.py",
        "properties": ["selectable text", "ASCII PDF", "standard PDF fonts", "dependency-free", "deterministic"],
    }
    manifest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
