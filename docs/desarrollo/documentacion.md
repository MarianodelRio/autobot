# Documentación

Cómo se escribe, se comprueba y se publica esta documentación. Léelo antes de añadir o cambiar una página. El sitio se genera con Zensical (tema Material) a partir de `mkdocs.yml` y de la carpeta `docs/`.

## Escribirla y verla en local

Desde la raíz del repo, en el portátil:

| Comando | Qué hace |
| --- | --- |
| `make docs` | Sirve el sitio en `http://localhost:8100` y lo recarga al guardar. |
| `make docs-check` | Construye en modo estricto en `var/docs-site/`: un enlace roto, un snippet que no existe o una página fuera del nav falla. |

Ambos usan el grupo de dependencias `docs` del backend (`zensical==0.1.3` en `apps/backend/pyproject.toml`) y se ejecutan desde la raíz, porque los snippets resuelven sus rutas contra el directorio de trabajo. `var/docs-site/` está ignorado por git.

## Estructura y navegación

- La navegación vive en `nav` de `mkdocs.yml`. Una página que no está ahí no aparece en el menú: añade la ruta al `nav` en el mismo cambio.
- Las carpetas no siguen el nombre de la sección del menú: `docs/arquitectura/` es **Conceptos**, `docs/arquitectura/adr/` es **Decisiones** y `docs/procedimientos/` es **Operación**.
- `docs/README.md` es la página de Inicio.

## Convenciones

- Español claro, frases cortas. Código, identificadores y comandos, en inglés.
- Cada página empieza con un párrafo de "qué es y cuándo leerla", sigue con secciones `##` y termina con "Dónde está el código" y/o "Relacionado".
- **Referencias a código** en backticks, con la ruta desde la raíz y el símbolo, sin números de línea: `apps/backend/src/core/pack.py` (`Pack`). No uses enlaces Markdown a ficheros fuera de `docs/`: rompen la build estricta.
- **Enlaces entre páginas**: relativos a otro `.md`, con ancla si hace falta (`../procedimientos/despliegue.md#seccion`).
- **Snippets** para piezas pequeñas y estables de contrato. Dentro de un bloque de código, una línea `--8<-- "ruta/desde/la/raiz.py:10:40"` incrusta ese rango del fichero. Úsalos con moderación.
- **Diagramas** con Mermaid (bloque ` ```mermaid `): `flowchart`, `sequenceDiagram` o `stateDiagram-v2`, sencillos y comprobados contra el código.
- **Avisos** con admonitions: `!!! warning "Título"`, `!!! note` o `!!! tip`, con el cuerpo indentado 4 espacios.
- **Comandos de operación**: di siempre dónde se ejecutan (portátil o VPS) y con qué usuario. En el servidor, nunca `docker compose` a pelo: `deploy/scripts/compose.sh` y `deploy/scripts/manage.sh`, o `make prod-compose` y `make prod-manage` desde el portátil.
- Cada concepto se explica en un solo sitio; desde los demás se enlaza.

## Páginas generadas y coherencia

- `docs/referencia/api-panel.md` se genera con `apps/backend/src/tools/docs/openapi_md.py` a partir de `apps/panel/openapi.json`. No se edita a mano: `make api` regenera el esquema, los tipos del panel y esta página. El test `apps/backend/tests/tools/test_openapi_md.py` falla si está desfasada.
- `apps/backend/tests/repo/` comprueba que la documentación sigue al código (por ejemplo, que cada objetivo de `make` está en `docs/referencia/comandos.md`). Si añades un objetivo, una variable o un comando, actualiza la página de referencia correspondiente.

## Sitio autocontenido

El sitio no carga nada de fuera: la fuente Geist y Mermaid van en `docs/assets/` (`fonts/`, `javascripts/mermaid.min.js`, versión fijada), y `mkdocs.yml` desactiva Google Fonts. El tema solo descarga Mermaid de internet si `window.mermaid` no existe, y aquí lo define el fichero local. Para actualizar Mermaid, sustituye ese fichero por `dist/mermaid.min.js` de la nueva versión de npm y comprueba una página con diagramas.

## Cómo se publica

El panel sirve el sitio construido bajo `/docs/`, accesible solo por el túnel SSH del panel, con la imagen del panel que construye la documentación. La decisión y los detalles están en [ADR-018](../arquitectura/adr/ADR-018-documentacion-en-el-panel.md); el acceso al panel, en [panel](../procedimientos/panel.md).

## Dónde está el código

- `mkdocs.yml`: tema, extensiones y navegación.
- `docs/assets/`: CSS (`stylesheets/extra.css`), fuentes y Mermaid.
- `Makefile`: objetivos `docs` y `docs-check`.
- `apps/backend/src/tools/docs/openapi_md.py` (`render`): generador de la referencia de la API.

## Relacionado

- [Tests](tests.md)
- [Comandos](../referencia/comandos.md)
