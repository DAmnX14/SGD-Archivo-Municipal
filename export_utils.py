"""
export_utils.py - Comprobantes, reportes (PDF / Excel / PNG) y respaldos ZIP.
"""
from __future__ import annotations

import base64
import io
import os
import sqlite3
import zipfile
from datetime import datetime

from openpyxl import Workbook
from openpyxl.chart import BarChart, PieChart, Reference
from openpyxl.chart.label import DataLabelList
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from reportlab.graphics.barcode import code128, qr
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (Image as RLImage, Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

AZUL = colors.HexColor("#0A367A")
AZUL_VIVO = colors.HexColor("#0056D2")
CELESTE = colors.HexColor("#EBF3FA")
INSTITUCION = "Municipalidad de Libertador General San Martín"
SISTEMA = "Sistema de Gestión Documental - Jefatura de Archivo"


def _decodificar_imagen(data_url: str) -> bytes:
    if "," in data_url:
        data_url = data_url.split(",", 1)[1]
    return base64.b64decode(data_url)


def _fmt_fecha(iso: str | None, formato: str = "DD/MM/AAAA") -> str:
    if not iso:
        return "-"
    try:
        d = datetime.strptime(iso[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return iso
    patron = {"DD/MM/AAAA": "%d/%m/%Y", "AAAA-MM-DD": "%Y-%m-%d", "DD-MM-AAAA": "%d-%m-%Y"}
    return d.strftime(patron.get(formato, "%d/%m/%Y") + (" %H:%M" if len(iso) > 10 else ""))


def _fmt_tamano(b: int) -> str:
    return f"{b / 1048576:.2f} MB" if b >= 1048576 else f"{b / 1024:.1f} KB"


# --------------------------------------------------------------------------- #
#  Comprobante de registro
# --------------------------------------------------------------------------- #
def generar_comprobante(doc: dict, destino: str, logo: str | None = None,
                        formato_fecha: str = "DD/MM/AAAA") -> str:
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(destino, pagesize=A4)
    w, h = A4
    c.setTitle(f"Comprobante {doc['nro_registro']}")
    # Encabezado
    c.setFillColor(AZUL)
    c.rect(0, h - 95, w, 95, stroke=0, fill=1)
    if logo and os.path.exists(logo):
        c.drawImage(ImageReader(logo), 30, h - 85, 75, 75, mask="auto")
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 15)
    c.drawString(120, h - 45, INSTITUCION)
    c.setFont("Helvetica", 10)
    c.drawString(120, h - 63, SISTEMA)
    c.drawString(120, h - 78, "Comprobante de Registro de Documento Digitalizado")

    # Número de registro destacado
    c.setFillColor(CELESTE)
    c.roundRect(40, h - 200, w - 80, 85, 10, stroke=0, fill=1)
    c.setFillColor(AZUL)
    c.setFont("Helvetica", 10)
    c.drawString(60, h - 138, "N° DE REGISTRO")
    c.setFont("Helvetica-Bold", 30)
    c.drawString(60, h - 175, doc["nro_registro"])
    bc = code128.Code128(doc["nro_registro"], barHeight=40, barWidth=1.2)
    bc.drawOn(c, w - 60 - bc.width, h - 185)

    # Tabla de datos
    filas = [
        ("Tipo de documento", doc.get("tipo", "")),
        ("Número", doc.get("numero", "")),
        ("Año", str(doc.get("anio", ""))),
        ("Dirección", doc.get("direccion", "")),
        ("Descripción", doc.get("descripcion") or "-"),
        ("Ubicación física", doc.get("ubicacion_fisica") or "-"),
        ("Etiquetas", ", ".join(doc.get("etiquetas", [])) or "-"),
        ("Páginas", str(doc.get("paginas", 0))),
        ("Tamaño", _fmt_tamano(doc.get("tamano_bytes") or 0)),
        ("Archivo digital", os.path.basename(doc.get("archivo_path") or "") or "-"),
        ("Fecha de carga", _fmt_fecha(doc.get("fecha_carga"), formato_fecha)),
        ("Registrado por", doc.get("usuario") or "-"),
    ]
    estilo = ParagraphStyle("v", fontName="Helvetica", fontSize=10, leading=13)
    t = Table([[Paragraph(f"<b>{k}</b>", estilo), Paragraph(str(v), estilo)] for k, v in filas],
              colWidths=[45 * mm, w - 80 - 45 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F3F7FC")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#C9D6E8")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    _, th = t.wrap(w - 80, h)
    t.drawOn(c, 40, h - 225 - th)

    # QR + firma
    y_qr = h - 250 - th - 110
    q = qr.QrCodeWidget(f"SGD-LGSM|{doc['nro_registro']}|{doc.get('tipo')} {doc.get('numero')}|"
                        f"{doc.get('direccion')}")
    b = q.getBounds()
    d = Drawing(95, 95, transform=[95 / (b[2] - b[0]), 0, 0, 95 / (b[3] - b[1]), 0, 0])
    d.add(q)
    d.drawOn(c, 40, y_qr)
    c.setFillColor(colors.HexColor("#555555"))
    c.setFont("Helvetica", 8)
    c.drawString(40, y_qr - 10, "Código de verificación")
    c.setStrokeColor(colors.HexColor("#999999"))
    c.line(w - 240, y_qr + 30, w - 50, y_qr + 30)
    c.setFont("Helvetica", 9)
    c.drawCentredString(w - 145, y_qr + 16, "Firma y sello - Jefatura de Archivo")

    c.setFillColor(colors.HexColor("#888888"))
    c.setFont("Helvetica", 8)
    c.drawString(40, 30, f"Emitido el {datetime.now().strftime('%d/%m/%Y %H:%M')} - {SISTEMA}")
    c.showPage()
    c.save()
    return destino


# --------------------------------------------------------------------------- #
#  Reportes
# --------------------------------------------------------------------------- #
def _tabla_rl(encabezado: list[str], datos: list[list], anchos: list[float]) -> Table:
    estilo = ParagraphStyle("c", fontName="Helvetica", fontSize=8, leading=10)
    cuerpo = [[Paragraph(str(x), estilo) for x in fila] for fila in datos]
    t = Table([encabezado] + cuerpo, colWidths=anchos, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), AZUL),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F3F7FC")]),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#C9D6E8")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return t


def exportar_reporte_pdf(reporte: dict, destino: str, imagenes: dict | None = None,
                         filtros_txt: str = "", logo: str | None = None,
                         formato_fecha: str = "DD/MM/AAAA") -> str:
    imagenes = imagenes or {}
    pag = landscape(A4)
    doc = SimpleDocTemplate(destino, pagesize=pag, leftMargin=15 * mm, rightMargin=15 * mm,
                            topMargin=30 * mm, bottomMargin=15 * mm,
                            title="Reporte de Gestión Documental", author=INSTITUCION)
    ss = getSampleStyleSheet()
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], textColor=AZUL, spaceBefore=6, spaceAfter=6)
    normal = ss["Normal"]
    ancho = pag[0] - 30 * mm

    def encabezado(cv, _doc):
        cv.saveState()
        cv.setFillColor(AZUL)
        cv.rect(0, pag[1] - 22 * mm, pag[0], 22 * mm, stroke=0, fill=1)
        if logo and os.path.exists(logo):
            cv.drawImage(ImageReader(logo), 12 * mm, pag[1] - 19 * mm, 16 * mm, 16 * mm, mask="auto")
        cv.setFillColor(colors.white)
        cv.setFont("Helvetica-Bold", 13)
        cv.drawString(32 * mm, pag[1] - 11 * mm, INSTITUCION)
        cv.setFont("Helvetica", 9)
        cv.drawString(32 * mm, pag[1] - 16.5 * mm, "Reporte de Gestión Documental - Jefatura de Archivo")
        cv.drawRightString(pag[0] - 15 * mm, pag[1] - 11 * mm, datetime.now().strftime("%d/%m/%Y %H:%M"))
        cv.setFillColor(colors.HexColor("#888888"))
        cv.setFont("Helvetica", 8)
        cv.drawRightString(pag[0] - 15 * mm, 8 * mm, f"Página {cv.getPageNumber()}")
        cv.restoreState()

    k = reporte["kpis"]
    story = [Paragraph(f"<b>Filtros aplicados:</b> {filtros_txt or 'Sin filtros'}", normal), Spacer(1, 6)]
    kpi = Table([["Total digitalizados", "Tasa de digitalización", "Direcciones registradas", "Última carga"],
                 [str(k["total"]), f"{k['tasa']}%", str(k["direcciones"]),
                  f"{_fmt_fecha(k['ultima_fecha'], formato_fecha)}\n{k.get('ultimo_registro') or ''}"]],
                colWidths=[ancho / 4] * 4)
    kpi.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), AZUL), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"), ("FONTSIZE", (0, 1), (-1, 1), 15),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"), ("BACKGROUND", (0, 1), (-1, 1), CELESTE),
        ("TEXTCOLOR", (0, 1), (-1, 1), AZUL), ("TOPPADDING", (0, 1), (-1, 1), 10),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 10), ("BOX", (0, 0), (-1, -1), 0.5, AZUL),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.white),
        ("FONTSIZE", (3, 1), (3, 1), 11), ("VALIGN", (0, 1), (-1, 1), "MIDDLE"),
    ]))
    story += [kpi, Spacer(1, 10)]

    graf = []
    for clave in ("barras", "torta"):
        if imagenes.get(clave):
            raw = _decodificar_imagen(imagenes[clave])
            ir = ImageReader(io.BytesIO(raw))
            iw, ih = ir.getSize()
            gw = ancho / 2 - 5 * mm
            graf.append(RLImage(io.BytesIO(raw), width=gw, height=min(gw * ih / iw, 80 * mm)))
    if graf:
        tg = Table([graf], colWidths=[ancho / 2] * len(graf))
        tg.setStyle(TableStyle([("ALIGN", (0, 0), (-1, -1), "CENTER")]))
        story += [Paragraph("Gráficos", h2), tg]

    tot = max(1, k["total"])
    story += [Paragraph("Documentos por Dirección", h2),
              _tabla_rl(["Dirección", "Cantidad", "%"],
                        [[r["nombre"], r["cantidad"], f"{r['cantidad'] * 100 / tot:.1f}%"]
                         for r in reporte["por_direccion"]], [ancho * .6, ancho * .2, ancho * .2]),
              Paragraph("Tipos de Documentos", h2),
              _tabla_rl(["Tipo", "Cantidad", "%"],
                        [[r["nombre"], r["cantidad"], f"{r['cantidad'] * 100 / tot:.1f}%"]
                         for r in reporte["por_tipo"]], [ancho * .6, ancho * .2, ancho * .2]),
              Paragraph("Detalle de documentos", h2),
              _tabla_rl(["N° Registro", "Documento", "Dirección", "Año", "Descripción", "Fecha de carga"],
                        [[d["nro_registro"], f"{d['tipo']} {d['numero']}", d["direccion"], d["anio"],
                          d.get("descripcion") or "", _fmt_fecha(d["fecha_carga"], formato_fecha)]
                         for d in reporte["documentos"]],
                        [ancho * .12, ancho * .16, ancho * .14, ancho * .06, ancho * .36, ancho * .16])]
    doc.build(story, onFirstPage=encabezado, onLaterPages=encabezado)
    return destino


def exportar_reporte_excel(reporte: dict, destino: str, filtros_txt: str = "",
                           formato_fecha: str = "DD/MM/AAAA") -> str:
    wb = Workbook()
    cab_fill = PatternFill("solid", fgColor="0A367A")
    cab_font = Font(bold=True, color="FFFFFF")
    borde = Border(*(Side(style="thin", color="C9D6E8"),) * 4)

    def hoja_tabla(ws, fila0, encabezado, datos):
        for j, txt in enumerate(encabezado, 1):
            c = ws.cell(row=fila0, column=j, value=txt)
            c.fill, c.font, c.border = cab_fill, cab_font, borde
            c.alignment = Alignment(horizontal="center")
        for i, fila in enumerate(datos, fila0 + 1):
            for j, v in enumerate(fila, 1):
                c = ws.cell(row=i, column=j, value=v)
                c.border = borde
        for j in range(1, len(encabezado) + 1):
            largo = max([len(str(encabezado[j - 1]))] + [len(str(f[j - 1])) for f in datos] or [10])
            ws.column_dimensions[get_column_letter(j)].width = min(60, largo + 3)

    k = reporte["kpis"]
    ws = wb.active
    ws.title = "Resumen"
    ws["A1"] = INSTITUCION
    ws["A1"].font = Font(bold=True, size=14, color="0A367A")
    ws["A2"] = "Reporte de Gestión Documental - Jefatura de Archivo"
    ws["A3"] = f"Generado: {datetime.now().strftime('%d/%m/%Y %H:%M')}   Filtros: {filtros_txt or 'Sin filtros'}"
    hoja_tabla(ws, 5, ["Indicador", "Valor"], [
        ["Total de documentos digitalizados", k["total"]],
        ["Tasa de digitalización (%)", k["tasa"]],
        ["Direcciones registradas", k["direcciones"]],
        ["Última carga", f"{_fmt_fecha(k['ultima_fecha'], formato_fecha)} {k.get('ultimo_registro') or ''}"],
    ])

    def hoja_grafico(nombre, filas, tipo):
        w = wb.create_sheet(nombre)
        hoja_tabla(w, 1, [nombre.split(" ")[-1].capitalize(), "Cantidad"],
                   [[r["nombre"], r["cantidad"]] for r in filas])
        if not filas:
            return
        n = len(filas) + 1
        datos = Reference(w, min_col=2, min_row=1, max_row=n)
        cats = Reference(w, min_col=1, min_row=2, max_row=n)
        ch = BarChart() if tipo == "bar" else PieChart()
        ch.title = nombre
        ch.add_data(datos, titles_from_data=True)
        ch.set_categories(cats)
        if tipo == "bar":
            ch.y_axis.title = "Documentos"
            ch.legend = None
            ch.varyColors = True
        else:
            ch.dataLabels = DataLabelList()
            ch.dataLabels.showPercent = True
        ch.height, ch.width = 9, 16
        w.add_chart(ch, "D2")

    hoja_grafico("Por Dirección", reporte["por_direccion"], "bar")
    hoja_grafico("Por Tipo", reporte["por_tipo"], "pie")

    wd = wb.create_sheet("Documentos")
    hoja_tabla(wd, 1, ["N° Registro", "Tipo", "Número", "Dirección", "Año", "Descripción",
                       "Ubicación física", "Etiquetas", "Páginas", "Estado", "Fecha de carga"],
               [[d["nro_registro"], d["tipo"], d["numero"], d["direccion"], d["anio"],
                 d.get("descripcion") or "", d.get("ubicacion_fisica") or "",
                 ", ".join(d.get("etiquetas", [])), d.get("paginas") or 0, d.get("estado"),
                 _fmt_fecha(d["fecha_carga"], formato_fecha)] for d in reporte["documentos"]])
    wd.freeze_panes = "A2"
    wd.auto_filter.ref = wd.dimensions
    wb.save(destino)
    return destino


def guardar_png(data_url: str, destino: str) -> str:
    with open(destino, "wb") as fh:
        fh.write(_decodificar_imagen(data_url))
    return destino


# --------------------------------------------------------------------------- #
#  Respaldo
# --------------------------------------------------------------------------- #
def crear_respaldo(db_path: str, repo_dir: str, backup_dir: str) -> dict:
    """Copia consistente de SQLite (API backup) + PDFs en un ZIP con fecha y hora."""
    os.makedirs(backup_dir, exist_ok=True)
    marca = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    destino = os.path.join(backup_dir, f"respaldo_{marca}.zip")
    copia_db = os.path.join(backup_dir, f".tmp_{marca}.db")
    origen = sqlite3.connect(db_path)
    copia = sqlite3.connect(copia_db)
    try:
        origen.backup(copia)
    finally:
        copia.close()
        origen.close()
    n_pdf = 0
    try:
        with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            z.write(copia_db, "archivo_municipal.db")
            for raiz, _, archivos in os.walk(repo_dir):
                for a in archivos:
                    ruta = os.path.join(raiz, a)
                    z.write(ruta, os.path.join("repositorio_pdf", os.path.relpath(ruta, repo_dir)))
                    n_pdf += 1
    finally:
        os.remove(copia_db)
    return {"archivo": destino, "tamano_bytes": os.path.getsize(destino), "archivos_pdf": n_pdf}
