/* Módulo Consultar Documentos */
Vistas.consultar = (() => {
  let resultados = [];
  let seleccionado = null;
  let visor = null;

  function llenarFiltros() {
    const f = UI.$('#form-consulta');
    UI.opciones(f.direccion_id, Estado.catalogos.direcciones, { todos: 'Todas', valor: f.direccion_id.value });
    UI.opciones(f.tipo_id, Estado.catalogos.tipos, { todos: 'Todos', valor: f.tipo_id.value });
    const anio = f.anio.value;
    f.anio.innerHTML = '<option value="">Todos</option>' + Estado.catalogos.anios.map((a) => `<option>${a}</option>`).join('');
    f.anio.value = anio;
  }

  async function buscar() {
    try {
      resultados = await Api.consultar(UI.filtrosDe(UI.$('#form-consulta')));
      pintar();
    } catch (e) { UI.error(e); }
  }
  const buscarDiferido = UI.debounce(buscar, 280);

  function pintar() {
    UI.$('#c-cantidad').textContent = resultados.length;
    UI.$('#c-resultados').innerHTML = resultados.length ? resultados.map((d) => `
      <tr class="clic ${seleccionado && seleccionado.id === d.id ? 'sel' : ''}" data-id="${d.id}">
        <td class="font-semibold text-vivo whitespace-nowrap">${UI.esc(d.nro_registro)}</td>
        <td><div class="font-medium">${UI.esc(d.tipo)} ${UI.esc(d.numero)}</div><div class="text-xs text-muted truncate max-w-[260px]">${UI.esc(d.descripcion)}</div></td>
        <td>${UI.esc(d.direccion)}</td><td>${d.anio}</td><td class="whitespace-nowrap">${UI.fecha(d.fecha_carga, true)}</td>
        <td class="text-right whitespace-nowrap">${d.url ? `
          <button class="btn-ico" data-acc="ver" title="Ver">${Iconos.svg('eye')}</button>
          <button class="btn-ico" data-acc="descargar" title="Descargar / Guardar copia">${Iconos.svg('download')}</button>
          <button class="btn-ico" data-acc="imprimir" title="Imprimir">${Iconos.svg('printer')}</button>`
          : '<span class="badge badge-warn">Pendiente</span>'}</td>
      </tr>`).join('') : UI.vacioFila(6, 'No se encontraron documentos con los filtros indicados.');
  }

  function seleccionar(id, cargarVista = true) {
    seleccionado = resultados.find((d) => d.id === id) || null;
    UI.$$('#c-resultados tr').forEach((tr) => tr.classList.toggle('sel', +tr.dataset.id === id));
    pintarMetadatos();
    if (!cargarVista) return;
    if (seleccionado && seleccionado.url && seleccionado.archivo_existe !== false) {
      visor.cargar(seleccionado.url);
      UI.$('#c-prev-titulo').textContent = `${seleccionado.tipo} ${seleccionado.numero}`;
    } else {
      visor.vacio(seleccionado ? 'Este registro no tiene archivo digital (pendiente de digitalización).' : 'Seleccione un documento');
      UI.$('#c-prev-titulo').textContent = '';
    }
  }

  function pintarMetadatos() {
    const d = seleccionado;
    const box = UI.$('#c-metadatos');
    if (!d) { box.innerHTML = '<div class="text-muted text-sm">Seleccione un documento de la lista para ver sus datos.</div>'; return; }
    const admin = Estado.usuario.rol === 'Administrador';
    const puedeEditar = Estado.usuario.rol !== 'Consulta';
    box.innerHTML = `
      <div class="grid grid-cols-4 gap-4">
        <div><div class="dato-k">N° Registro</div><div class="dato-v text-vivo">${UI.esc(d.nro_registro)}</div></div>
        <div><div class="dato-k">Tipo</div><div class="dato-v">${UI.esc(d.tipo)}</div></div>
        <div><div class="dato-k">Número / Año</div><div class="dato-v">${UI.esc(d.numero)} · ${d.anio}</div></div>
        <div><div class="dato-k">Dirección</div><div class="dato-v">${UI.esc(d.direccion)}</div></div>
        <div class="col-span-2"><div class="dato-k">Descripción</div><div class="dato-v font-normal">${UI.esc(d.descripcion) || '-'}</div></div>
        <div><div class="dato-k">Ubicación Física</div><div class="dato-v">${UI.esc(d.ubicacion_fisica) || '-'}</div></div>
        <div><div class="dato-k">Estado</div><div>${d.estado === 'Digitalizado' ? '<span class="badge badge-ok">Digitalizado</span>' : '<span class="badge badge-warn">Pendiente</span>'}</div></div>
        <div class="col-span-2"><div class="dato-k mb-1">Etiquetas</div><div class="flex flex-wrap gap-1.5">${d.etiquetas.length ? d.etiquetas.map((e) => `<span class="chip">${UI.esc(e)}</span>`).join('') : '<span class="text-muted text-sm">Sin etiquetas</span>'}</div></div>
        <div><div class="dato-k">Páginas / Tamaño</div><div class="dato-v">${d.paginas || 0} pág. · ${UI.mb(d.tamano_bytes)} MB</div></div>
        <div><div class="dato-k">Cargado por</div><div class="dato-v">${UI.esc(d.usuario) || '-'} · ${UI.fecha(d.fecha_carga, true)}</div></div>
      </div>
      <div class="flex gap-2 mt-4 pt-4 border-t border-borde flex-wrap">
        ${d.url ? `<button class="btn btn-sec" data-acc="abrir">${Iconos.svg('external')}Abrir en lector</button>` : ''}
        <button class="btn btn-sec" data-acc="comprobante">${Iconos.svg('printer')}Comprobante</button>
        ${puedeEditar ? `<button class="btn btn-sec" data-acc="editar">${Iconos.svg('edit')}Editar metadatos</button>` : ''}
        ${admin ? `<button class="btn btn-peligro ml-auto" data-acc="eliminar">${Iconos.svg('trash')}Eliminar</button>` : ''}
      </div>`;
  }

  async function accion(acc, d) {
    try {
      if (acc === 'ver') return seleccionar(d.id);
      if (acc === 'descargar') {
        const r = await Api.descargar_documento(d.id);
        if (r) UI.toast(`Copia guardada en: ${r}`, 'ok');
      } else if (acc === 'imprimir') {
        await Api.imprimir_documento(d.id);
        UI.toast('Documento enviado a impresión.', 'ok');
      } else if (acc === 'abrir') {
        await Api.ver_documento(d.id);
      } else if (acc === 'comprobante') {
        await UI.cargando('Generando comprobante...', () => Api.imprimir_comprobante(d.id));
        UI.toast('Comprobante generado y enviado a impresión.', 'ok');
      } else if (acc === 'editar') {
        await editar(d);
      } else if (acc === 'eliminar') {
        if (!(await UI.confirmar('Eliminar documento', `Se eliminará el registro <b>${UI.esc(d.nro_registro)}</b> y su archivo PDF. Esta acción no se puede deshacer.`, 'Eliminar'))) return;
        await Api.eliminar_documento(d.id);
        UI.toast('Documento eliminado.', 'ok');
        seleccionado = null; pintarMetadatos(); visor.vacio('Seleccione un documento');
        buscar();
      }
    } catch (e) { UI.error(e); }
  }

  async function editar(d) {
    const res = await UI.modal({
      titulo: `Editar ${d.tipo} ${d.numero}`, icono: 'edit',
      cuerpo: `<div class="space-y-3">
        <div><label class="lbl">Descripción</label><textarea class="inp" id="e-desc">${UI.esc(d.descripcion)}</textarea></div>
        <div><label class="lbl">Ubicación Física</label><input class="inp" id="e-ubic" value="${UI.esc(d.ubicacion_fisica)}"></div>
        <div><label class="lbl">Etiquetas (separadas por coma)</label><input class="inp" id="e-etq" value="${UI.esc(d.etiquetas.join(', '))}"></div></div>`,
      botones: [{ texto: 'Cancelar', valor: null }, { texto: 'Guardar cambios', clase: 'btn-primario',
        validar: (m) => ({ descripcion: m.querySelector('#e-desc').value, ubicacion_fisica: m.querySelector('#e-ubic').value,
          etiquetas: m.querySelector('#e-etq').value.split(',').map((x) => x.trim().toLowerCase()).filter(Boolean) }) }],
    });
    if (!res) return;
    const act = await Api.actualizar_documento(d.id, res);
    resultados = resultados.map((x) => (x.id === act.id ? act : x));
    pintar(); seleccionar(act.id, false);
    App.refrescarCatalogos();
    UI.toast('Metadatos actualizados.', 'ok');
  }

  function iniciar() {
    visor = new VisorPDF(UI.$('#visor-consulta'), { vacio: 'Seleccione un documento para ver la vista previa' });
    const f = UI.$('#form-consulta');
    f.addEventListener('input', buscarDiferido);
    f.addEventListener('change', buscarDiferido);
    f.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); buscar(); } });
    UI.$('#c-buscar').addEventListener('click', buscar);
    UI.$('#c-limpiar').addEventListener('click', () => { f.reset(); buscar(); });
    UI.$('#c-resultados').addEventListener('click', (e) => {
      const tr = e.target.closest('tr[data-id]');
      if (!tr) return;
      const d = resultados.find((x) => x.id === +tr.dataset.id);
      const b = e.target.closest('[data-acc]');
      if (b) accion(b.dataset.acc, d); else seleccionar(d.id);
    });
    UI.$('#c-metadatos').addEventListener('click', (e) => {
      const b = e.target.closest('[data-acc]');
      if (b && seleccionado) accion(b.dataset.acc, seleccionado);
    });
    document.addEventListener('catalogos-cambiados', llenarFiltros);
  }

  function mostrar() { llenarFiltros(); buscar(); }

  return { titulo: 'Consultar Documentos', subtitulo: 'Búsqueda y visualización del repositorio digital', iniciar, mostrar };
})();
