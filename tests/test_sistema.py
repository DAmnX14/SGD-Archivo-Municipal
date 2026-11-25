"""Pruebas de punta a punta del backend (sin interfaz gráfica)."""
import base64
import io
import os
import zipfile

import pytest
from PIL import Image
from pypdf import PdfReader

import app
import database as dbm
import export_utils as exp


@pytest.fixture(scope="module")
def api():
    dbm.inicializar()
    return app.Api()


def ok(r):
    assert r["ok"], r.get("error")
    return r["data"]


def ids(api):
    c = ok(api.catalogos())
    d = next(x["id"] for x in c["direcciones"] if x["nombre"] == "Comercio")
    t = next(x["id"] for x in c["tipos"] if x["nombre"] == "Decreto")
    return d, t


def imagen(tmp_path, nombre="hoja.jpg", size=(2480, 3508)):
    ruta = tmp_path / nombre
    Image.new("RGB", size, "white").save(ruta, dpi=(300, 300))
    return str(ruta)


def test_seed(api):
    d = ok(api.dashboard())
    assert d["total"] == 55 and d["pendientes"] == 1
    r = ok(api.reporte({}))
    assert r["kpis"]["tasa"] == 98
    assert ok(api.siguiente_registro()).endswith("-000245")
    assert any(x["numero"].startswith("243/") for x in ok(api.consultar({"texto": "habilitación"})))


def test_flujo_carga_completo(api, tmp_path):
    info = ok(api.importar_archivo(False, [imagen(tmp_path)]))
    assert info["paginas"] == 1 and info["calidad"] == "Óptima" and info["dpi"] == 300
    info = ok(api.importar_archivo(True, [imagen(tmp_path, "h2.png", (1240, 1754))]))
    assert info["paginas"] == 2
    ok(api.rotar(90, 1))
    d, t = ids(api)
    doc = ok(api.guardar_documento({"direccion_id": d, "tipo_id": t, "numero": "999/2026", "anio": 2026,
                                    "descripcion": "Prueba CI", "ubicacion_fisica": "Caja 1",
                                    "etiquetas": ["ci", "urgente"]}))
    assert doc["nro_registro"].endswith("-000245")
    ruta = dbm.ruta_absoluta(doc["archivo_path"])
    assert ruta.endswith(os.path.join("Comercio", "Decreto_999_2026.pdf"))
    pdf = PdfReader(ruta)
    assert len(pdf.pages) == 2 and pdf.pages[0].get("/Rotate") == 90
    assert doc["etiquetas"] == ["ci", "urgente"]
    # duplicado
    ok(api.importar_archivo(False, [imagen(tmp_path)]))
    r = api.guardar_documento({"direccion_id": d, "tipo_id": t, "numero": "999/2026", "anio": 2026})
    assert not r["ok"] and "Ya existe" in r["error"]
    ok(api.descartar_escaneo())
    comp = ok(api.imprimir_comprobante(doc["id"], False))
    assert len(PdfReader(comp).pages) == 1


def test_validaciones(api):
    r = api.guardar_documento({"numero": "1"})
    assert not r["ok"]
    r = api.importar_archivo(False, [__file__])
    assert not r["ok"] and "Formato no soportado" in r["error"]


def test_exportaciones(api, tmp_path):
    rep = api._reporte({"periodo": "anio"})
    buf = io.BytesIO()
    Image.new("RGB", (600, 300), "blue").save(buf, "PNG")
    img = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    exp.exportar_reporte_pdf(rep, str(tmp_path / "r.pdf"), {"barras": img, "torta": img}, "x", app.LOGO_PNG)
    exp.exportar_reporte_excel(rep, str(tmp_path / "r.xlsx"))
    exp.guardar_png(img, str(tmp_path / "r.png"))
    assert PdfReader(str(tmp_path / "r.pdf")).pages
    import openpyxl
    assert openpyxl.load_workbook(tmp_path / "r.xlsx").sheetnames == ["Resumen", "Por Dirección", "Por Tipo", "Documentos"]


def test_configuracion_y_respaldo(api):
    ok(api.guardar_usuario({"usuario": "ci", "nombre": "CI", "rol": "Consulta", "password": "1234"}))
    assert any(u["usuario"] == "ci" for u in ok(api.usuarios()))
    assert not api.eliminar_categoria("direcciones", 1)["ok"]  # tiene documentos
    cat = ok(api.guardar_categoria("tipos", {"nombre": "Acta"}))
    acta = next(x for x in cat["tipos"] if x["nombre"] == "Acta")
    ok(api.eliminar_categoria("tipos", acta["id"]))
    assert ok(api.guardar_preferencias({"tema": "oscuro", "formato_fecha": "AAAA-MM-DD"}))["tema"] == "oscuro"
    res = ok(api.realizar_respaldo())
    with zipfile.ZipFile(res["archivo"]) as z:
        assert "archivo_municipal.db" in z.namelist()
        assert sum(n.endswith(".pdf") for n in z.namelist()) == res["archivos_pdf"] > 50
    assert ok(api.respaldos())[0]["existe"]


def test_escaner_no_falla(api):
    e = ok(api.estado_escaner())
    assert set(e) == {"conectado", "nombre", "mensaje"}
