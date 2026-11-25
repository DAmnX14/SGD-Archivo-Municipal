# Sistema de Gestión Documental - Jefatura de Archivo
**Municipalidad de Libertador General San Martín**

Aplicación de escritorio para Windows (Python 3.11+ · pywebview · SQLite) para digitalizar, clasificar, consultar y reportar el archivo municipal. La interfaz funciona 100 % sin conexión: Tailwind ya está compilado y Chart.js y pdf.js están incluidos en `static/`.

## Estructura
```
sgd/
├── app.py               # Punto de entrada: ventana pywebview + servidor local + API JS
├── database.py          # Esquema SQLite, rutas, seed data, registro correlativo
├── scanner_utils.py     # WIA (escáner), imagen→PDF, métricas, rotación (pypdf)
├── export_utils.py      # Comprobante PDF, reportes PDF/Excel/PNG, respaldo ZIP
├── requirements.txt
├── build_exe.bat        # Compilación a .exe con PyInstaller
├── tests/               # Pruebas automáticas (pytest)
├── .github/workflows/   # CI en Windows: pruebas + .exe + autoprueba
├── templates/index.html
├── static/
│   ├── css/  tailwind.css (compilado) · app.css (tema claro/oscuro) · tailwind.src.css
│   ├── js/   api.js · app.js · visor.js · iconos.js · inicio.js · escanear.js · consultar.js · reportes.js · configuracion.js
│   ├── img/  logo_archivo.png · .ico · .svg
│   └── vendor/ chart.umd.min.js · pdf.min.js · pdf.worker.min.js
└── datos_sistema/       # Se crea al primer inicio (junto al .exe)
    ├── archivo_municipal.db
    ├── repositorio_pdf/{AÑO}/{DIRECCION}/Decreto_243_2026.pdf
    ├── backups/ · comprobantes/ · temp/
```

## Ejecutar
```bat
python -m pip install -r requirements.txt
python app.py
```
Para trabajar en la interfaz desde el navegador: `python app.py --navegador`. Para abrir las herramientas de desarrollo: `python app.py --debug`.

Usuarios iniciales: `Archivo` / `archivo` (Administrador), `operador` / `operador` y `consulta` / `consulta`. La sesión activa es la de `Archivo`.

## Compilar a .exe
Ejecute `build_exe.bat`, o directamente:
```bat
pyinstaller --noconfirm --onefile --windowed --name "SGD_Archivo_Municipal" --icon "static\img\logo_archivo.ico" --add-data "templates;templates" --add-data "static;static" --hidden-import pythoncom --hidden-import pywintypes --hidden-import win32com.client --collect-data reportlab app.py
```
El ejecutable queda en `dist\SGD_Archivo_Municipal.exe`. La carpeta `datos_sistema\` se crea al lado del `.exe`.

Requisito en la PC: **Microsoft Edge WebView2 Runtime**. Ya viene instalado en Windows 10 actualizado y en Windows 11.

## Pruebas y compilación automática (GitHub Actions)
El workflow `.github/workflows/windows.yml` se ejecuta en Windows en cada *push*:
1. Instala las dependencias y corre `pytest` sobre todo el backend (carga, rotación, duplicados, comprobantes, exportaciones y respaldo).
2. Compila el `.exe` con PyInstaller.
3. Abre el `.exe` real con `--autoprueba`: verifica la ventana WebView2, el puente JS↔Python y el dashboard, y luego se cierra.
4. Publica el `.exe` como artefacto descargable (pestaña **Actions**). Si se crea una etiqueta `v1.0.0`, el `.exe` también se publica como **Release**.

Para correr las pruebas en la PC: `pip install pytest` y luego `python -m pytest tests`.

## Notas
- **Escáner:** usa WIA (el driver del escáner debe estar instalado). Si no se detecta ninguno, "Iniciar Escaneo" abre el selector de archivos (PDF, JPG, PNG, TIFF o BMP).
- **Imprimir:** se usa el verbo "imprimir" de Windows con el lector de PDF predeterminado. Si el lector no lo admite, el PDF se abre para imprimirlo desde allí.
- **Tasa de digitalización:** registros digitalizados sobre el total de registros. El seed incluye un registro "Pendiente" (solo en papel), por eso da 98 %.
- **Recompilar estilos** (opcional, requiere Node): `npm install` y luego `npm run css`.
