/* ==========================================================================
   Banco Sandbox — lógica del entorno de pruebas
   Todo ocurre en el navegador. No hay peticiones de red ni envío de datos.
   Estado simulado en sessionStorage: se borra al cerrar la pestaña.
   ========================================================================== */

const SB = (() => {
  const CLAVE = 'sandbox.estado';

  const INICIAL = {
    sesion: false,
    usuario: null,
    titular: {
      nombre: 'DIEGO ALEJANDRO MORALES CASTAÑO',
      documento: 'C.C. 1.024.587.963',
      ciudad: 'Bogotá D.C.'
    },
    cuentas: [
      { id: 'ahorros',   nombre: 'Cuenta de ahorros',  numero: '••••4821', saldo: 4850320, completo: '3120004821', apertura: '2021-03-14' },
      { id: 'corriente', nombre: 'Cuenta corriente',   numero: '••••7734', saldo: 1230000, completo: '4580017734', apertura: '2023-09-02' }
    ],
    movimientos: [
      { fecha: '2026-08-11', concepto: 'Nómina Andes Ltda.',        cuenta: 'ahorros',   valor:  3200000 },
      { fecha: '2026-08-10', concepto: 'Supermercado La Plaza',     cuenta: 'ahorros',   valor:  -184500 },
      { fecha: '2026-08-09', concepto: 'Bre-B enviada a @lucia',    cuenta: 'ahorros',   valor:  -120000 },
      { fecha: '2026-08-08', concepto: 'Recarga celular',           cuenta: 'ahorros',   valor:   -30000 },
      { fecha: '2026-08-06', concepto: 'Bre-B recibida de @marco',  cuenta: 'ahorros',   valor:   450000 },
      { fecha: '2026-08-05', concepto: 'Arriendo oficina',          cuenta: 'corriente', valor: -1800000 },
      { fecha: '2026-08-03', concepto: 'Pago factura energía',      cuenta: 'ahorros',   valor:  -212400 },
      { fecha: '2026-08-01', concepto: 'Transferencia recibida',    cuenta: 'corriente', valor:  2000000 }
    ],
    borrador: null,   // transferencia en curso
    ultima: null      // último comprobante generado
  };

  // Directorio de llaves Bre-B reconocidas por el entorno.
  const LLAVES = {
    '@lucia':          { titular: 'Lucía Restrepo Gil',   entidad: 'Banco Jav' },
    '@marco':          { titular: 'Marco Peña Ruiz',      entidad: 'BancoYa' },
    '@ferreteria':     { titular: 'Ferretería El Tornillo', entidad: 'Payme' },
    '3105558842':      { titular: 'Diana Ospina Cárdenas', entidad: 'Cash' },
    '1024587963':      { titular: 'Julián Arias Mejía',   entidad: 'JaveMoney' },
    'pagos@tienda.co': { titular: 'Tienda Central S.A.S.', entidad: 'TiendaBarrio' }
  };

  const CREDENCIALES = { usuario: 'demo.usuario', clave: 'Sandbox2026' };
  const CLAVE_DINAMICA = '123456';

  function leer() {
    try {
      const bruto = sessionStorage.getItem(CLAVE);
      if (bruto) return JSON.parse(bruto);
    } catch (e) { /* estado corrupto: se reinicia */ }
    const nuevo = structuredClone(INICIAL);
    guardar(nuevo);
    return nuevo;
  }

  function guardar(estado) {
    sessionStorage.setItem(CLAVE, JSON.stringify(estado));
  }

  function reiniciar() {
    sessionStorage.removeItem(CLAVE);
  }

  function pesos(valor) {
    return '$ ' + Math.abs(valor).toLocaleString('es-CO');
  }

  function cuenta(estado, id) {
    return estado.cuentas.find(c => c.id === id);
  }

  function buscarLlave(valor) {
    return LLAVES[valor.trim().toLowerCase()] || null;
  }

  function comprobante() {
    const n = Math.floor(100000000 + Math.random() * 899999999);
    return 'BRB-' + n;
  }

  /** Folio de certificado: CERT-AAAA-NNNNNN */
  function folio() {
    const n = Math.floor(100000 + Math.random() * 899999);
    return 'CERT-' + new Date().getFullYear() + '-' + n;
  }

  /** Fecha larga en español: "13 de agosto de 2026" */
  function fechaLarga(fecha) {
    const d = fecha ? new Date(fecha + 'T00:00:00') : new Date();
    return d.toLocaleDateString('es-CO', { day: 'numeric', month: 'long', year: 'numeric' });
  }

  /* --- Cifras en letras (hasta 999.999.999) ------------------------------ */

  const UNI = ['', 'uno', 'dos', 'tres', 'cuatro', 'cinco', 'seis', 'siete', 'ocho', 'nueve',
    'diez', 'once', 'doce', 'trece', 'catorce', 'quince', 'dieciséis', 'diecisiete',
    'dieciocho', 'diecinueve', 'veinte', 'veintiuno', 'veintidós', 'veintitrés',
    'veinticuatro', 'veinticinco', 'veintiséis', 'veintisiete', 'veintiocho', 'veintinueve'];
  const DEC = ['', '', '', 'treinta', 'cuarenta', 'cincuenta', 'sesenta', 'setenta', 'ochenta', 'noventa'];
  const CEN = ['', 'ciento', 'doscientos', 'trescientos', 'cuatrocientos', 'quinientos',
    'seiscientos', 'setecientos', 'ochocientos', 'novecientos'];

  function tres(n) {
    if (n < 30) return UNI[n];
    if (n < 100) {
      const d = Math.floor(n / 10), u = n % 10;
      return DEC[d] + (u ? ' y ' + UNI[u] : '');
    }
    if (n === 100) return 'cien';
    const c = Math.floor(n / 100), r = n % 100;
    return CEN[c] + (r ? ' ' + tres(r) : '');
  }

  function miles(n) {
    if (n < 1000) return tres(n);
    const m = Math.floor(n / 1000), r = n % 1000;
    const pre = m === 1 ? 'mil' : tres(m) + ' mil';
    return pre + (r ? ' ' + tres(r) : '');
  }

  function enLetras(n) {
    n = Math.round(Math.abs(n));
    if (n === 0) return 'cero';
    let texto;
    if (n < 1000000) {
      texto = miles(n);
    } else {
      const m = Math.floor(n / 1000000), r = n % 1000000;
      const pre = m === 1 ? 'un millón' : miles(m) + ' millones';
      texto = pre + (r ? ' ' + miles(r) : '');
    }
    // Apócope: "uno mil" → "un mil", "veintiuno" → "veintiún"
    return texto
      .replace(/veintiuno\b/g, 'veintiún')
      .replace(/\buno mil\b/g, 'un mil')
      .replace(/uno$/, 'un');
  }

  /** "CUATRO MILLONES ... PESOS M/CTE ($ 4.850.320)" */
  function montoFormal(valor) {
    return enLetras(valor).toUpperCase() + ' PESOS M/CTE (' + pesos(valor) + ')';
  }

  /** Redirige al login si la página exige sesión. */
  function exigirSesion(estado) {
    if (!estado.sesion) {
      window.location.replace('login.html?motivo=sesion');
      return false;
    }
    return true;
  }

  return {
    leer, guardar, reiniciar, pesos, cuenta, buscarLlave,
    comprobante, folio, fechaLarga, enLetras, montoFormal,
    exigirSesion, CREDENCIALES, CLAVE_DINAMICA
  };
})();

/* --- Panel de pruebas ---------------------------------------------------- */

function montarPanel() {
  const estado = SB.leer();
  const panel = document.createElement('aside');
  panel.className = 'probe';
  panel.dataset.open = 'false';
  panel.dataset.testid = 'panel-pruebas';
  panel.innerHTML = `
    <button type="button" class="probe__toggle" data-testid="panel-alternar" aria-expanded="false">
      <span><span class="probe__dot">●</span> Panel de pruebas</span><span aria-hidden="true">▴</span>
    </button>
    <div class="probe__body">
      <div class="probe__row"><span>Pantalla</span><b id="probe-ruta"></b></div>
      <div class="probe__row"><span>Sesión</span><b id="probe-sesion"></b></div>
      <div class="probe__row"><span>Usuario</span><b id="probe-usuario"></b></div>
      <div class="probe__btns">
        <button type="button" id="probe-ids" data-testid="panel-ver-ids">Ver testids</button>
        <button type="button" id="probe-reset" data-testid="panel-reiniciar">Reiniciar</button>
      </div>
    </div>`;
  document.body.appendChild(panel);

  const archivo = window.location.pathname.split('/').pop() || 'index.html';
  panel.querySelector('#probe-ruta').textContent = archivo;
  panel.querySelector('#probe-sesion').textContent = estado.sesion ? 'activa' : 'sin iniciar';
  panel.querySelector('#probe-usuario').textContent = estado.usuario || '—';

  const alternar = panel.querySelector('.probe__toggle');
  alternar.addEventListener('click', () => {
    const abierto = panel.dataset.open === 'true';
    panel.dataset.open = String(!abierto);
    alternar.setAttribute('aria-expanded', String(!abierto));
    alternar.lastElementChild.textContent = abierto ? '▴' : '▾';
  });

  panel.querySelector('#probe-ids').addEventListener('click', () => {
    document.body.classList.toggle('show-ids');
  });

  panel.querySelector('#probe-reset').addEventListener('click', () => {
    SB.reiniciar();
    window.location.href = 'index.html';
  });
}

/* --- Cierre de sesión ---------------------------------------------------- */

function montarSalir() {
  const boton = document.querySelector('[data-accion="salir"]');
  if (!boton) return;
  boton.addEventListener('click', () => {
    const estado = SB.leer();
    estado.sesion = false;
    estado.usuario = null;
    estado.borrador = null;
    SB.guardar(estado);
    window.location.href = 'index.html';
  });
}

/* --- Nombre de usuario en el encabezado ---------------------------------- */

function montarUsuario() {
  const destino = document.querySelector('[data-campo="usuario-activo"]');
  if (!destino) return;
  const estado = SB.leer();
  destino.textContent = estado.usuario ? 'Hola, ' + estado.usuario : '';
}

document.addEventListener('DOMContentLoaded', () => {
  montarPanel();
  montarSalir();
  montarUsuario();
});
