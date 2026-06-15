"""Generate output schema JSON from an Excel workbook header row."""

from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import typer

app = typer.Typer(help="Generate schema JSON from an Excel file")

XML_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
REL_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"


def _to_snake_case(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip().lower())
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    return normalized or "field"


def _guess_field_type(header: str) -> str:
    text = header.lower()
    if any(tok in text for tok in ["amount", "value", "total", "balance", "cost"]):
        return "number"
    return "string"


def _load_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []

    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    shared: list[str] = []
    for item in root.findall(f"{XML_NS}si"):
        parts = [node.text or "" for node in item.iter(f"{XML_NS}t")]
        shared.append("".join(parts))
    return shared


def _get_first_sheet_path(archive: zipfile.ZipFile) -> str:
    wb = ET.fromstring(archive.read("xl/workbook.xml"))
    rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    rel_map = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rels}

    first_sheet = wb.find(f"{XML_NS}sheets/{XML_NS}sheet")
    if first_sheet is None:
        raise ValueError("No worksheet found in workbook")

    rel_id = first_sheet.attrib.get(f"{REL_NS}id")
    if not rel_id:
        raise ValueError("Worksheet relationship id is missing")

    target = rel_map.get(rel_id)
    if not target:
        raise ValueError("Worksheet relationship target is missing")

    if not target.startswith("worksheets/"):
        target = f"worksheets/{target.split('/')[-1]}"
    return f"xl/{target}"


def _read_cell_text(cell: ET.Element, shared_strings: list[str]) -> str:
    cell_type = cell.attrib.get("t", "")

    if cell_type == "inlineStr":
        t_node = cell.find(f"{XML_NS}is/{XML_NS}t")
        return (t_node.text or "").strip() if t_node is not None else ""

    value_node = cell.find(f"{XML_NS}v")
    if value_node is None or value_node.text is None:
        return ""

    raw_value = value_node.text.strip()
    if cell_type == "s" and raw_value.isdigit():
        idx = int(raw_value)
        if 0 <= idx < len(shared_strings):
            return shared_strings[idx].strip()
    return raw_value


def _read_headers_from_xlsx(xlsx_path: Path) -> list[str]:
    with zipfile.ZipFile(xlsx_path) as archive:
        shared_strings = _load_shared_strings(archive)
        sheet_path = _get_first_sheet_path(archive)
        worksheet = ET.fromstring(archive.read(sheet_path))
        first_row = worksheet.find(f"{XML_NS}sheetData/{XML_NS}row")

        if first_row is None:
            raise ValueError("Worksheet is empty")

        headers: list[str] = []
        for cell in first_row.findall(f"{XML_NS}c"):
            value = _read_cell_text(cell, shared_strings)
            if value:
                headers.append(value)

        if not headers:
            raise ValueError("No headers found in first row")

        return headers


@app.command("generate")
def generate_schema(
    input_file: Path = typer.Option(..., "--input-file", exists=True, dir_okay=False),
    output_schema: Path = typer.Option(
        "./schemas/output_schema.generated.json", "--output-schema"
    ),
    schema_name: str = typer.Option("generated_output", "--schema-name"),
) -> None:
    """Generate schema JSON using first-row headers from an XLSX file."""
    headers = _read_headers_from_xlsx(input_file)
    seen_names: dict[str, int] = {}
    fields: list[dict] = []

    for header in headers:
        field_name = _to_snake_case(header)
        if field_name in seen_names:
            seen_names[field_name] += 1
            field_name = f"{field_name}_{seen_names[field_name]}"
        else:
            seen_names[field_name] = 1

        fields.append(
            {
                "name": field_name,
                "type": _guess_field_type(header),
                "required": False,
                "aliases": [header.lower(), header],
            }
        )

    schema = {"schema_name": schema_name, "fields": fields}

    output_schema.parent.mkdir(parents=True, exist_ok=True)
    output_schema.write_text(json.dumps(schema, indent=2), encoding="utf-8")

    typer.secho(f"Schema written to: {output_schema}", fg=typer.colors.GREEN)
    typer.echo(f"Fields detected: {len(fields)}")
    for field in fields:
        typer.echo(f"- {field['name']} ({field['type']})")


if __name__ == "__main__":
    app()
