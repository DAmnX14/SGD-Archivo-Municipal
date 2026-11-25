"""
app.py - Punto de entrada del "Sistema de Gestión Documental - Jefatura de Archivo".
Municipalidad de Libertador General San Martín.

Arquitectura:
  * Servidor HTTP local (127.0.0.1, puerto aleatorio) que sirve la interfaz
    (templates/ + static/) y los PDF del repositorio protegidos con token.
  * Ventana nativa pywebview (WebView2 en Windows) maximizada, sin barra de navegador.
  * Clase `Api` expuesta a JavaScript (window.pywebview.api.*).

Uso:
  python app.py               -> aplicación de escritorio
  python app.py --navegador   -> modo desarrollo en el navegador (API vía HTTP)
"""
from __future__ import annotations

import functools
import json
import mimetypes
import os
import secrets
import shutil
import subprocess
import sys
import threading
import traceback
import webbrowser
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

import database as dbm
import export_utils as exp
import scanner_utils as scn

TITULO = "Sistema de Gestión Documental - Jefatura de Archivo"
TOKEN = secrets.token_urlsafe(24)
LOGO_PNG = os.path.join(dbm.RESOURCE_DIR, "static", "img", "logo_archivo.png")
ICONO = os.path.join(dbm.RESOURCE_DIR, "static", "img", "logo_archivo.ico")

try:
    import webview  # pywebview
except ImportError:  # permite ejecutar --navegador / pruebas sin pywebview
    webview = None


# --------------------------------------------------------------------------- #
#  Utilidades del sistema operativo
# --------------------------------------------------------------------------- #
def abrir_con_sistema(ruta: str, imprimir: bool = False) -> None:
    """Abre (o imprime) un archivo con la aplicación predeterminada de Windows."""
    if sys.platform.startswith("win"):
        if imprimir:
            try:
                os.startfile(ruta, "print")  # type: ignore[attr-defined]
                return
            except OSError:
                pass  # sin verbo 'print' registrado: se abre el lector para imprimir desde allí
        os.startfile(ruta)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", ruta])
    else:
        subprocess.Popen(["lp" if imprimir else "xdg-open", ruta])


def _dentro_de(raiz: str, ruta: str) -> bool:
    raiz, ruta = os.path.realpath(raiz), os.path.realpath(ruta)
    return os.path.commonpath([raiz, ruta]) == raiz


class ErrorUsuario(Exception):
    """Error con mensaje apto para mostrar al usuario."""


def api_segura(fn):
    """Envuelve cada método de la API: devuelve {ok, data} o {ok: False, error}."""
    @functools.wraps(fn)
    def envoltura(self, *args, **kwargs):
        try:
            return {"ok": True, "data": fn(self, *args, **kwargs)}
        except ErrorUsuario as e:
            return {"ok": False, "error": str(e)}
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            return {"ok": False, "error": f"Error inesperado: {e}"}
    return envoltura


# --------------------------------------------------------------------------- #
#  Consultas compartidas
# --------------------------------------------------------------------------- #
SELECT_DOC = """
SELECT d.*, di.nombre AS direccion, t.nombre AS tipo, u.usuario AS usuario,
       (SELECT group_concat(e.nombre, '|') FROM documento_etiquetas de
          JOIN etiquetas e ON e.id = de.etiqueta_id WHERE de.documento_id = d.id) AS etiquetas_txt
FROM documentos d
JOIN direcciones di ON di.id = d.direccion_id
JOIN tipos_documento t ON t.id = d.tipo_id
LEFT JOIN usuarios u ON u.id = d.usuario_id
"""


def _doc_publico(r) -> dict:
    d = dict(r)
    d["etiquetas"] = sorted((d.pop("etiquetas_txt") or "").split("|")) if d.get("etiquetas_txt") else []
    d.pop("etiquetas_txt", None)
    d["url"] = None
    if d.get("archivo_path"):
        rel = os.path.relpath(dbm.ruta_absoluta(d["archivo_path"]), dbm.REPO_DIR).replace(os.sep, "/")
        d["url"] = f"/repositorio/{rel}?t={TOKEN}"
        d["archivo_existe"] = os.path.exists(dbm.ruta_absoluta(d["archivo_path"]))
    return d


def _filtros_periodo(f: dict, cond: list, params: list) -> None:
    hoy = datetime.now()
    per = (f or {}).get("periodo") or "todo"
    desde = hasta = None
    if per == "mes":
        desde = hoy.replace(day=1)
    elif per == "30d":
        desde = hoy - timedelta(days=30)
    elif per == "trimestre":
        desde = hoy - timedelta(days=90)
    elif per == "anio":
        desde = hoy.replace(month=1, day=1)
    elif per == "anio_anterior":
        desde, hasta = datetime(hoy.year - 1, 1, 1), datetime(hoy.year, 1, 1)
    if desde:
        cond.append("d.fecha_carga >= ?")
        params.append(desde.strftime("%Y-%m-%d 00:00:00"))
    if hasta:
        cond.append("d.fecha_carga < ?")
        params.append(hasta.strftime("%Y-%m-%d 00:00:00"))


def _int_o_none(v):
    try:
        return int(v) if v not in (None, "", "todos") else None
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- #
#  API expuesta a JavaScript
# --------------------------------------------------------------------------- #
class Api:
    def __init__(self):
        self._ventana = None
        self._lock = threading.Lock()
        self._sesion: dict | None = None  # documento en proceso de digitalización

    def set_ventana(self, ventana):
        self._ventana = ventana

    # ------------------------------------------------------------ diálogos
    def _dialogo_abrir(self, multiple=True) -> list[str]:
        tipos = ("Documentos (*.pdf;*.jpg;*.jpeg;*.png;*.tif;*.tiff;*.bmp)", "Todos los archivos (*.*)")
        if self._ventana is not None:
            modo = webview.FileDialog.OPEN if hasattr(webview, "FileDialog") else webview.OPEN_DIALOG
            res = self._ventana.create_file_dialog(modo, allow_multiple=multiple, file_types=tipos)
            return list(res or [])
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk(); root.withdraw(); root.attributes("-topmost", True)
        res = filedialog.askopenfilenames(filetypes=[("Documentos", "*.pdf *.jpg *.jpeg *.png *.tif *.tiff *.bmp")])
        root.destroy()
        return list(res or [])

    def _dialogo_guardar(self, nombre: str, descripcion: str, ext: str) -> str | None:
        if self._ventana is not None:
            modo = webview.FileDialog.SAVE if hasattr(webview, "FileDialog") else webview.SAVE_DIALOG
            res = self._ventana.create_file_dialog(modo, save_filename=nombre,
                                                   file_types=(f"{descripcion} (*{ext})",))
            if not res:
                return None
            ruta = res if isinstance(res, str) else res[0]
        else:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk(); root.withdraw(); root.attributes("-topmost", True)
            ruta = filedialog.asksaveasfilename(initialfile=nombre, defaultextension=ext,
                                                filetypes=[(descripcion, f"*{ext}")])
            root.destroy()
            if not ruta:
                return None
        return ruta if ruta.lower().endswith(ext) else ruta + ext

    # ------------------------------------------------------------ general
    @api_segura
    def estado_inicial(self):
        cfg = dbm.get_config()
        with dbm.db() as con:
            u = con.execute("SELECT id, usuario, nombre, rol FROM usuarios WHERE usuario = ?",
                            (cfg.get("usuario_actual", "Archivo"),)).fetchone()
        return {"config": cfg, "usuario": dict(u) if u else {"usuario": "Archivo", "rol": "Administrador"},
                "catalogos": self._catalogos(), "token": TOKEN,
                "sistema": {"titulo": TITULO, "datos": dbm.DATA_DIR, "plataforma": sys.platform}}

    def _catalogos(self):
        with dbm.db() as con:
            return {
                "direcciones": dbm.filas(con.execute(
                    "SELECT id, nombre, activo FROM direcciones ORDER BY nombre")),
                "tipos": dbm.filas(con.execute(
                    "SELECT id, nombre, activo FROM tipos_documento ORDER BY nombre")),
                "etiquetas": [r[0] for r in con.execute("SELECT nombre FROM etiquetas ORDER BY nombre")],
                "anios": [r[0] for r in con.execute(
                    "SELECT DISTINCT anio FROM documentos ORDER BY anio DESC")],
            }

    @api_segura
    def catalogos(self):
        return self._catalogos()

    @api_segura
    def dashboard(self):
        with dbm.db() as con:
            total = con.execute("SELECT COUNT(*) FROM documentos WHERE estado='Digitalizado'").fetchone()[0]
            mes = con.execute("SELECT COUNT(*) FROM documentos WHERE fecha_carga >= ?",
                              (datetime.now().strftime("%Y-%m-01"),)).fetchone()[0]
            hoy = con.execute("SELECT COUNT(*) FROM documentos WHERE date(fecha_carga) = date('now','localtime')"
                              ).fetchone()[0]
            paginas = con.execute("SELECT COALESCE(SUM(paginas),0) FROM documentos").fetchone()[0]
            peso = con.execute("SELECT COALESCE(SUM(tamano_bytes),0) FROM documentos").fetchone()[0]
            pendientes = con.execute("SELECT COUNT(*) FROM documentos WHERE estado='Pendiente'").fetchone()[0]
            recientes = [_doc_publico(r) for r in con.execute(SELECT_DOC + " ORDER BY d.fecha_carga DESC LIMIT 8")]
            meses = dbm.filas(con.execute(
                "SELECT strftime('%Y-%m', fecha_carga) AS mes, COUNT(*) AS cantidad FROM documentos "
                "WHERE fecha_carga >= date('now','start of month','-11 months') GROUP BY mes ORDER BY mes"))
            ult_resp = con.execute("SELECT fecha FROM historial_respaldos ORDER BY id DESC LIMIT 1").fetchone()
        return {"total": total, "mes": mes, "hoy": hoy, "paginas": paginas, "peso_mb": round(peso / 1048576, 1),
                "pendientes": pendientes, "recientes": recientes, "meses": meses,
                "ultimo_respaldo": ult_resp[0] if ult_resp else None}

    @api_segura
    def salir(self):
        if self._ventana is not None:
            threading.Timer(0.1, self._ventana.destroy).start()
        return True

    # ------------------------------------------------------------ escaneo
    @api_segura
    def estado_escaner(self):
        return scn.estado_escaner()

    def _info_sesion(self):
        s = self._sesion
        if not s:
            return None
        return {**s["metricas"], "url": f"/temp/{os.path.basename(s['path'])}?t={TOKEN}"
                f"&v={s['version']}", "origen": s["origen"], "version": s["version"]}

    def _incorporar(self, rutas: list[str], agregar: bool, origen: str):
        with self._lock:
            base = self._sesion["path"] if (agregar and self._sesion) else None
            destino = scn.tmp_nombre(dbm.TEMP_DIR)
            try:
                metricas = scn.construir_pdf(rutas, destino, pdf_base=base)
            except ValueError as e:
                raise ErrorUsuario(str(e)) from e
            if self._sesion:
                self._descartar_archivo()
            self._sesion = {"path": destino, "metricas": metricas, "origen": origen,
                            "version": secrets.token_hex(4)}
            return self._info_sesion()

    @api_segura
    def iniciar_escaneo(self, agregar=False):
        """Escanea vía WIA; si no hay escáner disponible, abre el selector de archivos."""
        estado = scn.estado_escaner()
        if estado["conectado"]:
            try:
                img = scn.escanear_wia(dbm.TEMP_DIR)
            except RuntimeError as e:
                raise ErrorUsuario(str(e)) from e
            if not img:
                return None  # cancelado
            try:
                return self._incorporar([img], agregar, f"Escáner: {estado['nombre']}")
            finally:
                if os.path.exists(img):
                    os.remove(img)
        rutas = self._dialogo_abrir()
        if not rutas:
            return None
        return self._incorporar(rutas, agregar, ", ".join(os.path.basename(r) for r in rutas))

    @api_segura
    def importar_archivo(self, agregar=False, rutas=None):
        """Importa PDF/imágenes desde la PC (diálogo nativo). `rutas` sólo para pruebas."""
        rutas = rutas or self._dialogo_abrir()
        if not rutas:
            return None
        return self._incorporar(list(rutas), agregar, ", ".join(os.path.basename(r) for r in rutas))

    @api_segura
    def sesion_actual(self):
        return self._info_sesion()

    @api_segura
    def rotar(self, grados, pagina=None):
        with self._lock:
            if not self._sesion:
                raise ErrorUsuario("No hay un documento en digitalización.")
            self._sesion["metricas"].update(scn.rotar_pdf(self._sesion["path"], int(grados),
                                                          _int_o_none(pagina)))
            self._sesion["version"] = secrets.token_hex(4)
            return self._info_sesion()

    def _descartar_archivo(self):
        try:
            if self._sesion and os.path.exists(self._sesion["path"]):
                os.remove(self._sesion["path"])
        except OSError:
            pass

    @api_segura
    def descartar_escaneo(self):
        with self._lock:
            self._descartar_archivo()
            self._sesion = None
        return True

    @api_segura
    def siguiente_registro(self):
        with dbm.db() as con:
            return dbm.siguiente_registro(con)

    @api_segura
    def guardar_documento(self, datos: dict):
        datos = datos or {}
        dir_id, tipo_id = _int_o_none(datos.get("direccion_id")), _int_o_none(datos.get("tipo_id"))
        numero = (datos.get("numero") or "").strip()
        anio = _int_o_none(datos.get("anio"))
        if not dir_id or not tipo_id:
            raise ErrorUsuario("Seleccione la Dirección y el Tipo de Documento.")
        if not numero:
            raise ErrorUsuario("Ingrese el número del documento.")
        if not anio or not 1900 <= anio <= datetime.now().year + 1:
            raise ErrorUsuario("Ingrese un año válido.")
        with self._lock:
            if not self._sesion or not os.path.exists(self._sesion["path"]):
                raise ErrorUsuario("No hay un documento digitalizado para guardar. Vuelva al Paso 1.")
            cfg = dbm.get_config()
            with dbm.db() as con:
                direccion = con.execute("SELECT nombre FROM direcciones WHERE id=?", (dir_id,)).fetchone()
                tipo = con.execute("SELECT nombre FROM tipos_documento WHERE id=?", (tipo_id,)).fetchone()
                if not direccion or not tipo:
                    raise ErrorUsuario("Dirección o tipo inexistente.")
                dup = con.execute("SELECT nro_registro FROM documentos WHERE direccion_id=? AND tipo_id=? "
                                  "AND numero=? AND anio=?", (dir_id, tipo_id, numero, anio)).fetchone()
                if dup and not datos.get("permitir_duplicado"):
                    raise ErrorUsuario(f"Ya existe {tipo[0]} {numero} de {direccion[0]} "
                                       f"(registro {dup[0]}). Verifique el número.")
                carpeta = os.path.join(dbm.REPO_DIR, str(anio), dbm.nombre_seguro(direccion[0]))
                os.makedirs(carpeta, exist_ok=True)
                num_base = dbm.nombre_seguro(numero.replace("/", "_"))
                if not num_base.endswith(f"_{anio}"):
                    num_base = f"{num_base}_{anio}"
                base = f"{dbm.nombre_seguro(tipo[0])}_{num_base}"
                destino, n = os.path.join(carpeta, base + ".pdf"), 2
                while os.path.exists(destino):
                    destino, n = os.path.join(carpeta, f"{base}_{n}.pdf"), n + 1
                shutil.move(self._sesion["path"], destino)
                try:
                    u = con.execute("SELECT id FROM usuarios WHERE usuario=?",
                                    (cfg.get("usuario_actual"),)).fetchone()
                    nro = dbm.siguiente_registro(con)
                    m = self._sesion["metricas"]
                    cur = con.execute(
                        "INSERT INTO documentos(nro_registro,direccion_id,tipo_id,numero,anio,descripcion,"
                        "ubicacion_fisica,archivo_path,paginas,tamano_bytes,calidad,estado,usuario_id,"
                        "fecha_carga) VALUES (?,?,?,?,?,?,?,?,?,?,?,'Digitalizado',?,?)",
                        (nro, dir_id, tipo_id, numero, anio, (datos.get("descripcion") or "").strip(),
                         (datos.get("ubicacion_fisica") or "").strip(), os.path.relpath(destino, dbm.DATA_DIR),
                         m["paginas"], os.path.getsize(destino), m.get("calidad"),
                         u[0] if u else None, dbm.ahora()))
                    dbm.asignar_etiquetas(con, cur.lastrowid, datos.get("etiquetas") or [])
                    doc_id = cur.lastrowid
                except Exception:
                    shutil.move(destino, self._sesion["path"])  # revertir el archivo
                    raise
            self._sesion = None
        return self._obtener(doc_id)

    def _obtener(self, doc_id):
        with dbm.db() as con:
            r = con.execute(SELECT_DOC + " WHERE d.id = ?", (int(doc_id),)).fetchone()
        if not r:
            raise ErrorUsuario("El documento no existe.")
        return _doc_publico(r)

    def _ruta_doc(self, doc_id) -> tuple[dict, str]:
        d = self._obtener(doc_id)
        ruta = dbm.ruta_absoluta(d.get("archivo_path"))
        if not ruta or not os.path.exists(ruta):
            raise ErrorUsuario("El documento no tiene archivo digital disponible.")
        return d, ruta

    @api_segura
    def imprimir_comprobante(self, doc_id, abrir=True):
        d = self._obtener(doc_id)
        cfg = dbm.get_config()
        destino = os.path.join(dbm.COMPROBANTES_DIR, f"Comprobante_{d['nro_registro']}.pdf")
        exp.generar_comprobante(d, destino, LOGO_PNG, cfg.get("formato_fecha", "DD/MM/AAAA"))
        if abrir:
            abrir_con_sistema(destino, imprimir=True)
        return destino

    @api_segura
    def ver_documento(self, doc_id):
        _, ruta = self._ruta_doc(doc_id)
        abrir_con_sistema(ruta)
        return ruta

    @api_segura
    def imprimir_documento(self, doc_id):
        _, ruta = self._ruta_doc(doc_id)
        abrir_con_sistema(ruta, imprimir=True)
        return ruta

    @api_segura
    def descargar_documento(self, doc_id):
        d, ruta = self._ruta_doc(doc_id)
        destino = self._dialogo_guardar(os.path.basename(ruta), "Documento PDF", ".pdf")
        if not destino:
            return None
        shutil.copy2(ruta, destino)
        return destino

    @api_segura
    def obtener_documento(self, doc_id):
        return self._obtener(doc_id)

    @api_segura
    def actualizar_documento(self, doc_id, datos):
        with dbm.db() as con:
            con.execute("UPDATE documentos SET descripcion=?, ubicacion_fisica=? WHERE id=?",
                        ((datos.get("descripcion") or "").strip(),
                         (datos.get("ubicacion_fisica") or "").strip(), int(doc_id)))
            dbm.asignar_etiquetas(con, int(doc_id), datos.get("etiquetas") or [])
        return self._obtener(doc_id)

    @api_segura
    def eliminar_documento(self, doc_id):
        self._exigir_rol("Administrador")
        d = self._obtener(doc_id)
        with dbm.db() as con:
            con.execute("DELETE FROM documentos WHERE id=?", (int(doc_id),))
        ruta = dbm.ruta_absoluta(d.get("archivo_path"))
        if ruta and os.path.exists(ruta):
            os.remove(ruta)
        return True

    # ------------------------------------------------------------ consulta
    @api_segura
    def consultar(self, f=None):
        f = f or {}
        cond, params = [], []
        if (f.get("registro") or "").strip():
            cond.append("d.nro_registro LIKE ?")
            params.append(f"%{f['registro'].strip()}%")
        for palabra in (f.get("texto") or "").split():
            cond.append("(d.descripcion LIKE ? OR d.numero LIKE ? OR d.ubicacion_fisica LIKE ? OR EXISTS ("
                        "SELECT 1 FROM documento_etiquetas de JOIN etiquetas e ON e.id=de.etiqueta_id "
                        "WHERE de.documento_id=d.id AND e.nombre LIKE ?))")
            params += [f"%{palabra}%"] * 4
        for campo, col in (("direccion_id", "d.direccion_id"), ("tipo_id", "d.tipo_id"), ("anio", "d.anio")):
            v = _int_o_none(f.get(campo))
            if v:
                cond.append(f"{col} = ?")
                params.append(v)
        if f.get("desde"):
            cond.append("date(d.fecha_carga) >= date(?)")
            params.append(f["desde"])
        if f.get("hasta"):
            cond.append("date(d.fecha_carga) <= date(?)")
            params.append(f["hasta"])
        sql = SELECT_DOC + (" WHERE " + " AND ".join(cond) if cond else "") + \
            " ORDER BY d.fecha_carga DESC LIMIT 1000"
        with dbm.db() as con:
            return [_doc_publico(r) for r in con.execute(sql, params)]

    # ------------------------------------------------------------ reportes
    def _reporte(self, f=None):
        f = f or {}
        cond, params = [], []
        _filtros_periodo(f, cond, params)
        for campo, col in (("direccion_id", "d.direccion_id"), ("tipo_id", "d.tipo_id")):
            v = _int_o_none(f.get(campo))
            if v:
                cond.append(f"{col} = ?")
                params.append(v)
        where = (" WHERE " + " AND ".join(cond)) if cond else ""
        with dbm.db() as con:
            registrados = con.execute(f"SELECT COUNT(*) FROM documentos d{where}", params).fetchone()[0]
            dig_where = where + (" AND " if where else " WHERE ") + "d.estado='Digitalizado'"
            total = con.execute(f"SELECT COUNT(*) FROM documentos d{dig_where}", params).fetchone()[0]
            ultimo = con.execute(f"SELECT d.fecha_carga, d.nro_registro FROM documentos d{where} "
                                 "ORDER BY d.fecha_carga DESC LIMIT 1", params).fetchone()
            n_dir = con.execute("SELECT COUNT(*) FROM direcciones WHERE activo=1").fetchone()[0]
            por_dir = dbm.filas(con.execute(
                f"SELECT di.nombre, COUNT(*) AS cantidad FROM documentos d JOIN direcciones di "
                f"ON di.id=d.direccion_id{where} GROUP BY di.nombre ORDER BY cantidad DESC", params))
            por_tipo = dbm.filas(con.execute(
                f"SELECT t.nombre, COUNT(*) AS cantidad FROM documentos d JOIN tipos_documento t "
                f"ON t.id=d.tipo_id{where} GROUP BY t.nombre ORDER BY cantidad DESC", params))
            por_mes = dbm.filas(con.execute(
                f"SELECT strftime('%Y-%m', d.fecha_carga) AS mes, COUNT(*) AS cantidad FROM documentos d"
                f"{where} GROUP BY mes ORDER BY mes", params))
            docs = [_doc_publico(r) for r in con.execute(
                SELECT_DOC + where + " ORDER BY d.fecha_carga DESC", params)]
        return {"kpis": {"total": total, "registrados": registrados,
                         "tasa": round(total * 100 / registrados) if registrados else 0,
                         "direcciones": n_dir,
                         "ultima_fecha": ultimo[0] if ultimo else None,
                         "ultimo_registro": ultimo[1] if ultimo else None},
                "por_direccion": por_dir, "por_tipo": por_tipo, "por_mes": por_mes,
                "recientes": docs[:10], "documentos": docs}

    @api_segura
    def reporte(self, f=None):
        r = self._reporte(f)
        r.pop("documentos")
        return r

    @api_segura
    def exportar_pdf(self, f=None, imagenes=None, filtros_txt=""):
        destino = self._dialogo_guardar(f"Reporte_Archivo_{datetime.now():%Y-%m-%d}.pdf", "Documento PDF", ".pdf")
        if not destino:
            return None
        exp.exportar_reporte_pdf(self._reporte(f), destino, imagenes, filtros_txt, LOGO_PNG,
                                 dbm.get_config().get("formato_fecha", "DD/MM/AAAA"))
        return destino

    @api_segura
    def exportar_excel(self, f=None, filtros_txt=""):
        destino = self._dialogo_guardar(f"Reporte_Archivo_{datetime.now():%Y-%m-%d}.xlsx",
                                        "Libro de Excel", ".xlsx")
        if not destino:
            return None
        exp.exportar_reporte_excel(self._reporte(f), destino, filtros_txt,
                                   dbm.get_config().get("formato_fecha", "DD/MM/AAAA"))
        return destino

    @api_segura
    def exportar_png(self, data_url):
        destino = self._dialogo_guardar(f"Reporte_Archivo_{datetime.now():%Y-%m-%d}.png", "Imagen PNG", ".png")
        if not destino:
            return None
        return exp.guardar_png(data_url, destino)

    @api_segura
    def abrir_archivo(self, ruta):
        """Abre un archivo exportado/generado por el sistema."""
        if not ruta or not os.path.exists(ruta):
            raise ErrorUsuario("El archivo no existe.")
        abrir_con_sistema(ruta)
        return True

    # ------------------------------------------------------------ configuración
    def _usuario_actual(self):
        with dbm.db() as con:
            return con.execute("SELECT * FROM usuarios WHERE usuario=?",
                               (dbm.get_config().get("usuario_actual"),)).fetchone()

    def _exigir_rol(self, *roles):
        u = self._usuario_actual()
        if not u or u["rol"] not in roles:
            raise ErrorUsuario("Su rol no tiene permiso para realizar esta operación.")

    @api_segura
    def usuarios(self):
        with dbm.db() as con:
            return dbm.filas(con.execute(
                "SELECT id, usuario, nombre, rol, activo, creado FROM usuarios ORDER BY usuario"))

    @api_segura
    def guardar_usuario(self, u: dict):
        self._exigir_rol("Administrador")
        usuario, nombre, rol = (u.get("usuario") or "").strip(), (u.get("nombre") or "").strip(), u.get("rol")
        if not usuario or not nombre:
            raise ErrorUsuario("Complete usuario y nombre.")
        if rol not in dbm.ROLES:
            raise ErrorUsuario("Rol inválido.")
        activo = 1 if u.get("activo", True) else 0
        uid = _int_o_none(u.get("id"))
        actual = dbm.get_config().get("usuario_actual")
        with dbm.db() as con:
            if uid:
                previo = con.execute("SELECT usuario FROM usuarios WHERE id=?", (uid,)).fetchone()
                if previo and previo[0].lower() == (actual or "").lower() and (rol != "Administrador" or not activo):
                    raise ErrorUsuario("No puede quitarse el rol de Administrador ni desactivar su propio usuario.")
                try:
                    con.execute("UPDATE usuarios SET usuario=?, nombre=?, rol=?, activo=? WHERE id=?",
                                (usuario, nombre, rol, activo, uid))
                except dbm.sqlite3.IntegrityError as e:
                    raise ErrorUsuario("Ya existe un usuario con ese nombre.") from e
                if u.get("password"):
                    con.execute("UPDATE usuarios SET password_hash=? WHERE id=?",
                                (dbm.hash_password(u["password"]), uid))
                if previo and previo[0].lower() == (actual or "").lower():
                    con.execute("UPDATE configuracion SET valor=? WHERE clave='usuario_actual'", (usuario,))
            else:
                if len(u.get("password") or "") < 4:
                    raise ErrorUsuario("La contraseña debe tener al menos 4 caracteres.")
                try:
                    con.execute("INSERT INTO usuarios(usuario,nombre,rol,password_hash,activo,creado) "
                                "VALUES (?,?,?,?,?,?)",
                                (usuario, nombre, rol, dbm.hash_password(u["password"]), activo, dbm.ahora()))
                except dbm.sqlite3.IntegrityError as e:
                    raise ErrorUsuario("Ya existe un usuario con ese nombre.") from e
        return True

    @api_segura
    def eliminar_usuario(self, uid):
        self._exigir_rol("Administrador")
        with dbm.db() as con:
            u = con.execute("SELECT usuario FROM usuarios WHERE id=?", (int(uid),)).fetchone()
            if not u:
                raise ErrorUsuario("El usuario no existe.")
            if u[0].lower() == (dbm.get_config().get("usuario_actual") or "").lower():
                raise ErrorUsuario("No puede eliminar el usuario con la sesión activa.")
            con.execute("UPDATE documentos SET usuario_id=NULL WHERE usuario_id=?", (int(uid),))
            con.execute("DELETE FROM usuarios WHERE id=?", (int(uid),))
        return True

    _TABLAS = {"direcciones": "direcciones", "tipos": "tipos_documento"}

    @api_segura
    def guardar_categoria(self, tabla, item: dict):
        self._exigir_rol("Administrador", "Operador")
        t = self._TABLAS.get(tabla)
        nombre = (item.get("nombre") or "").strip()
        if not t or not nombre:
            raise ErrorUsuario("Ingrese un nombre.")
        cid = _int_o_none(item.get("id"))
        try:
            with dbm.db() as con:
                if cid:
                    con.execute(f"UPDATE {t} SET nombre=?, activo=? WHERE id=?",
                                (nombre, 1 if item.get("activo", True) else 0, cid))
                else:
                    con.execute(f"INSERT INTO {t}(nombre) VALUES (?)", (nombre,))
        except dbm.sqlite3.IntegrityError as e:
            raise ErrorUsuario(f"'{nombre}' ya existe.") from e
        return self._catalogos()

    @api_segura
    def eliminar_categoria(self, tabla, cid):
        self._exigir_rol("Administrador")
        t = self._TABLAS.get(tabla)
        if not t:
            raise ErrorUsuario("Categoría inválida.")
        col = "direccion_id" if tabla == "direcciones" else "tipo_id"
        with dbm.db() as con:
            usados = con.execute(f"SELECT COUNT(*) FROM documentos WHERE {col}=?", (int(cid),)).fetchone()[0]
            if usados:
                raise ErrorUsuario(f"No se puede eliminar: tiene {usados} documento(s) asociados. "
                                   "Puede desactivarla para que no aparezca en nuevas cargas.")
            con.execute(f"DELETE FROM {t} WHERE id=?", (int(cid),))
        return self._catalogos()

    @api_segura
    def realizar_respaldo(self):
        self._exigir_rol("Administrador", "Operador")
        res = exp.crear_respaldo(dbm.DB_PATH, dbm.REPO_DIR, dbm.BACKUP_DIR)
        with dbm.db() as con:
            n = con.execute("SELECT COUNT(*) FROM documentos").fetchone()[0]
            con.execute("INSERT INTO historial_respaldos(fecha,archivo,tamano_bytes,documentos,usuario,estado) "
                        "VALUES (?,?,?,?,?,'Completado')",
                        (dbm.ahora(), os.path.basename(res["archivo"]), res["tamano_bytes"], n,
                         dbm.get_config().get("usuario_actual")))
        return res

    @api_segura
    def respaldos(self):
        with dbm.db() as con:
            rows = dbm.filas(con.execute("SELECT * FROM historial_respaldos ORDER BY id DESC LIMIT 50"))
        for r in rows:
            r["existe"] = os.path.exists(os.path.join(dbm.BACKUP_DIR, r["archivo"]))
        return rows

    @api_segura
    def abrir_carpeta_respaldos(self):
        abrir_con_sistema(dbm.BACKUP_DIR)
        return True

    @api_segura
    def guardar_preferencias(self, prefs: dict):
        permitidas = {"tema": {"claro", "oscuro"}, "notificaciones": {"0", "1"},
                      "formato_fecha": {"DD/MM/AAAA", "AAAA-MM-DD", "DD-MM-AAAA"}}
        for k, v in (prefs or {}).items():
            v = str(v)
            if k in permitidas and v in permitidas[k]:
                dbm.set_config(k, v)
        return dbm.get_config()


# --------------------------------------------------------------------------- #
#  Servidor HTTP local
# --------------------------------------------------------------------------- #
def crear_servidor(api: Api, modo_api_http: bool = False) -> ThreadingHTTPServer:
    rutas_estaticas = {
        "/static/": os.path.join(dbm.RESOURCE_DIR, "static"),
        "/templates/": os.path.join(dbm.RESOURCE_DIR, "templates"),
    }
    rutas_protegidas = {"/repositorio/": dbm.REPO_DIR, "/temp/": dbm.TEMP_DIR}

    class Manejador(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):  # silencioso
            pass

        def _enviar(self, codigo, cuerpo: bytes, tipo="text/plain; charset=utf-8", extra=None):
            self.send_response(codigo)
            self.send_header("Content-Type", tipo)
            self.send_header("Content-Length", str(len(cuerpo)))
            self.send_header("X-Content-Type-Options", "nosniff")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(cuerpo)

        def _token_ok(self, qs):
            return secrets.compare_digest(qs.get("t", [""])[0], TOKEN)

        def do_HEAD(self):
            self.do_GET()

        def do_GET(self):
            u = urlparse(self.path)
            ruta, qs = unquote(u.path), parse_qs(u.query)
            if ruta in ("/", "/index.html"):
                return self._enviar(302, b"", extra={"Location": "/templates/index.html"})
            for prefijo, raiz in {**rutas_estaticas, **rutas_protegidas}.items():
                if ruta.startswith(prefijo):
                    if prefijo in rutas_protegidas and not self._token_ok(qs):
                        return self._enviar(403, b"Acceso denegado")
                    archivo = os.path.normpath(os.path.join(raiz, ruta[len(prefijo):]))
                    if not _dentro_de(raiz, archivo) or not os.path.isfile(archivo):
                        return self._enviar(404, b"No encontrado")
                    tipo = mimetypes.guess_type(archivo)[0] or "application/octet-stream"
                    if tipo.startswith("text/") or tipo.endswith("javascript"):
                        tipo += "; charset=utf-8"
                    with open(archivo, "rb") as fh:
                        datos = fh.read()
                    cache = "no-store" if prefijo in rutas_protegidas or prefijo == "/templates/" \
                        else "max-age=3600"
                    return self._enviar(200, datos, tipo, {"Cache-Control": cache})
            self._enviar(404, b"No encontrado")

        def do_POST(self):
            u = urlparse(self.path)
            if not modo_api_http or not u.path.startswith("/api/") or not self._token_ok(parse_qs(u.query)):
                return self._enviar(403, b"Acceso denegado")
            nombre = u.path[5:]
            metodo = getattr(api, nombre, None)
            if nombre.startswith("_") or not callable(metodo):
                return self._enviar(404, b"Metodo inexistente")
            largo = int(self.headers.get("Content-Length") or 0)
            args = json.loads(self.rfile.read(largo) or b"[]")
            res = metodo(*args)
            self._enviar(200, json.dumps(res, default=str).encode(), "application/json")

    servidor = ThreadingHTTPServer(("127.0.0.1", 0), Manejador)
    servidor.daemon_threads = True
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    return servidor


def limpiar_temporales():
    for a in os.listdir(dbm.TEMP_DIR):
        try:
            os.remove(os.path.join(dbm.TEMP_DIR, a))
        except OSError:
            pass


def main():
    dbm.inicializar()
    limpiar_temporales()
    api = Api()
    modo_navegador = "--navegador" in sys.argv or webview is None
    servidor = crear_servidor(api, modo_api_http=modo_navegador)
    url = f"http://127.0.0.1:{servidor.server_address[1]}/templates/index.html"

    if modo_navegador:
        print(f"Modo navegador: {url}?t={TOKEN}")
        if "--sin-abrir" not in sys.argv:
            webbrowser.open(f"{url}?t={TOKEN}")
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            pass
        return

    ventana = webview.create_window(
        TITULO, url, js_api=api, maximized=True, min_size=(1180, 720),
        background_color="#EBF3FA", text_select=True,
    )
    api.set_ventana(ventana)
    opciones = {"debug": "--debug" in sys.argv}
    if "--autoprueba" in sys.argv:
        # Verificación sin intervención: abre la ventana real, espera la interfaz y registra el resultado.
        def autoprueba(win):
            resultado = {"ok": False}
            try:
                win.events.loaded.wait(60)
                js = ("JSON.stringify({titulo: document.title, vista: document.querySelector('#titulo-vista').textContent,"
                      " total: document.querySelector('#ini-total').textContent,"
                      " puente: !!(window.pywebview && window.pywebview.api)})")
                for _ in range(40):  # hasta 20 s para que el dashboard cargue datos
                    datos = json.loads(win.evaluate_js(js))
                    if datos["puente"] and datos["total"] not in ("", "0"):
                        break
                    threading.Event().wait(0.5)
                resultado = {"ok": datos["puente"] and datos["vista"] == "Inicio" and datos["total"] not in ("", "0"),
                             "interfaz": datos, "escaner": scn.estado_escaner()}
            except Exception as e:  # noqa: BLE001
                resultado["error"] = repr(e)
            with open(os.path.join(dbm.DATA_DIR, "autoprueba.json"), "w", encoding="utf-8") as fh:
                json.dump(resultado, fh, ensure_ascii=False, indent=2)
            win.destroy()
        opciones["func"], opciones["args"] = autoprueba, (ventana,)
    if os.path.exists(LOGO_PNG):
        opciones["icon"] = LOGO_PNG  # GTK/Qt; en Windows se usa el ícono del .exe
    try:
        webview.start(**opciones)
    except TypeError:  # versiones de pywebview sin parámetro icon
        opciones.pop("icon", None)
        webview.start(**opciones)
    servidor.shutdown()
    limpiar_temporales()


if __name__ == "__main__":
    main()
