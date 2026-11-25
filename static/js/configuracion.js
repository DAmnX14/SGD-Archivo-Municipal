/* Módulo Configuración del Sistema */
Vistas.configuracion = (() => {
  let tab = 'usuarios';
  let usuarios = [];

  function cambiarTab(t) {
    tab = t;
    UI.$$('#cfg-tabs .tab').forEach((b) => b.classList.toggle('activo', b.dataset.tab === t));
    UI.$$('#vista-configuracion [data-panel]').forEach((p) => p.classList.toggle('hidden', p.dataset.panel !== t));
    ({ usuarios: cargarUsuarios, categorias: pintarCategorias, respaldo: cargarRespaldos, preferencias: pintarPreferencias })[t]();
  }

  /* ------------------------------------------------------------ usuarios */
  async function cargarUsuarios() {
    try { usuarios = await Api.usuarios(); } catch (e) { return UI.error(e); }
    const rolBadge = (r) => `<span class="badge badge-rol">${UI.esc(r)}</span>`;
    UI.$('#u-lista').innerHTML = usuarios.map((u) => `<tr>
      <td class="font-semibold">${UI.esc(u.usuario)} ${u.usuario.toLowerCase() === (Estado.usuario.usuario || '').toLowerCase() ? '<span class="badge badge-ok ml-1">sesión activa</span>' : ''}</td>
      <td>${UI.esc(u.nombre)}</td><td>${rolBadge(u.rol)}</td>
      <td>${u.activo ? '<span class="badge badge-ok">Activo</span>' : '<span class="badge badge-off">Inactivo</span>'}</td>
      <td>${UI.fecha(u.creado)}</td>
      <td class="text-right whitespace-nowrap"><button class="btn-ico" data-u-edit="${u.id}" title="Editar">${Iconos.svg('edit')}</button>
        <button class="btn-ico peligro" data-u-del="${u.id}" title="Eliminar">${Iconos.svg('trash')}</button></td></tr>`).join('');
  }

  async function formUsuario(u = null) {
    const datos = await UI.modal({
      titulo: u ? `Editar usuario: ${u.usuario}` : 'Nuevo usuario', icono: u ? 'edit' : 'user-plus',
      cuerpo: `<div class="grid grid-cols-2 gap-4">
        <div><label class="lbl">Usuario *</label><input class="inp" id="fu-usuario" value="${UI.esc(u ? u.usuario : '')}"></div>
        <div><label class="lbl">Rol *</label><select class="inp" id="fu-rol">${['Administrador', 'Operador', 'Consulta']
          .map((r) => `<option ${u && u.rol === r ? 'selected' : ''}>${r}</option>`).join('')}</select></div>
        <div class="col-span-2"><label class="lbl">Nombre completo *</label><input class="inp" id="fu-nombre" value="${UI.esc(u ? u.nombre : '')}"></div>
        <div class="col-span-2"><label class="lbl">${u ? 'Nueva contraseña (dejar vacío para no cambiar)' : 'Contraseña * (mín. 4 caracteres)'}</label>
          <input class="inp" type="password" id="fu-pass" autocomplete="new-password"></div>
        <label class="col-span-2 flex items-center gap-3 text-sm"><span class="switch"><input type="checkbox" id="fu-activo" ${!u || u.activo ? 'checked' : ''}><span></span></span>Usuario activo</label>
      </div>`,
      botones: [{ texto: 'Cancelar', valor: null }, { texto: 'Guardar', clase: 'btn-primario', validar: async (m) => {
        const d = { id: u ? u.id : null, usuario: m.querySelector('#fu-usuario').value, nombre: m.querySelector('#fu-nombre').value,
          rol: m.querySelector('#fu-rol').value, password: m.querySelector('#fu-pass').value, activo: m.querySelector('#fu-activo').checked };
        try { await Api.guardar_usuario(d); return d; } catch (e) { UI.error(e); return false; }
      } }],
    });
    if (!datos) return;
    UI.toast('Usuario guardado.', 'ok');
    if (u && u.usuario.toLowerCase() === (Estado.usuario.usuario || '').toLowerCase()) {
      Estado.usuario.usuario = datos.usuario;
      UI.$('#hdr-usuario').textContent = datos.usuario;
    }
    cargarUsuarios();
  }

  /* ------------------------------------------------------------ categorías */
  function pintarCategorias() {
    const fila = (tabla, c) => `<tr>
      <td class="font-medium">${UI.esc(c.nombre)}</td>
      <td>${c.activo ? '<span class="badge badge-ok">Activa</span>' : '<span class="badge badge-off">Inactiva</span>'}</td>
      <td class="text-right whitespace-nowrap"><button class="btn-ico" data-cat-edit="${tabla}:${c.id}" title="Editar">${Iconos.svg('edit')}</button>
        <button class="btn-ico peligro" data-cat-del="${tabla}:${c.id}" title="Eliminar">${Iconos.svg('trash')}</button></td></tr>`;
    UI.$('#cat-direcciones').innerHTML = Estado.catalogos.direcciones.map((c) => fila('direcciones', c)).join('') || UI.vacioFila(3, 'Sin direcciones');
    UI.$('#cat-tipos').innerHTML = Estado.catalogos.tipos.map((c) => fila('tipos', c)).join('') || UI.vacioFila(3, 'Sin tipos');
  }

  async function formCategoria(tabla, c = null) {
    const nombreTabla = tabla === 'direcciones' ? 'Dirección' : 'Tipo de Documento';
    const ok = await UI.modal({
      titulo: c ? `Editar ${nombreTabla}` : `Nueva ${nombreTabla}`, icono: 'tags',
      cuerpo: `<div class="space-y-4"><div><label class="lbl">Nombre *</label><input class="inp" id="fc-nombre" value="${UI.esc(c ? c.nombre : '')}"></div>
        ${c ? `<label class="flex items-center gap-3 text-sm"><span class="switch"><input type="checkbox" id="fc-activo" ${c.activo ? 'checked' : ''}><span></span></span>Activa (disponible para nuevas cargas)</label>` : ''}</div>`,
      botones: [{ texto: 'Cancelar', valor: null }, { texto: 'Guardar', clase: 'btn-primario', validar: async (m) => {
        const item = { id: c ? c.id : null, nombre: m.querySelector('#fc-nombre').value, activo: c ? m.querySelector('#fc-activo').checked : true };
        try { Estado.catalogos = await Api.guardar_categoria(tabla, item); return true; } catch (e) { UI.error(e); return false; }
      } }],
    });
    if (!ok) return;
    document.dispatchEvent(new Event('catalogos-cambiados'));
    pintarCategorias();
    UI.toast(`${nombreTabla} guardada.`, 'ok');
  }

  /* ------------------------------------------------------------ respaldo */
  async function cargarRespaldos() {
    UI.$('#resp-ruta').textContent = Estado.sistema ? `${Estado.sistema.datos}${Estado.sistema.plataforma.startsWith('win') ? '\\' : '/'}backups` : 'datos_sistema/backups/';
    try {
      const lista = await Api.respaldos();
      UI.$('#resp-lista').innerHTML = lista.length ? lista.map((r) => `<tr><td>${UI.fecha(r.fecha, true)}</td>
        <td class="font-mono text-xs">${UI.esc(r.archivo)}</td><td>${UI.mb(r.tamano_bytes)} MB</td><td>${r.documentos}</td>
        <td>${UI.esc(r.usuario || '-')}</td><td>${r.existe ? `<span class="badge badge-ok">${UI.esc(r.estado)}</span>` : '<span class="badge badge-off">Archivo no encontrado</span>'}</td></tr>`).join('')
        : UI.vacioFila(6, 'Aún no se realizaron respaldos.');
    } catch (e) { UI.error(e); }
  }

  /* ------------------------------------------------------------ preferencias */
  function pintarPreferencias() {
    UI.$('#pref-tema').checked = Estado.config.tema === 'oscuro';
    UI.$('#pref-notif').checked = Estado.config.notificaciones !== '0';
    UI.$('#pref-fecha').value = Estado.config.formato_fecha || 'DD/MM/AAAA';
    UI.$('#pref-datos').textContent = Estado.sistema ? Estado.sistema.datos : '';
  }

  function iniciar() {
    UI.$$('#cfg-tabs .tab').forEach((b) => b.addEventListener('click', () => cambiarTab(b.dataset.tab)));
    UI.$('#u-nuevo').addEventListener('click', () => formUsuario());
    UI.$('#u-lista').addEventListener('click', async (e) => {
      const ed = e.target.closest('[data-u-edit]'), del = e.target.closest('[data-u-del]');
      if (ed) formUsuario(usuarios.find((u) => u.id === +ed.dataset.uEdit));
      if (del) {
        const u = usuarios.find((x) => x.id === +del.dataset.uDel);
        if (!(await UI.confirmar('Eliminar usuario', `¿Eliminar al usuario <b>${UI.esc(u.usuario)}</b>?`, 'Eliminar'))) return;
        try { await Api.eliminar_usuario(u.id); UI.toast('Usuario eliminado.', 'ok'); cargarUsuarios(); } catch (er) { UI.error(er); }
      }
    });
    UI.$$('[data-nueva-cat]').forEach((b) => b.addEventListener('click', () => formCategoria(b.dataset.nuevaCat)));
    UI.$('#vista-configuracion').addEventListener('click', async (e) => {
      const ed = e.target.closest('[data-cat-edit]'), del = e.target.closest('[data-cat-del]');
      if (ed) {
        const [t, id] = ed.dataset.catEdit.split(':');
        formCategoria(t, Estado.catalogos[t].find((c) => c.id === +id));
      }
      if (del) {
        const [t, id] = del.dataset.catDel.split(':');
        const c = Estado.catalogos[t].find((x) => x.id === +id);
        if (!(await UI.confirmar('Eliminar categoría', `¿Eliminar <b>${UI.esc(c.nombre)}</b>?`, 'Eliminar'))) return;
        try {
          Estado.catalogos = await Api.eliminar_categoria(t, c.id);
          document.dispatchEvent(new Event('catalogos-cambiados'));
          pintarCategorias(); UI.toast('Categoría eliminada.', 'ok');
        } catch (er) { UI.error(er); }
      }
    });
    UI.$('#btn-respaldo').addEventListener('click', async () => {
      try {
        const r = await UI.cargando('Generando respaldo (base de datos + PDF)...', () => Api.realizar_respaldo());
        UI.toast(`Respaldo creado: ${r.archivo.split(/[\\/]/).pop()} (${r.archivos_pdf} PDF, ${UI.mb(r.tamano_bytes)} MB)`, 'ok');
        cargarRespaldos();
      } catch (e) { UI.error(e); }
    });
    UI.$('#btn-abrir-backups').addEventListener('click', () => Api.abrir_carpeta_respaldos().catch(UI.error));
    UI.$('#pref-tema').addEventListener('change', (e) => App.guardarPreferencias({ tema: e.target.checked ? 'oscuro' : 'claro' }));
    UI.$('#pref-notif').addEventListener('change', (e) => App.guardarPreferencias({ notificaciones: e.target.checked ? '1' : '0' }));
    UI.$('#pref-fecha').addEventListener('change', (e) => App.guardarPreferencias({ formato_fecha: e.target.value }));
  }

  function mostrar() { cambiarTab(tab); }

  return { titulo: 'Configuración del Sistema', subtitulo: 'Usuarios, categorías, respaldos y preferencias', iniciar, mostrar, pintarPreferencias };
})();
