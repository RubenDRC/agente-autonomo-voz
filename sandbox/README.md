# Banco Sandbox

Entorno de pruebas para agentes autónomos de navegación web. Simula la banca en línea de un banco colombiano ficticio, con el flujo completo de una transferencia **Bre-B**.

Todo ocurre en el navegador: no hay backend, no hay peticiones de red, no se envía ni se guarda ningún dato. El estado vive en `sessionStorage` y desaparece al cerrar la pestaña.

## Levantar en localhost

Desde esta carpeta:

```bash
python3 -m http.server 5173
```

Y abre `http://localhost:5173`.

Alternativas equivalentes:

```bash
npx serve -l 5173      # Node
php -S localhost:5173  # PHP
```

> Sirve por HTTP, no abras los archivos con `file://`. Con `file://` algunos navegadores bloquean `sessionStorage` y la sesión no se mantiene entre páginas.

## Credenciales

| Dato | Valor |
|---|---|
| Usuario | `demo.usuario` |
| Clave | `Sandbox2026` |
| Clave dinámica | `123456` |

## Recorrido

```
index.html → login.html → inicio.html → transferencia.html → confirmar.html → comprobante.html
                                     ├→ movimientos.html
                                     ├→ certificados.html → certificado.html
                                     ├→ ayuda.html
                                     └→ seccion.html?s=… (caminos cerrados a propósito)
```

Las páginas internas redirigen a `login.html?motivo=sesion` si no hay sesión activa, así que el agente no puede saltarse el login por URL directa.

## Llaves Bre-B reconocidas

| Llave | Titular | Entidad |
|---|---|---|
| `@lucia` | Lucía Restrepo Gil | Banco Andes |
| `@marco` | Marco Peña Ruiz | Nequi |
| `@ferreteria` | Ferretería El Tornillo | Bancolombia |
| `3105558842` | Diana Ospina Cárdenas | Daviplata |
| `1024587963` | Julián Arias Mejía | Banco Sandbox |
| `pagos@tienda.co` | Tienda Central S.A.S. | Davivienda |

Cualquier otra llave produce un error de "llave no encontrada".

## Casos de fallo deterministas

Sirven para verificar que el agente lee errores en vez de seguir de largo:

| Caso | Cómo provocarlo | Resultado |
|---|---|---|
| Credenciales incorrectas | Cualquier clave distinta de `Sandbox2026` | Alerta en `#alerta-login` |
| Campos vacíos | Enviar el formulario sin llenarlo | Error bajo cada campo |
| Llave inexistente | `@noexiste` | Error bajo el campo de llave |
| Monto bajo el mínimo | `500` | "El monto mínimo por envío es $ 1.000" |
| Monto sobre el máximo | `25000000` | "El monto máximo por envío es $ 20.000.000" |
| Saldo insuficiente | `5000000` desde ahorros | Alerta en `#alerta-transferencia` |
| Clave dinámica errada | `999999` | Alerta en `#alerta-confirmar` |
| Sesión expirada | Abrir `inicio.html` sin login | Redirección al login |
| Camino cerrado | Botón "Pagar facturas" | Pantalla de sección no disponible |
| Certificado sin tipo | Generar sin elegir tipo | Error bajo el campo de tipo |
| Año sin datos | Certificado tributario 2023 sobre cuenta corriente | Alerta en `#alerta-certificado` |
| Búsqueda sin resultados | Escribir `zzz` en preguntas frecuentes | Mensaje en `sin-resultados` |

La consulta de llave tiene una latencia simulada de 600 ms y deshabilita el botón mientras responde: útil para probar esperas.

## Selectores

Cada elemento interactivo tiene `id` y `data-testid` estables. El panel inferior derecho ("Panel de pruebas") muestra la pantalla actual, el estado de la sesión, un botón **Ver testids** que dibuja los identificadores sobre la página, y **Reiniciar**, que borra el estado y vuelve a la portada.

Los principales:

| Pantalla | `data-testid` |
|---|---|
| Portada | `ir-a-login`, `ingresar-superior`, `conocer-breb` |
| Login | `campo-usuario`, `campo-clave`, `boton-entrar`, `alerta-login` |
| Inicio | `accion-breb`, `accion-movimientos`, `saldo-ahorros`, `saldo-corriente`, `cerrar-sesion` |
| Transferencia | `campo-origen`, `campo-llave`, `boton-consultar-llave`, `destino-titular`, `campo-monto`, `campo-descripcion`, `boton-continuar` |
| Confirmación | `resumen-monto`, `campo-clave-dinamica`, `boton-confirmar`, `boton-cancelar` |
| Comprobante | `mensaje-exito`, `comprobante-numero`, `comprobante-monto` |
| Movimientos | `tabla-movimientos`, `filtro-cuenta`, `movimiento-0` |
| Preguntas frecuentes | `campo-buscar-pregunta`, `conteo-resultados`, `pregunta-que-es-llave`, `abrir-que-es-llave`, `respuesta-que-es-llave`, `sin-resultados` |
| Certificados | `campo-producto`, `campo-tipo`, `campo-anio`, `campo-dirigido`, `boton-generar-certificado` |
| Certificado | `documento-certificado`, `certificado-folio`, `certificado-verificacion`, `dato-saldo`, `boton-descargar` |

## Preguntas frecuentes

`ayuda.html` trae 14 preguntas en cuatro grupos (Bre-B, Seguridad, Certificados, Productos), dentro de elementos `<details>`. El buscador filtra por título y por texto de la respuesta, oculta los encabezados de grupo que quedan vacíos y actualiza el contador.

Superficies de prueba: expandir y contraer, escribir en el buscador y leer el conteo, llegar a cero resultados.

## Certificados

`certificados.html` pide producto, tipo y destinatario; `certificado.html` renderiza el documento. Tres tipos:

| Tipo | Contenido |
|---|---|
| Titularidad | Producto, número, apertura y estado. Sin saldo. |
| Titularidad con saldo | Lo anterior más el saldo, escrito en cifras y en letras. |
| Tributario | Saldo a 31 de diciembre, rendimientos y retención del año elegido. |

El tributario pide un año adicional y rechaza los anteriores a la apertura de la cuenta: la corriente se abrió en 2023, así que pedir 2023 o antes sobre ese producto produce un error controlado.

Cada certificado lleva folio (`CERT-AAAA-NNNNNN`) y código de verificación aleatorios, así que dos ejecuciones nunca dan el mismo documento. El botón **Descargar o imprimir** abre el diálogo de impresión del navegador; hay CSS de impresión que oculta encabezado, botones y panel de pruebas para que salga solo el documento.

La expedición tarda 900 ms a propósito, con el botón deshabilitado mientras responde.

## Extender el entorno

- **Llaves y credenciales**: objeto `LLAVES` y `CREDENCIALES` en `assets/app.js`.
- **Saldos y movimientos iniciales**: objeto `INICIAL` en `assets/app.js`.
- **Preguntas**: arreglo `PREGUNTAS` en `ayuda.html`. El grupo se toma del campo `grupo`.
- **Datos del titular** que salen en el certificado: objeto `titular` dentro de `INICIAL` en `assets/app.js`.
- **Paleta**: variables `--brand` y `--brand-dim` al inicio de `assets/styles.css`.
- **Nuevas pantallas**: copia la cabecera de `movimientos.html`, incluye `assets/app.js` y llama a `SB.exigirSesion(SB.leer())`.
