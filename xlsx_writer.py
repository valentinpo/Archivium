# -*- coding: utf-8 -*-
"""Минимальный генератор .xlsx на стандартной библиотеке Python.

XLSX — это ZIP-архив с набором XML-документов OOXML. Мы создаём ровно тот
минимальный набор, который понимает Excel и LibreOffice, без внешних
зависимостей (без openpyxl/pandas).

Возможности:
  - несколько листов с заголовками и данными;
  - автоширина колонок (приблизительная по длине текста);
  - числа и текст, даты как текст.
"""
import os
import time
import zipfile
from xml.sax.saxutils import escape, quoteattr
from datetime import datetime


def _col_name(idx):
    """0 -> 'A', 25 -> 'Z', 26 -> 'AA'."""
    name = ""
    idx += 1
    while idx:
        idx, rem = divmod(idx - 1, 26)
        name = chr(65 + rem) + name
    return name


class XlsxSheet:
    def __init__(self, title):
        # Excel требует, чтобы имя листа было <=31 символа и без спецсимволов
        clean = "".join(c for c in title if c.isalnum() or c in " _-")
        self.title = (clean or "Sheet")[:31]
        self.rows = []  # list[list] — первая строка заголовки


class XlsxWriter:
    def __init__(self, path):
        self.path = path
        self.sheets = []

    def add_sheet(self, title):
        s = XlsxSheet(title)
        self.sheets.append(s)
        return s

    # ------------------------------------------------------------------
    @staticmethod
    def _cell_xml(value):
        if value is None:
            return '<c/>'
        if isinstance(value, bool):
            return '<c t="b"><v>%d</v></c>' % (1 if value else 0)
        if isinstance(value, (int, float)):
            return '<c><v>%s</v></c>' % value
        return '<c t="inlineStr"><is><t xml:space="preserve">%s</t></is></c>' % escape(str(value))

    def _sheet_xml(self, sheet):
        parts = [
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">',
            '<sheetData>',
        ]
        for r in sheet.rows:
            cells = "".join(self._cell_xml(v) for v in r)
            parts.append('<row>%s</row>' % cells)
        parts.append('</sheetData>')
        parts.append('</worksheet>')
        return "".join(parts)

    def _col_widths_xml(self, sheet):
        # грубый подсчёт ширины
        if not sheet.rows:
            return ""
        ncols = max(len(r) for r in sheet.rows)
        widths = []
        for c in range(ncols):
            maxlen = 0
            for r in sheet.rows:
                if c < len(r) and r[c] is not None:
                    # числа: +2; латиница ~1, кириллица ~1.6 условных
                    s = str(r[c])
                    L = 0.0
                    for ch in s:
                        L += 2.0 if ord(ch) > 127 else 1.0
                    maxlen = max(maxlen, L)
            widths.append(max(10, maxlen + 2))
        cols = "".join(
            '<col min="%d" max="%d" width="%.2f" customWidth="1"/>'
            % (i + 1, i + 1, widths[i])
            for i in range(ncols)
        )
        return '<cols>%s</cols>' % cols

    # ------------------------------------------------------------------
    def save(self):
        """Собрать ZIP-архив .xlsx."""
        n = len(self.sheets)
        sheet_overrides = "".join(
            '<Override PartName="/xl/worksheets/sheet%d.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' % (i + 1)
            for i in range(n)
        )
        # [Content_Types].xml
        content_types = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            + sheet_overrides +
            '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
            '<Override PartName="/xl/_rels/workbook.xml.rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
            '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>'
            '</Types>'
        )

        # workbook.xml
        sheet_refs = "".join(
            '<sheet name=%s sheetId="%d" r:id="rId%d"/>'
            % (quoteattr(s.title), i + 1, i + 1)
            for i, s in enumerate(self.sheets)
        )
        workbook_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets>%s</sheets></workbook>' % sheet_refs
        )

        # workbook.xml.rels
        rels = []
        for i in range(len(self.sheets)):
            rels.append(
                '<Relationship Id="rId%d" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet%d.xml"/>' % (i + 1, i + 1)
            )
        rels.append(
            '<Relationship Id="rId%d" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>' % (len(self.sheets) + 1)
        )
        workbook_rels = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">%s</Relationships>' % "".join(rels)
        )

        # styles.xml (минимальный — стиль 0 по умолчанию)
        styles_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts>'
            '<fills count="1"><fill><patternFill patternType="none"/></fill></fills>'
            '<borders count="1"><border/></borders>'
            '<cellStyleXfs count="1"><xf/></cellStyleXfs>'
            '<cellXfs count="1"><xf xfId="0"/></cellXfs>'
            '</styleSheet>'
        )

        core_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
            'xmlns:dcmitype="http://purl.org/dc/dcmitype/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
            '<dc:title>Archivium export</dc:title>'
            '<cp:lastModifiedBy>Archivium</cp:lastModifiedBy>'
            '<dcterms:created xsi:type="dcterms:W3CDTF">%s</dcterms:created>'
            '</cp:coreProperties>' % datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        )

        app_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" '
            'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">'
            '<Application>Archivium</Application>'
            '</Properties>'
        )

        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        with zipfile.ZipFile(self.path, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("[Content_Types].xml", content_types)
            z.writestr("docProps/core.xml", core_xml)
            z.writestr("docProps/app.xml", app_xml)
            z.writestr("xl/workbook.xml", workbook_xml)
            z.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
            z.writestr("xl/styles.xml", styles_xml)
            for i, s in enumerate(self.sheets):
                sheet_xml = (
                    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                    '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                    + self._col_widths_xml(s)
                    + '<sheetData>'
                )
                for r in s.rows:
                    cells = "".join(self._cell_xml(v) for v in r)
                    sheet_xml += '<row>%s</row>' % cells
                sheet_xml += '</sheetData></worksheet>'
                z.writestr("xl/worksheets/sheet%d.xml" % (i + 1), sheet_xml)
        return self.path