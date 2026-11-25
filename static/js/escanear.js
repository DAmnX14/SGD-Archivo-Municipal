/* Módulo Escanear y Cargar - flujo de 4 pasos */
Vistas.escanear = (() => {
  let paso = 1;
  let sesion = null;        // documento en digitalización (métricas + url temporal)
  let ultimoDoc = null;     // último documento guardado
  let etiquetas = [];
  let cargadosSesion = 0;
  let visor = null;

  /* ---------------------------------------------------------------- pasos */
  function irPaso(n) {
    paso = n;
    [1, 2, 3, 4].forEach((i) => {
      UI.$(`#paso-${i}`).classList.toggle('hidden', i !== n);
      const p = UI.$(`.paso[data-paso="${i}"]`);
      p.classList.toggle('activo', i === n);
      p.classList.toggle('hecho', i < n);
      p.querySelector('.paso-num').innerHTML = i < n ? Iconos.svg('check', 'w-5 h-5') : i;
      const l = UI.$(`.paso-linea[data-linea="${i}"]`);
      if (l) l.classList.toggle('hecho', i < n);
    });
    if (n === 2 && sesion) { pintarResumen(); visor.cargar(sesion.url); }
    if (n === 3) prepararFormulario();
    UI.$('#contenido').scrollTop = 0;
  }

  /* ---------------------------------------------------------------- paso 1 */
  async function verificarEscaner() {
    const box = UI.$('#esc-estado');
    box.querySelector('span:nth-child(2)').textContent = 'Verificando escáner...';
    try {
      const e = await Api.estado_escaner();
      box.querySelector('.punto').className = `punto ${e.conectado ? 'ok' : 'warn'}`;
      box.querySelector('span:nth-child(2)').innerHTML = e.conectado
        ? `<b class="text-exito">${UI.esc(e.mensaje)}</b> <span class="text-muted">(${UI.esc(e.nombre)})</span>`
        : `<span>${UI.esc(e.mensaje)}</span>`;
      UI.$('#btn-iniciar-escaneo').title = e.conectado ? 'Digitalizar con el escáner' : 'Sin escáner: se abrirá el selector de archivos';
      UI.$('#btn-agregar-escaneo').classList.toggle('hidden', !e.conectado);
    } catch (err) { UI.error(err); }
  }

  async function actualizarRegistro() {
    try {
      const r = await Api.siguiente_registro();
      UI.$('#esc-prox-reg').textContent = r;
      UI.$('#p3-registro').textContent = r;
    } catch (e) { /* no crítico */ }
  }

  function pintarSesion() {
    UI.$('#esc-resultado').classList.toggle('hidden', !sesion);
    UI.$('#esc-zona').classList.toggle('hidden', !!sesion);
    if (!sesion) return;
    UI.$('#esc-origen').textContent = sesion.origen;
    UI.$('#m-paginas').textContent = sesion.paginas;
    UI.$('#m-formato').textContent = sesion.formato;
    UI.$('#m-tamano').textContent = UI.mbTxt(sesion.tamano_bytes);
    const cal = UI.$('#m-calidad');
    cal.textContent = sesion.calidad;
    cal.className = 'v ' + (sesion.calidad === 'Baja' ? 'text-amber-500' : 'text-exito');
    miniaturaPDF(sesion.url, UI.$('#esc-miniatura'), 160);
  }

  async function adquirir(metodo, agregar) {
    try {
      const r = await UI.cargando(metodo === 'iniciar_escaneo' ? 'Digitalizando documento...' : 'Importando y convirtiendo a PDF...',
        () => Api[metodo](agregar));
      if (!r) return; // cancelado por el usuario
      sesion = r;
      pintarSesion();
      UI.toast(agregar ? `Página(s) agregada(s). Total: ${r.paginas}` : 'Documento adquirido correctamente.', 'ok');
    } catch (e) { UI.error(e); }
  }

  async function descartar(silencioso = false) {
    try { await Api.descartar_escaneo(); } catch (e) { UI.error(e); }
    sesion = null;
    pintarSesion();
    visor.vacio('Sin documento para mostrar');
    if (!silencioso) UI.toast('Digitalización descartada.', 'info');
  }

  /* ---------------------------------------------------------------- paso 2 */
  function pintarResumen() {
    UI.$('#r-paginas').textContent = sesion.paginas;
    UI.$('#r-formato').textContent = sesion.formato;
    UI.$('#r-tamano').textContent = `${UI.mbTxt(sesion.tamano_bytes)} MB`;
    UI.$('#r-dpi').textContent = sesion.dpi ? `${sesion.dpi} DPI` : 'Vectorial';
    UI.$('#r-calidad').textContent = sesion.calidad;
    UI.$('#r-origen').textContent = sesion.origen;
    UI.$('#r-origen').title = sesion.origen;
  }

  async function rotar(grados, pagina) {
    try {
      sesion = await Api.rotar(grados, pagina);
      pintarResumen();
      return sesion.url;
    } catch (e) { UI.error(e); return null; }
  }

  /* ---------------------------------------------------------------- paso 3 */
  function llenarSelects() {
    const f = UI.$('#form-doc');
    UI.opciones(f.direccion_id, Estado.catalogos.direcciones, { soloActivos: true, valor: f.direccion_id.value });
    UI.opciones(f.tipo_id, Estado.catalogos.tipos, { soloActivos: true, valor: f.tipo_id.value });
    UI.$('#dl-etiquetas').innerHTML = Estado.catalogos.etiquetas.map((e) => `<option value="${UI.esc(e)}">`).join('');
  }

  function prepararFormulario() {
    llenarSelects();
    const f = UI.$('#form-doc');
    if (!f.anio.value) f.anio.value = new Date().getFullYear();
    f.numero.placeholder = `Ej. 243/${f.anio.value}`;
    UI.$('#p3-paginas').textContent = sesion ? sesion.paginas : '-';
    if (sesion) miniaturaPDF(sesion.url, UI.$('#p3-miniatura'), 220);
    actualizarRegistro();
    pintarDestino();
    pintarEtiquetas();
    setTimeout(() => (f.direccion_id.value ? f.numero : f.direccion_id).focus(), 50);
  }

  function seguro(t) {
    return (t || '').normalize('NFKD').replace(/[̀-ͯ]/g, '').replace(/[^\w-]+/g, '_').replace(/^_+|_+$/g, '');
  }

  function pintarDestino() {
    const f = UI.$('#form-doc');
    const dir = f.direccion_id.selectedOptions[0];
    const tipo = f.tipo_id.selectedOptions[0];
    if (!f.direccion_id.value || !f.tipo_id.value || !f.numero.value || !f.anio.value) {
      UI.$('#p3-destino').textContent = 'repositorio_pdf/{AÑO}/{DIRECCIÓN}/{Tipo}_{Número}_{Año}.pdf';
      return;
    }
    let num = seguro(f.numero.value.replace(/\//g, '_'));
    if (!num.endsWith(`_${f.anio.value}`)) num += `_${f.anio.value}`;
    UI.$('#p3-destino').textContent = `repositorio_pdf/${f.anio.value}/${seguro(dir.textContent)}/${seguro(tipo.textContent)}_${num}.pdf`;
  }

  function pintarEtiquetas() {
    UI.$('#f-etiquetas-chips').innerHTML = etiquetas.map((e, i) =>
      `<span class="chip">${UI.esc(e)}<button type="button" data-quitar="${i}" title="Quitar">${Iconos.svg('x', 'w-3 h-3')}</button></span>`).join('');
  }

  function agregarEtiqueta(txt) {
    txt.split(',').map((t) => t.trim().toLowerCase()).filter(Boolean).forEach((t) => {
      if (!etiquetas.includes(t) && t.length <= 40) etiquetas.push(t);
    });
    pintarEtiquetas();
  }

  function validar() {
    const f = UI.$('#form-doc');
    let ok = true;
    ['direccion_id', 'tipo_id', 'numero', 'anio'].forEach((k) => {
      const vacio = !String(f[k].value).trim();
      f[k].classList.toggle('error', vacio);
      if (vacio) ok = false;
    });
    if (!ok) UI.toast('Complete los campos obligatorios (*).', 'warn');
    return ok;
  }

  async function guardar(continuar) {
    if (!sesion) { UI.toast('No hay documento digitalizado. Vuelva al Paso 1.', 'warn'); return irPaso(1); }
    const pend = UI.$('#f-etiqueta-input').value.trim();
    if (pend) { agregarEtiqueta(pend); UI.$('#f-etiqueta-input').value = ''; }
    if (!validar()) return;
    const datos = { ...UI.filtrosDe(UI.$('#form-doc')), etiquetas };
    let doc;
    try {
      doc = await UI.cargando('Guardando documento...', () => Api.guardar_documento(datos));
    } catch (e) {
      if (!/Ya existe/.test(e.message)) return UI.error(e);
      const ok = await UI.confirmar('Posible documento duplicado', `${UI.esc(e.message)}<br><br>¿Desea registrarlo de todos modos?`,
        'Guardar igualmente', 'btn-marino');
      if (!ok) return;
      try { doc = await UI.cargando('Guardando documento...', () => Api.guardar_documento({ ...datos, permitir_duplicado: true })); }
      catch (e2) { return UI.error(e2); }
    }
    ultimoDoc = doc;
    sesion = null;
    cargadosSesion++;
    UI.$('#esc-sesion-count').textContent = cargadosSesion;
    App.refrescarCatalogos();
    const f = UI.$('#form-doc');
    if (continuar) {
      // Carga masiva: conserva Dirección, Tipo, Año y Ubicación
      f.numero.value = ''; f.descripcion.value = '';
      UI.toast(`Guardado con registro ${doc.nro_registro}. Listo para el siguiente documento.`, 'ok');
      pintarSesion();
      actualizarRegistro();
      irPaso(1);
    } else {
      f.reset(); etiquetas = [];
      UI.$('#p4-registro').textContent = doc.nro_registro;
      UI.$('#p4-doc').textContent = `${doc.tipo} ${doc.numero}`;
      UI.$('#p4-dir').textContent = doc.direccion;
      UI.$('#p4-fecha').textContent = UI.fecha(doc.fecha_carga, true);
      UI.$('#p4-archivo').textContent = `datos_sistema/${doc.archivo_path.replace(/\\/g, '/')}`;
      irPaso(4);
      UI.toast('Documento guardado correctamente.', 'ok');
    }
  }

  /* ---------------------------------------------------------------- init */
  function iniciar() {
    visor = new VisorPDF(UI.$('#visor-escaneo'), { rotar, vacio: 'Sin documento para mostrar' });

    UI.$('#esc-refrescar').addEventListener('click', verificarEscaner);
    UI.$('#btn-iniciar-escaneo').addEventListener('click', () => adquirir('iniciar_escaneo', false));
    UI.$('#btn-importar').addEventListener('click', () => adquirir('importar_archivo', false));
    UI.$('#btn-agregar-escaneo').addEventListener('click', () => adquirir('iniciar_escaneo', true));
    UI.$('#btn-agregar-archivo').addEventListener('click', () => adquirir('importar_archivo', true));
    UI.$('#btn-descartar').addEventListener('click', async () => {
      if (await UI.confirmar('Descartar digitalización', '¿Desea descartar el documento digitalizado?', 'Descartar')) descartar();
    });
    UI.$('#btn-p1-continuar').addEventListener('click', () => irPaso(2));
    UI.$('#btn-p2-volver').addEventListener('click', () => irPaso(1));
    UI.$('#btn-p2-continuar').addEventListener('click', () => irPaso(3));

    const f = UI.$('#form-doc');
    ['change', 'input'].forEach((ev) => f.addEventListener(ev, (e) => {
      pintarDestino();
      if (e.target.classList) e.target.classList.remove('error');
      if (e.target.name === 'anio') f.numero.placeholder = `Ej. 243/${f.anio.value || new Date().getFullYear()}`;
    }));
    // Si escribe "243/2026" completa el año automáticamente
    f.numero.addEventListener('blur', () => {
      const m = f.numero.value.match(/\/(\d{4})\s*$/);
      if (m) { f.anio.value = m[1]; pintarDestino(); }
    });
    const inpEt = UI.$('#f-etiqueta-input');
    inpEt.addEventListener('keydown', (e) => {
      if ((e.key === 'Enter' || e.key === ',') && inpEt.value.trim()) { e.preventDefault(); agregarEtiqueta(inpEt.value); inpEt.value = ''; }
      else if (e.key === 'Backspace' && !inpEt.value && etiquetas.length) { etiquetas.pop(); pintarEtiquetas(); }
    });
    inpEt.addEventListener('change', () => { // selección desde datalist
      if (Estado.catalogos.etiquetas.includes(inpEt.value)) { agregarEtiqueta(inpEt.value); inpEt.value = ''; }
    });
    UI.$('#f-etiquetas-box').addEventListener('click', (e) => {
      const b = e.target.closest('[data-quitar]');
      if (b) { etiquetas.splice(+b.dataset.quitar, 1); pintarEtiquetas(); } else inpEt.focus();
    });
    UI.$('#btn-p3-cancelar').addEventListener('click', async () => {
      if (!(await UI.confirmar('Cancelar carga', 'Se descartará el documento digitalizado y los datos ingresados. ¿Continuar?', 'Sí, cancelar'))) return;
      f.reset(); etiquetas = [];
      await descartar(true);
      irPaso(1);
    });
    UI.$('#btn-p3-guardar-continuar').addEventListener('click', () => guardar(true));
    UI.$('#btn-p3-guardar').addEventListener('click', () => guardar(false));

    UI.$('#btn-p4-comprobante').addEventListener('click', async () => {
      try {
        await UI.cargando('Generando comprobante...', () => Api.imprimir_comprobante(ultimoDoc.id));
        UI.toast('Comprobante generado y enviado a impresión.', 'ok');
      } catch (e) { UI.error(e); }
    });
    UI.$('#btn-p4-ver').addEventListener('click', async () => {
      try { await Api.ver_documento(ultimoDoc.id); } catch (e) { UI.error(e); }
    });
    UI.$('#btn-p4-finalizar').addEventListener('click', () => { ultimoDoc = null; pintarSesion(); irPaso(1); });

    document.addEventListener('catalogos-cambiados', llenarSelects);
    irPaso(1);
  }

  async function mostrar() {
    verificarEscaner();
    actualizarRegistro();
    try {
      const s = await Api.sesion_actual();
      if (s && (!sesion || s.version !== sesion.version)) { sesion = s; }
    } catch (e) { /* sin sesión */ }
    if (paso === 1) pintarSesion();
  }

  return {
    titulo: 'Escanear y Cargar', subtitulo: 'Digitalización y clasificación de documentos', iniciar, mostrar,
    hayTrabajoPendiente: () => !!sesion,
  };
})();
