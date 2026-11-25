/* Visor PDF basado en pdf.js (offline). Zoom, escala, navegación, rotación y pantalla completa. */
pdfjsLib.GlobalWorkerOptions.workerSrc = '/static/vendor/pdf.worker.min.js';

class VisorPDF {
  /**
   * @param {HTMLElement} contenedor
   * @param {{rotar?: (grados:number, pagina:number)=>Promise<string|null>, vacio?: string}} opciones
   *   rotar: callback que rota el PDF real en Python y devuelve la nueva URL.
   */
  constructor(contenedor, opciones = {}) {
    this.op = opciones;
    this.escala = 1;
    this.pagina = 1;
    this.doc = null;
    this.url = null;
    this.ajustar = true; // primer render: ajustar al ancho
    this.render = 0;
    contenedor.innerHTML = `
      <div class="visor flex-1 min-w-0">
        <div class="visor-barra">
          <button class="btn-ico" data-a="zoom-out" title="Alejar (−)">${Iconos.svg('zoom-out')}</button>
          <select class="inp !w-[104px] !py-1.5 text-sm flex-none" data-a="escala" title="Escala">
            <option value="ancho">Ajustar</option><option value="0.5">50%</option><option value="0.75">75%</option>
            <option value="1" selected>100%</option><option value="1.25">125%</option><option value="1.5">150%</option>
            <option value="2">200%</option><option value="3">300%</option></select>
          <button class="btn-ico" data-a="zoom-in" title="Acercar (+)">${Iconos.svg('zoom-in')}</button>
          <span class="sep-v"></span>
          <button class="btn-ico" data-a="prev" title="Página anterior">${Iconos.svg('chev-left')}</button>
          <span class="text-sm text-muted min-w-[56px] text-center whitespace-nowrap" data-a="pag">- / -</span>
          <button class="btn-ico" data-a="next" title="Página siguiente">${Iconos.svg('chev-right')}</button>
          ${opciones.rotar ? `<span class="sep-v"></span>
          <button class="btn-ico" data-a="rot-left" title="Rotar a la izquierda">${Iconos.svg('rot-left')}</button>
          <button class="btn-ico" data-a="rot-right" title="Rotar a la derecha">${Iconos.svg('rot-right')}</button>` : ''}
          <button class="btn-ico ml-auto" data-a="full" title="Pantalla completa">${Iconos.svg('expand')}</button>
        </div>
        <div class="visor-area" data-a="area"></div>
      </div>`;
    this.raiz = contenedor.querySelector('.visor');
    this.area = contenedor.querySelector('[data-a=area]');
    this.selEscala = contenedor.querySelector('[data-a=escala]');
    this.lblPag = contenedor.querySelector('[data-a=pag]');
    const on = (a, fn) => { const el = contenedor.querySelector(`[data-a="${a}"]`); if (el) el.addEventListener('click', fn); };
    on('zoom-in', () => this.setEscala(Math.min(4, +(this.escala + 0.25).toFixed(2))));
    on('zoom-out', () => this.setEscala(Math.max(0.25, +(this.escala - 0.25).toFixed(2))));
    on('prev', () => this.irA(this.pagina - 1));
    on('next', () => this.irA(this.pagina + 1));
    on('rot-left', () => this.rotar(-90));
    on('rot-right', () => this.rotar(90));
    on('full', () => this.pantallaCompleta());
    this.selEscala.addEventListener('change', () => {
      if (this.selEscala.value === 'ancho') { this.ajustar = true; this.dibujar(); } else this.setEscala(+this.selEscala.value);
    });
    this.area.addEventListener('wheel', (e) => {
      if (!e.ctrlKey) return;
      e.preventDefault();
      this.setEscala(Math.min(4, Math.max(0.25, +(this.escala + (e.deltaY < 0 ? 0.1 : -0.1)).toFixed(2))));
    }, { passive: false });
    document.addEventListener('fullscreenchange', () => { if (this.doc) setTimeout(() => this.dibujar(), 80); });
    this.vacio(opciones.vacio || 'Sin documento para mostrar');
  }

  vacio(msg) {
    this.doc = null; this.url = null;
    this.area.innerHTML = `<div class="visor-vacio">${Iconos.svg('file')}<div>${msg}</div></div>`;
    this.lblPag.textContent = '- / -';
  }

  async cargar(url, { mantenerPagina = false } = {}) {
    this.url = url;
    if (!mantenerPagina) { this.pagina = 1; this.ajustar = true; }
    this.area.innerHTML = `<div class="visor-vacio"><div class="spinner !border-blue-200 !border-t-blue-600"></div>Cargando documento...</div>`;
    try {
      if (this.doc) this.doc.destroy();
      this.doc = await pdfjsLib.getDocument({ url }).promise;
      this.pagina = Math.min(this.pagina, this.doc.numPages);
      await this.dibujar();
    } catch (e) {
      console.error(e);
      this.vacio('No fue posible abrir el documento PDF.');
    }
  }

  setEscala(e) {
    this.ajustar = false;
    this.escala = e;
    const opt = [...this.selEscala.options].find((o) => +o.value === e);
    if (!opt) {
      let tmp = this.selEscala.querySelector('option[data-tmp]');
      if (!tmp) { tmp = document.createElement('option'); tmp.dataset.tmp = 1; this.selEscala.appendChild(tmp); }
      tmp.value = e; tmp.textContent = Math.round(e * 100) + '%';
    }
    this.selEscala.value = String(e);
    this.dibujar();
  }

  irA(n) {
    if (!this.doc || n < 1 || n > this.doc.numPages) return;
    this.pagina = n;
    this.dibujar();
  }

  async dibujar() {
    if (!this.doc) return;
    const id = ++this.render;
    const page = await this.doc.getPage(this.pagina);
    if (this.ajustar) {
      const base = page.getViewport({ scale: 1 });
      const disp = Math.max(200, this.area.clientWidth - 40);
      this.escala = +(disp / base.width).toFixed(3);
      this.selEscala.value = 'ancho';
    }
    const dpr = window.devicePixelRatio || 1;
    const vp = page.getViewport({ scale: this.escala });
    const canvas = document.createElement('canvas');
    canvas.width = Math.floor(vp.width * dpr);
    canvas.height = Math.floor(vp.height * dpr);
    canvas.style.width = Math.floor(vp.width) + 'px';
    canvas.style.height = Math.floor(vp.height) + 'px';
    await page.render({ canvasContext: canvas.getContext('2d'), viewport: vp,
      transform: dpr !== 1 ? [dpr, 0, 0, dpr, 0, 0] : null }).promise;
    if (id !== this.render) return; // un render más nuevo ya empezó
    this.area.innerHTML = '';
    this.area.appendChild(canvas);
    this.lblPag.textContent = `${this.pagina} / ${this.doc.numPages}`;
  }

  async rotar(grados) {
    if (!this.doc || !this.op.rotar) return;
    const nuevaUrl = await this.op.rotar(grados, this.pagina);
    if (nuevaUrl) await this.cargar(nuevaUrl, { mantenerPagina: true });
  }

  pantallaCompleta() {
    if (document.fullscreenElement) document.exitFullscreen();
    else this.raiz.requestFullscreen().catch(() => UI.toast('Pantalla completa no disponible.', 'warn'));
  }
}

/** Renderiza la primera página de un PDF en un canvas (miniatura). */
async function miniaturaPDF(url, canvas, ancho = 160) {
  try {
    const doc = await pdfjsLib.getDocument({ url }).promise;
    const page = await doc.getPage(1);
    const base = page.getViewport({ scale: 1 });
    const vp = page.getViewport({ scale: (ancho * 2) / base.width });
    canvas.width = vp.width; canvas.height = vp.height;
    canvas.style.width = ancho + 'px';
    await page.render({ canvasContext: canvas.getContext('2d'), viewport: vp }).promise;
    doc.destroy();
  } catch (e) { console.error(e); }
}
