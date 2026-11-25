"""
database.py - Capa de datos del Sistema de Gestión Documental.

Crea y administra la base SQLite `archivo_municipal.db`, la estructura de
carpetas de `datos_sistema/` y los datos iniciales (seed) del sistema.
"""
from __future__ import annotations

import hashlib
import os
import random
import re
import secrets
import sqlite3
import sys
import unicodedata
from contextlib import contextmanager
from datetime import datetime, timedelta

# --------------------------------------------------------------------------- #
#  Rutas: recursos empaquetados (solo lectura) vs. datos del usuario (escritura)
# --------------------------------------------------------------------------- #
if getattr(sys, "frozen", False):  # Ejecutable PyInstaller
    RESOURCE_DIR = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    APP_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    RESOURCE_DIR = os.path.dirname(os.path.abspath(__file__))
    APP_DIR = RESOURCE_DIR

# SGD_DATOS permite usar otra carpeta de datos (pruebas automáticas, red, etc.)
DATA_DIR = os.environ.get("SGD_DATOS") or os.path.join(APP_DIR, "datos_sistema")
REPO_DIR = os.path.join(DATA_DIR, "repositorio_pdf")
BACKUP_DIR = os.path.join(DATA_DIR, "backups")
TEMP_DIR = os.path.join(DATA_DIR, "temp")
COMPROBANTES_DIR = os.path.join(DATA_DIR, "comprobantes")
DB_PATH = os.path.join(DATA_DIR, "archivo_municipal.db")

DIRECCIONES_INICIALES = [
    "Comercio", "Obras Públicas", "Hacienda", "Recursos Humanos",
    "Gobierno", "Acción Social", "Tránsito", "Catastro",
]
TIPOS_INICIALES = [
    "Decreto", "Resolución", "Ordenanza", "Expediente",
    "Nota", "Contrato", "Disposición",
]
ROLES = ("Administrador", "Operador", "Consulta")
PREFERENCIAS_DEFECTO = {
    "tema": "claro",
    "notificaciones": "1",
    "formato_fecha": "DD/MM/AAAA",
    "usuario_actual": "Archivo",
}


def asegurar_carpetas() -> None:
    for d in (DATA_DIR, REPO_DIR, BACKUP_DIR, TEMP_DIR, COMPROBANTES_DIR):
        os.makedirs(d, exist_ok=True)


def conectar() -> sqlite3.Connection:
    """Nueva conexión por llamada (pywebview ejecuta la API en varios hilos)."""
    con = sqlite3.connect(DB_PATH, timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


@contextmanager
def db():
    con = conectar()
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def filas(rows) -> list[dict]:
    return [dict(r) for r in rows]


# --------------------------------------------------------------------------- #
#  Utilidades
# --------------------------------------------------------------------------- #
def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000)
    return f"{salt}${h.hex()}"


def verificar_password(password: str, almacenado: str) -> bool:
    try:
        salt, _ = almacenado.split("$", 1)
    except ValueError:
        return False
    return secrets.compare_digest(hash_password(password, salt), almacenado)


def nombre_seguro(texto: str) -> str:
    """'Obras Públicas' -> 'Obras_Publicas' (válido para carpetas de Windows)."""
    t = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    t = re.sub(r"[^\w\-]+", "_", t).strip("_")
    return t or "Sin_Nombre"


def ahora() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# --------------------------------------------------------------------------- #
#  Esquema
# --------------------------------------------------------------------------- #
ESQUEMA = """
CREATE TABLE IF NOT EXISTS direcciones (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre  TEXT NOT NULL UNIQUE COLLATE NOCASE,
    activo  INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS tipos_documento (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre  TEXT NOT NULL UNIQUE COLLATE NOCASE,
    activo  INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS usuarios (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario        TEXT NOT NULL UNIQUE COLLATE NOCASE,
    nombre         TEXT NOT NULL,
    rol            TEXT NOT NULL CHECK (rol IN ('Administrador','Operador','Consulta')),
    password_hash  TEXT NOT NULL,
    activo         INTEGER NOT NULL DEFAULT 1,
    creado         TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS documentos (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    nro_registro      TEXT NOT NULL UNIQUE,
    direccion_id      INTEGER NOT NULL REFERENCES direcciones(id),
    tipo_id           INTEGER NOT NULL REFERENCES tipos_documento(id),
    numero            TEXT NOT NULL,
    anio              INTEGER NOT NULL,
    descripcion       TEXT,
    ubicacion_fisica  TEXT,
    archivo_path      TEXT,
    paginas           INTEGER DEFAULT 0,
    tamano_bytes      INTEGER DEFAULT 0,
    calidad           TEXT,
    estado            TEXT NOT NULL DEFAULT 'Digitalizado',
    usuario_id        INTEGER REFERENCES usuarios(id),
    fecha_carga       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_doc_fecha ON documentos(fecha_carga);
CREATE INDEX IF NOT EXISTS ix_doc_dir   ON documentos(direccion_id);
CREATE INDEX IF NOT EXISTS ix_doc_tipo  ON documentos(tipo_id);
CREATE INDEX IF NOT EXISTS ix_doc_anio  ON documentos(anio);

CREATE TABLE IF NOT EXISTS etiquetas (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre  TEXT NOT NULL UNIQUE COLLATE NOCASE
);
CREATE TABLE IF NOT EXISTS documento_etiquetas (
    documento_id  INTEGER NOT NULL REFERENCES documentos(id) ON DELETE CASCADE,
    etiqueta_id   INTEGER NOT NULL REFERENCES etiquetas(id) ON DELETE CASCADE,
    PRIMARY KEY (documento_id, etiqueta_id)
);
CREATE TABLE IF NOT EXISTS historial_respaldos (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha         TEXT NOT NULL,
    archivo       TEXT NOT NULL,
    tamano_bytes  INTEGER NOT NULL DEFAULT 0,
    documentos    INTEGER NOT NULL DEFAULT 0,
    usuario       TEXT,
    estado        TEXT NOT NULL DEFAULT 'Completado'
);
CREATE TABLE IF NOT EXISTS configuracion (
    clave  TEXT PRIMARY KEY,
    valor  TEXT
);
"""


def inicializar() -> bool:
    """Crea carpetas, tablas y datos iniciales. Devuelve True si era BD nueva."""
    asegurar_carpetas()
    nueva = not os.path.exists(DB_PATH)
    with db() as con:
        con.executescript(ESQUEMA)
        for k, v in PREFERENCIAS_DEFECTO.items():
            con.execute("INSERT OR IGNORE INTO configuracion(clave, valor) VALUES (?,?)", (k, v))
        vacia = con.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0] == 0
    if vacia:
        cargar_datos_iniciales()
    return nueva


# --------------------------------------------------------------------------- #
#  Configuración
# --------------------------------------------------------------------------- #
def get_config() -> dict:
    with db() as con:
        return {r["clave"]: r["valor"] for r in con.execute("SELECT * FROM configuracion")}


def set_config(clave: str, valor) -> None:
    with db() as con:
        con.execute(
            "INSERT INTO configuracion(clave, valor) VALUES (?,?) "
            "ON CONFLICT(clave) DO UPDATE SET valor = excluded.valor",
            (clave, str(valor)),
        )


# --------------------------------------------------------------------------- #
#  Registro correlativo
# --------------------------------------------------------------------------- #
def siguiente_registro(con: sqlite3.Connection, anio: int | None = None) -> str:
    anio = anio or datetime.now().year
    row = con.execute(
        "SELECT MAX(CAST(substr(nro_registro, 6) AS INTEGER)) FROM documentos "
        "WHERE nro_registro LIKE ?", (f"{anio}-%",)
    ).fetchone()
    return f"{anio}-{(row[0] or 0) + 1:06d}"


def asignar_etiquetas(con: sqlite3.Connection, documento_id: int, etiquetas: list[str]) -> None:
    con.execute("DELETE FROM documento_etiquetas WHERE documento_id = ?", (documento_id,))
    for e in {e.strip() for e in etiquetas if e and e.strip()}:
        con.execute("INSERT OR IGNORE INTO etiquetas(nombre) VALUES (?)", (e,))
        eid = con.execute("SELECT id FROM etiquetas WHERE nombre = ?", (e,)).fetchone()[0]
        con.execute("INSERT OR IGNORE INTO documento_etiquetas VALUES (?,?)", (documento_id, eid))


# --------------------------------------------------------------------------- #
#  Datos iniciales (seed)
# --------------------------------------------------------------------------- #
_DESCRIPCIONES = {
    "Comercio": ["Habilitación comercial de local gastronómico", "Renovación de licencia comercial",
                 "Autorización de feria artesanal", "Baja de habilitación comercial"],
    "Obras Públicas": ["Pavimentación de calle Belgrano", "Licitación de cordón cuneta Barrio Norte",
                       "Certificado de obra - alumbrado público", "Ampliación de red de agua potable"],
    "Hacienda": ["Presupuesto general de gastos", "Modificación de tasas municipales",
                 "Rendición de cuentas trimestral", "Plan de pagos de deuda tributaria"],
    "Recursos Humanos": ["Designación de personal de planta", "Licencia anual reglamentaria",
                         "Adicional por título", "Pase a planta permanente"],
    "Gobierno": ["Convenio con el Gobierno Provincial", "Declaración de interés municipal",
                 "Asueto administrativo", "Designación de funcionarios"],
    "Acción Social": ["Subsidio a comedor comunitario", "Entrega de módulos alimentarios",
                      "Programa de asistencia a adultos mayores", "Ayuda económica por emergencia"],
    "Tránsito": ["Ordenamiento del tránsito en el centro", "Renovación de licencias de conducir",
                 "Señalización vial zona escolar", "Habilitación de remises"],
    "Catastro": ["Mensura y subdivisión de lote", "Actualización de valuación fiscal",
                 "Registro de planos de obra privada", "Unificación de parcelas"],
}
_ETIQUETAS = ["urgente", "licitación", "personal", "presupuesto", "convenio", "habilitación",
              "obra", "subsidio", "vigente", "archivo histórico"]


def cargar_datos_iniciales() -> None:
    """Carga usuarios, categorías y ~50 documentos de ejemplo con PDF reales."""
    from scanner_utils import generar_pdf_ejemplo  # import diferido (evita ciclo)

    rnd = random.Random(2026)
    hoy = datetime.now()
    with db() as con:
        for u, n, r, p in [("Archivo", "Jefatura de Archivo", "Administrador", "archivo"),
                           ("operador", "Operador de Mesa de Entradas", "Operador", "operador"),
                           ("consulta", "Usuario de Consulta", "Consulta", "consulta")]:
            con.execute("INSERT INTO usuarios(usuario,nombre,rol,password_hash,activo,creado) "
                        "VALUES (?,?,?,?,1,?)", (u, n, r, hash_password(p), ahora()))
        for d in DIRECCIONES_INICIALES:
            con.execute("INSERT OR IGNORE INTO direcciones(nombre) VALUES (?)", (d,))
        for t in TIPOS_INICIALES:
            con.execute("INSERT OR IGNORE INTO tipos_documento(nombre) VALUES (?)", (t,))
        dirs = {r["nombre"]: r["id"] for r in con.execute("SELECT * FROM direcciones")}
        tipos = {r["nombre"]: r["id"] for r in con.execute("SELECT * FROM tipos_documento")}

        # Distribución desigual para que los gráficos se vean interesantes
        pesos_dir = [10, 8, 9, 6, 7, 4, 3, 3]
        pesos_tipo = [12, 9, 5, 8, 6, 3, 4]
        registros = []
        # 2025: 12 documentos históricos
        for i in range(12):
            registros.append(datetime(2025, rnd.randint(2, 12), rnd.randint(1, 28),
                                      rnd.randint(8, 13), rnd.randint(0, 59)))
        # Año actual: 43 documentos repartidos en los últimos meses
        for i in range(43):
            registros.append(hoy - timedelta(days=rnd.randint(1, 300), hours=rnd.randint(0, 6)))
        registros.sort()

        contador: dict[int, int] = {}
        documentos = []
        for fecha in registros:
            anio = fecha.year
            contador[anio] = contador.get(anio, 200 if anio == hoy.year else 120) + 1
            documentos.append((fecha, f"{anio}-{contador[anio]:06d}"))

        # El documento destacado del enunciado: Decreto 243/2026 de Comercio
        destacado = (hoy - timedelta(hours=3), f"{hoy.year}-{contador.get(hoy.year, 200) + 1:06d}")

        for idx, (fecha, nro) in enumerate(documentos + [destacado]):
            es_destacado = (fecha, nro) == destacado
            if es_destacado:
                direccion, tipo, numero, anio = "Comercio", "Decreto", f"243/{hoy.year}", hoy.year
                desc = "Decreto de habilitación comercial - Régimen de ferias y comercios de la ciudad"
                ubic, etqs = "Caja 4 - Carpeta Decretos", ["habilitación", "vigente"]
            else:
                direccion = rnd.choices(DIRECCIONES_INICIALES, pesos_dir)[0]
                tipo = rnd.choices(TIPOS_INICIALES, pesos_tipo)[0]
                anio = fecha.year
                numero = f"{rnd.randint(10, 240)}/{anio}"
                desc = rnd.choice(_DESCRIPCIONES[direccion])
                ubic = f"Caja {rnd.randint(1, 12)} - Carpeta {tipo}s" if tipo != "Resolución" \
                    else f"Caja {rnd.randint(1, 12)} - Carpeta Resoluciones"
                etqs = rnd.sample(_ETIQUETAS, rnd.randint(0, 3))

            # Uno de los registros queda "Pendiente" de digitalización (sólo papel)
            pendiente = idx == 7
            ruta, paginas, tam = None, 0, 0
            if not pendiente:
                carpeta = os.path.join(REPO_DIR, str(anio), nombre_seguro(direccion))
                os.makedirs(carpeta, exist_ok=True)
                base = f"{nombre_seguro(tipo)}_{numero.split('/')[0]}_{anio}"
                ruta = os.path.join(carpeta, base + ".pdf")
                n = 2
                while os.path.exists(ruta):
                    ruta = os.path.join(carpeta, f"{base}_{n}.pdf")
                    n += 1
                paginas = 1 if es_destacado else rnd.randint(1, 3)
                generar_pdf_ejemplo(ruta, tipo, numero, direccion, desc, paginas)
                tam = os.path.getsize(ruta)
            cur = con.execute(
                "INSERT INTO documentos(nro_registro,direccion_id,tipo_id,numero,anio,descripcion,"
                "ubicacion_fisica,archivo_path,paginas,tamano_bytes,calidad,estado,usuario_id,fecha_carga)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,1,?)",
                (nro, dirs[direccion], tipos[tipo], numero, anio, desc, ubic,
                 os.path.relpath(ruta, DATA_DIR) if ruta else None, paginas, tam,
                 None if pendiente else "Óptima", "Pendiente" if pendiente else "Digitalizado",
                 fecha.strftime("%Y-%m-%d %H:%M:%S")),
            )
            asignar_etiquetas(con, cur.lastrowid, etqs)


def ruta_absoluta(rel: str | None) -> str | None:
    if not rel:
        return None
    return os.path.normpath(os.path.join(DATA_DIR, rel))
