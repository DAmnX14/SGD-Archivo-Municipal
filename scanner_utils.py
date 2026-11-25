"""
scanner_utils.py - Adquisición y manipulación de documentos digitalizados.

* Escaneo vía WIA (Windows Image Acquisition) usando pywin32, si hay escáner.
* Importación de PDF / JPG / PNG / TIFF / BMP y conversión automática a PDF.
* Cálculo de métricas reales (páginas, tamaño, calidad estimada en DPI).
* Rotación real de páginas con pypdf.
* Generación de PDFs de ejemplo para los datos iniciales.
"""
from __future__ import annotations

import io
import os
import sys
import uuid

from PIL import Image, ImageOps
from pypdf import PdfReader, PdfWriter

EXT_IMAGEN = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".gif", ".webp"}
EXT_PDF = {".pdf"}
A4_ANCHO_PULG = 8.27  # ancho A4 en pulgadas

# Constantes WIA
WIA_DEVICE_SCANNER = 1
WIA_FORMAT_JPEG = "{B96B3CAE-0728-11D3-9D7B-0000F81EF32E}"
WIA_INTENT_COLOR = 1


# --------------------------------------------------------------------------- #
#  Escáner WIA
# --------------------------------------------------------------------------- #
def _wia_disponible() -> bool:
    return sys.platform.startswith("win")


def estado_escaner() -> dict:
    """Detecta escáneres WIA conectados."""
    if not _wia_disponible():
        return {"conectado": False, "nombre": None,
                "mensaje": "Detección WIA disponible sólo en Windows. Puede importar un PDF o imagen."}
    try:
        import pythoncom
        import win32com.client
        pythoncom.CoInitialize()
        try:
            dm = win32com.client.Dispatch("WIA.DeviceManager")
            for i in range(1, dm.DeviceInfos.Count + 1):
                info = dm.DeviceInfos.Item(i)
                if info.Type == WIA_DEVICE_SCANNER:
                    nombre = info.Properties("Name").Value
                    return {"conectado": True, "nombre": nombre,
                            "mensaje": "Escáner conectado correctamente. Listo para digitalizar su documento."}
        finally:
            pythoncom.CoUninitialize()
    except Exception as exc:  # pywin32 ausente o servicio WIA detenido
        return {"conectado": False, "nombre": None,
                "mensaje": f"No se pudo consultar el servicio WIA ({exc.__class__.__name__}). "
                           "Puede importar un PDF o imagen desde su PC."}
    return {"conectado": False, "nombre": None,
            "mensaje": "No se detectó ningún escáner conectado. Puede importar un PDF o imagen desde su PC."}


def escanear_wia(destino_dir: str) -> str | None:
    """Abre el diálogo nativo de WIA y devuelve la ruta de la imagen adquirida.

    Devuelve None si el usuario cancela. Lanza RuntimeError si no hay WIA.
    """
    if not _wia_disponible():
        raise RuntimeError("El escaneo WIA sólo está disponible en Windows.")
    import pythoncom
    import win32com.client
    pythoncom.CoInitialize()
    try:
        dlg = win32com.client.Dispatch("WIA.CommonDialog")
        # ShowAcquireImage(DeviceType, Intent, Bias, FormatID, AlwaysSelectDevice, UseCommonUI, CancelError)
        img = dlg.ShowAcquireImage(WIA_DEVICE_SCANNER, WIA_INTENT_COLOR, 0, WIA_FORMAT_JPEG,
                                   False, True, False)
        if img is None:
            return None
        ruta = os.path.join(destino_dir, f"wia_{uuid.uuid4().hex}.jpg")
        img.SaveFile(ruta)
        return ruta
    except Exception as exc:
        # 0x80210015 = WIA_S_NO_DEVICE_AVAILABLE
        raise RuntimeError(f"No fue posible adquirir la imagen del escáner: {exc}") from exc
    finally:
        pythoncom.CoUninitialize()


# --------------------------------------------------------------------------- #
#  Conversión a PDF
# --------------------------------------------------------------------------- #
def _imagen_a_pagina_pdf(ruta_img: str) -> tuple[bytes, float]:
    """Convierte una imagen (todas sus páginas si es TIFF) a PDF. Devuelve (bytes, dpi)."""
    with Image.open(ruta_img) as im:
        paginas = []
        dpi = 0.0
        frame = 0
        while True:
            try:
                im.seek(frame)
            except EOFError:
                break
            p = ImageOps.exif_transpose(im.copy())
            if p.mode in ("RGBA", "LA", "P"):
                fondo = Image.new("RGB", p.size, "white")
                p = p.convert("RGBA")
                fondo.paste(p, mask=p.split()[-1])
                p = fondo
            elif p.mode != "RGB" and p.mode != "L":
                p = p.convert("RGB")
            ancho_px = min(p.size)  # lado corto = ancho de la hoja
            dpi = max(dpi, ancho_px / A4_ANCHO_PULG)
            paginas.append(p)
            frame += 1
        res = max(72.0, round(dpi))
        buf = io.BytesIO()
        paginas[0].save(buf, "PDF", resolution=res, save_all=True, append_images=paginas[1:])
        return buf.getvalue(), dpi


def _calidad_por_dpi(dpi: float | None) -> str:
    if dpi is None:
        return "Óptima"
    if dpi >= 200:
        return "Óptima"
    if dpi >= 140:
        return "Buena"
    return "Baja"


def _dpi_pdf(reader: PdfReader) -> float | None:
    """Estima DPI de la primera imagen de la primera página. None = vectorial/texto."""
    try:
        page = reader.pages[0]
        ancho_pt = float(page.mediabox.width)
        for img in page.images:
            w = img.image.size[0]
            return w / (ancho_pt / 72.0)
    except Exception:
        pass
    return None


def construir_pdf(rutas: list[str], destino: str, pdf_base: str | None = None) -> dict:
    """Combina PDFs e imágenes (en orden) en `destino`. Si `pdf_base` existe, se agrega al final."""
    writer = PdfWriter()
    dpis: list[float] = []
    if pdf_base and os.path.exists(pdf_base):
        writer.append(PdfReader(pdf_base))
    for r in rutas:
        ext = os.path.splitext(r)[1].lower()
        if ext in EXT_PDF:
            reader = PdfReader(r)
            if reader.is_encrypted:
                try:
                    reader.decrypt("")
                except Exception as exc:
                    raise ValueError(f"El PDF '{os.path.basename(r)}' está protegido con contraseña.") from exc
            d = _dpi_pdf(reader)
            if d:
                dpis.append(d)
            writer.append(reader)
        elif ext in EXT_IMAGEN:
            datos, dpi = _imagen_a_pagina_pdf(r)
            dpis.append(dpi)
            writer.append(PdfReader(io.BytesIO(datos)))
        else:
            raise ValueError(f"Formato no soportado: {os.path.basename(r)}")
    if len(writer.pages) == 0:
        raise ValueError("El documento no contiene páginas.")
    writer.add_metadata({"/Producer": "SGD - Jefatura de Archivo"})
    tmp = destino + ".tmp"
    with open(tmp, "wb") as fh:
        writer.write(fh)
    os.replace(tmp, destino)
    info = metricas_pdf(destino)
    if dpis:
        info["dpi"] = round(min(dpis))
        info["calidad"] = _calidad_por_dpi(min(dpis))
    return info


def metricas_pdf(ruta: str) -> dict:
    reader = PdfReader(ruta)
    tam = os.path.getsize(ruta)
    dpi = _dpi_pdf(reader)
    return {
        "paginas": len(reader.pages),
        "formato": "PDF",
        "tamano_bytes": tam,
        "tamano_mb": round(tam / (1024 * 1024), 2),
        "dpi": round(dpi) if dpi else None,
        "calidad": _calidad_por_dpi(dpi),
    }


def rotar_pdf(ruta: str, grados: int, pagina: int | None = None) -> dict:
    """Rota realmente el PDF (todas las páginas o sólo `pagina`, base 1)."""
    if grados % 90:
        raise ValueError("La rotación debe ser múltiplo de 90°.")
    reader = PdfReader(ruta)
    writer = PdfWriter()
    for i, page in enumerate(reader.pages, start=1):
        if pagina is None or i == pagina:
            page.rotate(grados)
        writer.add_page(page)
    tmp = ruta + ".tmp"
    with open(tmp, "wb") as fh:
        writer.write(fh)
    os.replace(tmp, ruta)
    return metricas_pdf(ruta)


# --------------------------------------------------------------------------- #
#  PDF de ejemplo (seed)
# --------------------------------------------------------------------------- #
def generar_pdf_ejemplo(ruta: str, tipo: str, numero: str, direccion: str,
                        descripcion: str, paginas: int = 1) -> None:
    """Genera un documento con apariencia de acto administrativo escaneado."""
    from reportlab.lib.colors import HexColor
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(ruta, pagesize=A4)
    w, h = A4
    c.setTitle(f"{tipo} {numero}")
    for p in range(1, paginas + 1):
        c.setFillColor(HexColor("#FBFAF5"))
        c.rect(0, 0, w, h, stroke=0, fill=1)
        c.setFillColor(HexColor("#0A367A"))
        c.setFont("Helvetica-Bold", 11)
        c.drawCentredString(w / 2, h - 60, "MUNICIPALIDAD DE LIBERTADOR GENERAL SAN MARTÍN")
        c.setFont("Helvetica", 9)
        c.drawCentredString(w / 2, h - 74, f"Dirección de {direccion}")
        c.setStrokeColor(HexColor("#0A367A"))
        c.line(60, h - 84, w - 60, h - 84)
        c.setFillColor(HexColor("#111111"))
        if p == 1:
            c.setFont("Helvetica-Bold", 18)
            c.drawCentredString(w / 2, h - 130, f"{tipo.upper()} N° {numero}")
            c.setFont("Helvetica-Oblique", 10)
            c.drawCentredString(w / 2, h - 150, "Libertador General San Martín, Jujuy")
            c.setFont("Helvetica-Bold", 11)
            c.drawString(70, h - 195, "VISTO:")
            c.setFont("Helvetica", 11)
            txt = c.beginText(70, h - 215)
            txt.setLeading(16)
            for linea in _envolver(f"El expediente relativo a: {descripcion}; y la normativa municipal "
                                   "vigente en la materia, y", 85):
                txt.textLine(linea)
            c.drawText(txt)
            c.setFont("Helvetica-Bold", 11)
            c.drawString(70, h - 290, "CONSIDERANDO:")
            y = h - 310
        else:
            y = h - 120
        c.setFont("Helvetica", 11)
        parrafo = ("Que corresponde dictar el instrumento legal pertinente a fin de dar curso a lo "
                   "solicitado, conforme a las facultades conferidas por la Carta Orgánica Municipal y "
                   "las ordenanzas en vigencia. Que han tomado intervención las áreas competentes sin "
                   "formular objeciones. Por ello, en uso de las atribuciones conferidas, ")
        txt = c.beginText(70, y)
        txt.setLeading(16)
        for linea in _envolver(parrafo * (2 if p > 1 else 1), 85):
            txt.textLine(linea)
        c.drawText(txt)
        if p == paginas:
            c.setFont("Helvetica-Bold", 11)
            c.drawCentredString(w / 2, 250, f"EL {('INTENDENTE MUNICIPAL' if tipo == 'Decreto' else 'DIRECTOR')}")
            c.drawCentredString(w / 2, 234, {"Decreto": "DECRETA:", "Ordenanza": "ORDENA:",
                                              "Disposición": "DISPONE:"}.get(tipo, "RESUELVE:"))
            c.line(w / 2 - 90, 140, w / 2 + 90, 140)
            c.setFont("Helvetica", 9)
            c.drawCentredString(w / 2, 126, "Firma y sello")
            # sello circular
            c.setStrokeColor(HexColor("#2B4FA8"))
            c.setLineWidth(1.5)
            c.circle(w - 140, 150, 38)
            c.setFont("Helvetica-Bold", 7)
            c.setFillColor(HexColor("#2B4FA8"))
            c.drawCentredString(w - 140, 154, "MUNICIPALIDAD")
            c.drawCentredString(w - 140, 144, "L.G.S.M.")
        c.setFillColor(HexColor("#777777"))
        c.setFont("Helvetica", 8)
        c.drawRightString(w - 60, 40, f"Página {p} de {paginas}")
        c.showPage()
    c.save()


def _envolver(texto: str, ancho: int) -> list[str]:
    import textwrap
    return textwrap.wrap(texto, ancho)


def tmp_nombre(base_dir: str, ext: str = ".pdf") -> str:
    return os.path.join(base_dir, f"{uuid.uuid4().hex}{ext}")
