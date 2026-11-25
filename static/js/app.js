/* Núcleo de la interfaz: navegación, estado global, utilidades de UI y preferencias. */
const Estado = { config: {}, usuario: {}, catalogos: { direcciones: [], tipos: [], etiquetas: [], anios: [] }, token: '' };
const Vistas = {}; // cada módulo registra { titulo, subtitulo, mostrar() }

const UI = {
  esc(s) {
    return String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  },
  $(sel, raiz = document) { return raiz.querySelector(sel); },
  $$(sel, raiz = document) { return [...raiz.querySelectorAll(sel)]; },

  fecha(iso, conHora = false) {
    if (!iso) return '-';
    const [f, h = ''] = String(iso).split(/[ T]/);
    const [a, m, d] = f.split('-');
    if (!d) return iso;
    const fmt = Estado.config.formato_fecha || 'DD/MM/AAAA';
    const s = fmt === 'AAAA-MM-DD' ? `${a}-${m}-${d}` : fmt === 'DD-MM-AAAA' ? `${d}-${m}-${a}` : `${d}/${m}/${a}`;
    return conHora && h ? `${s} ${h.slice(0, 5)}` : s;
  },
  mb(bytes) { return ((bytes || 0) / 1048576).toFixed(2); },
  mbTxt(bytes) { const m = (bytes || 0) / 1048576; return m > 0 && m < 0.01 ? '< 0.01' : m.toFixed(2); },

  toast(msg, tipo = 'info') {
    if (Estado.config.notificaciones === '0' && tipo !== 'error' && tipo !== 'warn') return;
    const ico = { ok: 'check-circle', error: 'alert', warn: 'alert', info: 'info' }[tipo];
    const col = { ok: 'text-exito', error: 'text-peligro', warn: 'text-amber-500', info: 'text-vivo' }[tipo];
    const el = document.createElement('div');
    el.className = `toast ${tipo}`;
    el.innerHTML = `${Iconos.svg(ico, col)}<div class="flex-1">${UI.esc(msg)}</div>`;
    UI.$('#toasts').appendChild(el);
    setTimeout(() => { el.style.transition = 'opacity .3s'; el.style.opacity = 0; setTimeout(() => el.remove(), 300); },
      tipo === 'error' ? 6500 : 3800);
  },
  error(e) { UI.toast(e && e.message ? e.message : String(e), 'error'); },

  async cargando(texto, fn) {
    const c = UI.$('#cargando');
    UI.$('#cargando-txt').textContent = texto || 'Procesando...';
    const t = setTimeout(() => c.classList.add('on'), 150);
    try { return await fn(); } finally { clearTimeout(t); c.classList.remove('on'); }
  },

  /** Modal genérico. `cuerpo` es HTML; `botones`: [{texto, clase, valor}] → resuelve con el valor o null. */
  modal({ titulo, cuerpo, botones = [{ texto: 'Aceptar', clase: 'btn-primario', valor: true }], icono = 'info', alAbrir }) {
    return new Promise((resolve) => {
      const fondo = document.createElement('div');
      fondo.className = 'modal-fondo';
      fondo.innerHTML = `<div class="modal"><div class="card-header">${Iconos.svg(icono)}${UI.esc(titulo)}</div>
        <div class="p-5">${cuerpo}</div>
        <div class="px-5 pb-5 flex justify-end gap-3">${botones.map((b, i) =>
          `<button class="btn ${b.clase || 'btn-sec'}" data-i="${i}">${UI.esc(b.texto)}</button>`).join('')}</div></div>`;
      const cerrar = (v) => { fondo.remove(); document.removeEventListener('keydown', tecla); resolve(v); };
      const tecla = (e) => { if (e.key === 'Escape') cerrar(null); };
      document.addEventListener('keydown', tecla);
      fondo.addEventListener('mousedown', (e) => { if (e.target === fondo) cerrar(null); });
      fondo.querySelectorAll('[data-i]').forEach((b) => b.addEventListener('click', async () => {
        const bt = botones[+b.dataset.i];
        if (bt.validar) { const v = await bt.validar(fondo); if (v === false) return; cerrar(v); } else cerrar(bt.valor);
      }));
      UI.$('#modal-raiz').appendChild(fondo);
      const f = fondo.querySelector('input,select,textarea');
      if (f) f.focus();
      if (alAbrir) alAbrir(fondo);
    });
  },
  confirmar(titulo, msg, textoOk = 'Confirmar', clase = 'btn-peligro') {
    return UI.modal({ titulo, icono: 'alert', cuerpo: `<p class="text-sm">${msg}</p>`,
      botones: [{ texto: 'Cancelar', valor: false }, { texto: textoOk, clase, valor: true }] });
  },

  opciones(select, items, { todos = null, valor = null, soloActivos = false } = {}) {
    const lista = soloActivos ? items.filter((i) => i.activo) : items;
    select.innerHTML = (todos ? `<option value="">${UI.esc(todos)}</option>` : '<option value="">Seleccione...</option>') +
      lista.map((i) => `<option value="${i.id}">${UI.esc(i.nombre)}</option>`).join('');
    if (valor != null) select.value = valor;
  },

  filtrosDe(form) {
    const o = {};
    new FormData(form).forEach((v, k) => { o[k] = typeof v === 'string' ? v.trim() : v; });
    return o;
  },
  debounce(fn, ms = 300) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; },
  vacioFila(cols, msg) { return `<tr><td colspan="${cols}" class="text-center text-muted py-8">${msg}</td></tr>`; },
};

const App = {
  vistaActual: null,

  async iniciar() {
    Iconos.hidratar();
    App.reloj();
    setInterval(App.reloj, 30000);
    try {
      const e = await Api.estado_inicial();
      Object.assign(Estado, { config: e.config, usuario: e.usuario, catalogos: e.catalogos, token: e.token, sistema: e.sistema });
    } catch (err) { UI.error(err); }
    UI.$('#hdr-usuario').textContent = Estado.usuario.usuario || 'Archivo';
    App.aplicarTema();
    App.aplicarRoles();
    UI.$$('#menu [data-vista]').forEach((b) => b.addEventListener('click', () => App.ir(b.dataset.vista)));
    document.addEventListener('click', (ev) => { const b = ev.target.closest('[data-ir]'); if (b) App.ir(b.dataset.ir); });
    UI.$('#btn-salir').addEventListener('click', App.salir);
    UI.$('#btn-tema').addEventListener('click', () => App.guardarPreferencias({ tema: Estado.config.tema === 'oscuro' ? 'claro' : 'oscuro' }));
    Object.values(Vistas).forEach((v) => v.iniciar && v.iniciar());
    App.ir('inicio');
  },

  reloj() {
    const d = new Date();
    const p = (n) => String(n).padStart(2, '0');
    UI.$('#hdr-fecha').textContent = UI.fecha(`${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`);
  },

  ir(nombre) {
    const v = Vistas[nombre];
    if (!v) return;
    const boton = UI.$(`#menu [data-vista="${nombre}"]`);
    if (boton && boton.classList.contains('hidden')) return UI.toast('Su rol no tiene acceso a este módulo.', 'warn');
    UI.$$('.vista').forEach((s) => s.classList.add('hidden'));
    UI.$(`#vista-${nombre}`).classList.remove('hidden');
    UI.$$('#menu .nav-btn').forEach((b) => b.classList.toggle('activo', b.dataset.vista === nombre));
    UI.$('#titulo-vista').textContent = v.titulo;
    UI.$('#subtitulo-vista').textContent = v.subtitulo;
    App.vistaActual = nombre;
    UI.$('#contenido').scrollTop = 0;
    v.mostrar && v.mostrar();
  },

  aplicarTema() {
    const oscuro = Estado.config.tema === 'oscuro';
    document.documentElement.classList.toggle('dark', oscuro);
    const b = UI.$('#btn-tema');
    b.innerHTML = Iconos.svg(oscuro ? 'sun' : 'moon');
    if (window.Chart) {
      Chart.defaults.color = oscuro ? '#93A3BD' : '#64748B';
      Chart.defaults.borderColor = oscuro ? 'rgba(147,163,189,.15)' : 'rgba(100,116,139,.15)';
    }
    document.dispatchEvent(new Event('tema-cambiado'));
  },

  aplicarRoles() {
    const rol = Estado.usuario.rol || 'Administrador';
    UI.$$('[data-roles]').forEach((el) => el.classList.toggle('hidden', !el.dataset.roles.split(',').includes(rol)));
  },

  async guardarPreferencias(p) {
    try {
      Estado.config = await Api.guardar_preferencias(p);
      App.aplicarTema();
      App.reloj();
      Vistas.configuracion && Vistas.configuracion.pintarPreferencias();
      if (App.vistaActual && Vistas[App.vistaActual].mostrar && p.formato_fecha) Vistas[App.vistaActual].mostrar();
      UI.toast('Preferencias guardadas.', 'ok');
    } catch (e) { UI.error(e); }
  },

  async refrescarCatalogos() {
    Estado.catalogos = await Api.catalogos();
    document.dispatchEvent(new Event('catalogos-cambiados'));
  },

  async salir() {
    if (Vistas.escanear && Vistas.escanear.hayTrabajoPendiente()) {
      const ok = await UI.confirmar('Salir del sistema', 'Hay un documento digitalizado sin guardar. ¿Desea salir de todos modos?', 'Salir');
      if (!ok) return;
    } else {
      const ok = await UI.confirmar('Salir del sistema', '¿Desea cerrar el Sistema de Gestión Documental?', 'Salir', 'btn-marino');
      if (!ok) return;
    }
    try { await Api.descartar_escaneo(); await Api.salir(); } catch (e) { UI.error(e); }
    if (!window.pywebview) window.close();
  },
};

/* Paleta multicolor compartida por los gráficos */
const PALETA = ['#0056D2', '#10B981', '#F59E0B', '#8B5CF6', '#EF4444', '#06B6D4', '#EC4899', '#0A367A', '#84CC16', '#F97316', '#64748B', '#14B8A6'];

document.addEventListener('DOMContentLoaded', App.iniciar);
