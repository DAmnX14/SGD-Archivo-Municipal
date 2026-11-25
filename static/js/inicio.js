/* Módulo Inicio (Dashboard rápido) */
Vistas.inicio = (() => {
  let grafico = null;
  const MESES = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic'];

  function estadoBadge(d) {
    return d.estado === 'Digitalizado' ? '<span class="badge badge-ok">Digitalizado</span>' : '<span class="badge badge-warn">Pendiente</span>';
  }

  async function mostrar() {
    try {
      const d = await Api.dashboard();
      UI.$('#ini-total').textContent = d.total.toLocaleString('es-AR');
      UI.$('#ini-mes').textContent = d.mes;
      UI.$('#ini-hoy').textContent = d.hoy;
      UI.$('#ini-paginas').textContent = d.paginas.toLocaleString('es-AR');
      UI.$('#ini-peso').textContent = d.peso_mb.toLocaleString('es-AR');
      UI.$('#ini-ult-resp').textContent = d.ultimo_respaldo ? UI.fecha(d.ultimo_respaldo, true) : 'nunca';
      UI.$('#ini-pend').textContent = d.pendientes;
      UI.$('#ini-pend-wrap').classList.toggle('hidden', !d.pendientes);
      UI.$('#ini-recientes').innerHTML = d.recientes.length ? d.recientes.map((r) => `<tr>
        <td class="font-semibold text-vivo">${UI.esc(r.nro_registro)}</td><td>${UI.esc(r.tipo)} ${UI.esc(r.numero)}</td>
        <td>${UI.esc(r.direccion)}</td><td class="max-w-[340px] truncate">${UI.esc(r.descripcion)}</td>
        <td>${UI.fecha(r.fecha_carga, true)}</td><td>${estadoBadge(r)}</td></tr>`).join('') : UI.vacioFila(6, 'Sin documentos cargados.');

      // últimos 12 meses (completa meses vacíos)
      const mapa = Object.fromEntries(d.meses.map((m) => [m.mes, m.cantidad]));
      const etiquetas = [], valores = [];
      const hoy = new Date();
      for (let i = 11; i >= 0; i--) {
        const f = new Date(hoy.getFullYear(), hoy.getMonth() - i, 1);
        const k = `${f.getFullYear()}-${String(f.getMonth() + 1).padStart(2, '0')}`;
        etiquetas.push(`${MESES[f.getMonth()]} ${String(f.getFullYear()).slice(2)}`);
        valores.push(mapa[k] || 0);
      }
      if (grafico) grafico.destroy();
      const ctx = UI.$('#ini-grafico').getContext('2d');
      const grad = ctx.createLinearGradient(0, 0, 0, 260);
      grad.addColorStop(0, 'rgba(0,86,210,.35)'); grad.addColorStop(1, 'rgba(0,86,210,0)');
      grafico = new Chart(ctx, {
        type: 'line',
        data: { labels: etiquetas, datasets: [{ label: 'Documentos', data: valores, borderColor: '#0056D2', backgroundColor: grad,
          fill: true, tension: .35, pointRadius: 4, pointBackgroundColor: '#0056D2' }] },
        options: { maintainAspectRatio: false, plugins: { legend: { display: false } },
          scales: { y: { beginAtZero: true, ticks: { precision: 0 } }, x: { grid: { display: false } } } },
      });
    } catch (e) { UI.error(e); }
  }

  function iniciar() {
    UI.$('#ini-respaldo').addEventListener('click', async () => {
      try {
        const r = await UI.cargando('Generando respaldo...', () => Api.realizar_respaldo());
        UI.toast(`Respaldo creado: ${r.archivo.split(/[\\/]/).pop()}`, 'ok');
        mostrar();
      } catch (e) { UI.error(e); }
    });
    document.addEventListener('tema-cambiado', () => { if (App.vistaActual === 'inicio') mostrar(); });
  }

  return { titulo: 'Inicio', subtitulo: 'Panel general del archivo municipal', mostrar, iniciar };
})();
