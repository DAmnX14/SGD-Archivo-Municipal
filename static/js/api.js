/* Puente JavaScript -> Python.
 * En la app de escritorio usa window.pywebview.api (js_api de pywebview).
 * En modo desarrollo (python app.py --navegador) usa POST /api/<metodo>?t=TOKEN.
 */
const Api = (() => {
  const tokenUrl = new URLSearchParams(location.search).get('t');
  let listo;

  const esperarPywebview = () => new Promise((resolve) => {
    if (window.pywebview && window.pywebview.api) return resolve('pywebview');
    if (tokenUrl) return resolve('http');
    window.addEventListener('pywebviewready', () => resolve('pywebview'), { once: true });
  });

  async function llamar(metodo, ...args) {
    listo = listo || esperarPywebview();
    const modo = await listo;
    let res;
    if (modo === 'pywebview') {
      res = await window.pywebview.api[metodo](...args);
    } else {
      const r = await fetch(`/api/${metodo}?t=${encodeURIComponent(tokenUrl)}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(args),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      res = await r.json();
    }
    if (!res || res.ok === false) throw new Error((res && res.error) || 'Error de comunicación con el sistema.');
    return res.data;
  }

  // Proxy: Api.consultar(filtros) === llamar('consultar', filtros)
  return new Proxy({ llamar }, {
    get: (obj, prop) => (prop in obj ? obj[prop] : (...a) => llamar(prop, ...a)),
  });
})();
