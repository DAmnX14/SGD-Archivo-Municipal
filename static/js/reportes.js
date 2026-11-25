/* Módulo Reportes y Estadísticas */
Vistas.reportes = (() => {
  let gBarras = null, gTorta = null, datos = null;

  const filtros = () => ({ periodo: UI.$('#r-periodo').value, direccion_id: UI.$('#r-direccion').value, tipo_id: UI.$('#r-tipo').value });
  const filtrosTexto = () => ['#r-periodo', '#r-direccion', '#r-tipo']
    .map((s) => { const el = UI.$(s); return `${el.previousElementSibling.textContent}: ${el.selectedOptions[0].textContent}`; }).join(' · ');

  function llenarFiltros() {
    UI.opciones(UI.$('#r-direccion'), Estado.catalogos.direcciones, { todos: 'Todas', valor: UI.$('#r-direccion').value });
    UI.opciones(UI.$('#r-tipo'), Estado.catalogos.tipos, { todos: 'Todos', valor: UI.$('#r-tipo').value });
  }

  /* Plugin: escribe el porcentaje sobre cada porción de la torta */
  const pluginPorcentajes = {
    id: 'porcentajes',
    afterDatasetsDraw(chart) {
      if (chart.config.type !== 'doughnut') return;
      const { ctx } = chart;
      const ds = chart.data.datasets[0];
      const total = ds.data.reduce((a, b) => a + b, 0);
      chart.getDatasetMeta(0).data.forEach((arc, i) => {
        const v = ds.data[i];
        if (!total || v / total < 0.04) return;
        const p = arc.tooltipPosition();
        ctx.save();
        ctx.fillStyle = '#fff'; ctx.font = 'bold 12px "Segoe UI", sans-serif';
        ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
        ctx.fillText(`${Math.round((v * 100) / total)}%`, p.x, p.y);
        ctx.restore();
      });
    },
  };

  /* Fondo sólido para que las imágenes exportadas no queden transparentes */
  const pluginFondo = {
    id: 'fondo',
    beforeDraw(chart) {
      const { ctx } = chart;
      ctx.save();
      ctx.globalCompositeOperation = 'destination-over';
      ctx.fillStyle = getComputedStyle(document.documentElement).getPropertyValue('--c-surface').trim() || '#fff';
      ctx.fillRect(0, 0, chart.width, chart.height);
      ctx.restore();
    },
  };

  async function cargar() {
    try {
      datos = await Api.reporte(filtros());
      pintar();
    } catch (e) { UI.error(e); }
  }

  function pintar() {
    const k = datos.kpis;
    UI.$('#k-total').textContent = k.total.toLocaleString('es-AR');
    UI.$('#k-tasa').textContent = `${k.tasa}%`;
    UI.$('#k-tasa-bar').style.width = `${k.tasa}%`;
    UI.$('#k-dirs').textContent = k.direcciones;
    UI.$('#k-ultima').textContent = k.ultima_fecha ? UI.fecha(k.ultima_fecha) : '-';
    UI.$('#k-ultimo-reg').textContent = k.ultimo_registro || 'sin cargas';

    if (gBarras) gBarras.destroy();
    gBarras = new Chart(UI.$('#g-barras'), {
      type: 'bar',
      data: { labels: datos.por_direccion.map((d) => d.nombre),
        datasets: [{ label: 'Documentos', data: datos.por_direccion.map((d) => d.cantidad),
          backgroundColor: datos.por_direccion.map((_, i) => PALETA[i % PALETA.length]), borderRadius: 6, maxBarThickness: 56 }] },
      options: { maintainAspectRatio: false, plugins: { legend: { display: false } },
        scales: { y: { beginAtZero: true, ticks: { precision: 0 } }, x: { grid: { display: false } } } },
      plugins: [pluginFondo],
    });

    if (gTorta) gTorta.destroy();
    const total = datos.por_tipo.reduce((a, b) => a + b.cantidad, 0);
    gTorta = new Chart(UI.$('#g-torta'), {
      type: 'doughnut',
      data: { labels: datos.por_tipo.map((d) => d.nombre),
        datasets: [{ data: datos.por_tipo.map((d) => d.cantidad), backgroundColor: datos.por_tipo.map((_, i) => PALETA[i % PALETA.length]),
          borderWidth: 2, borderColor: getComputedStyle(document.documentElement).getPropertyValue('--c-surface').trim() }] },
      options: { maintainAspectRatio: false, cutout: '45%',
        plugins: { legend: { position: 'right', labels: { boxWidth: 14, padding: 12,
          generateLabels: (ch) => Chart.overrides.doughnut.plugins.legend.labels.generateLabels(ch).map((l, i) => ({
            ...l, text: `${l.text} (${total ? Math.round((datos.por_tipo[i].cantidad * 100) / total) : 0}%)` })) } },
          tooltip: { callbacks: { label: (c) => ` ${c.label}: ${c.parsed} (${Math.round((c.parsed * 100) / total)}%)` } } } },
      plugins: [pluginPorcentajes, pluginFondo],
    });

    UI.$('#r-actividad').innerHTML = datos.recientes.length ? datos.recientes.map((d) => `<tr>
      <td class="font-semibold text-vivo">${UI.esc(d.nro_registro)}</td><td>${UI.esc(d.tipo)} ${UI.esc(d.numero)}</td>
      <td>${UI.esc(d.direccion)}</td><td class="max-w-[360px] truncate">${UI.esc(d.descripcion)}</td>
      <td>${UI.esc(d.usuario) || '-'}</td><td>${UI.fecha(d.fecha_carga, true)}</td></tr>`).join('')
      : UI.vacioFila(6, 'Sin actividad para los filtros seleccionados.');
  }

  /* Compone una imagen PNG del reporte: encabezado + KPIs + ambos gráficos */
  function componerImagen() {
    const W = 1600, H = 790;
    const c = document.createElement('canvas');
    c.width = W; c.height = H;
    const x = c.getContext('2d');
    const css = getComputedStyle(document.documentElement);
    const surface = css.getPropertyValue('--c-surface').trim(), app = css.getPropertyValue('--c-app').trim();
    const texto = css.getPropertyValue('--c-texto').trim(), muted = css.getPropertyValue('--c-muted').trim();
    x.fillStyle = app; x.fillRect(0, 0, W, H);
    x.fillStyle = '#0A367A'; x.fillRect(0, 0, W, 110);
    const logo = UI.$('#logo-img');
    if (logo && logo.complete && logo.naturalWidth) x.drawImage(logo, 30, 15, 80, 80);
    x.fillStyle = '#fff'; x.font = 'bold 30px "Segoe UI", sans-serif';
    x.fillText('Municipalidad de Libertador General San Martín', 130, 52);
    x.font = '18px "Segoe UI", sans-serif';
    x.fillText(`Reporte de Gestión Documental · ${filtrosTexto()}`, 130, 84);
    x.textAlign = 'right'; x.fillText(new Date().toLocaleString('es-AR'), W - 30, 52); x.textAlign = 'left';
    const k = datos.kpis;
    const kpis = [['Total digitalizados', k.total], ['Tasa de digitalización', `${k.tasa}%`], ['Direcciones registradas', k.direcciones],
      ['Última carga', k.ultima_fecha ? UI.fecha(k.ultima_fecha) : '-']];
    kpis.forEach(([l, v], i) => {
      const bx = 30 + i * 390;
      x.fillStyle = surface; x.beginPath(); x.roundRect(bx, 135, 365, 110, 12); x.fill();
      x.fillStyle = muted; x.font = '600 17px "Segoe UI", sans-serif'; x.fillText(l, bx + 22, 172);
      x.fillStyle = texto; x.font = 'bold 40px "Segoe UI", sans-serif'; x.fillText(String(v), bx + 22, 222);
    });
    const caja = (chart, titulo, bx, bw) => {
      x.fillStyle = surface; x.beginPath(); x.roundRect(bx, 270, bw, 490, 12); x.fill();
      x.fillStyle = '#0A367A'; x.beginPath(); x.roundRect(bx, 270, bw, 50, [12, 12, 0, 0]); x.fill();
      x.fillStyle = '#fff'; x.font = 'bold 19px "Segoe UI", sans-serif'; x.fillText(titulo, bx + 20, 302);
      const cv = chart.canvas;
      const esc = Math.min((bw - 40) / cv.width, 400 / cv.height);
      x.drawImage(cv, bx + (bw - cv.width * esc) / 2, 335, cv.width * esc, cv.height * esc);
    };
    caja(gBarras, 'Documentos por Dirección', 30, 930);
    caja(gTorta, 'Tipos de Documentos', 980, 590);
    return c.toDataURL('image/png');
  }

  async function exportar(tipo) {
    if (!datos) return;
    try {
      let ruta;
      if (tipo === 'pdf') {
        ruta = await UI.cargando('Generando PDF...', () => Api.exportar_pdf(filtros(),
          { barras: gBarras.toBase64Image('image/png', 1), torta: gTorta.toBase64Image('image/png', 1) }, filtrosTexto()));
      } else if (tipo === 'xlsx') {
        ruta = await UI.cargando('Generando Excel...', () => Api.exportar_excel(filtros(), filtrosTexto()));
      } else {
        ruta = await UI.cargando('Generando imagen...', () => Api.exportar_png(componerImagen()));
      }
      if (!ruta) return;
      const abrir = await UI.modal({ titulo: 'Exportación completada', icono: 'check-circle',
        cuerpo: `<p class="text-sm">El reporte se guardó en:</p><p class="font-mono text-xs bg-surface2 border border-borde rounded p-2 mt-2 break-all">${UI.esc(ruta)}</p>`,
        botones: [{ texto: 'Cerrar', valor: false }, { texto: 'Abrir archivo', clase: 'btn-primario', valor: true }] });
      if (abrir) await Api.abrir_archivo(ruta);
    } catch (e) { UI.error(e); }
  }

  function iniciar() {
    ['#r-periodo', '#r-direccion', '#r-tipo'].forEach((s) => UI.$(s).addEventListener('change', cargar));
    UI.$('#r-exp-pdf').addEventListener('click', () => exportar('pdf'));
    UI.$('#r-exp-xlsx').addEventListener('click', () => exportar('xlsx'));
    UI.$('#r-exp-png').addEventListener('click', () => exportar('png'));
    document.addEventListener('catalogos-cambiados', llenarFiltros);
    document.addEventListener('tema-cambiado', () => { if (App.vistaActual === 'reportes' && datos) pintar(); });
  }

  function mostrar() { llenarFiltros(); cargar(); }

  return { titulo: 'Reportes y Estadísticas', subtitulo: 'Indicadores de digitalización del archivo', iniciar, mostrar, componerImagen };
})();
