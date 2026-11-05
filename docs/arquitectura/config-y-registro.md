# Config y registro: notas de implementación

Detalle de implementación de la decisión de [ADR-009](../adr/ADR-009-config-en-bd.md)
(config y datasets de los negocios en PostgreSQL, versionados). Este documento no fija
decisiones de arquitectura por sí mismo; corrige o amplía según cambie el código.

## Formato de directorio

`source_from_dir` acepta `document.yaml` o el nombre antiguo `tenant.yaml`; el nombre
de la carpeta no condiciona el slug del documento, de modo que una plantilla en
`template/` o un export a un directorio temporal conserva la identidad del negocio.
El registro recibe `TenantSource` y materializa sus datasets en un directorio temporal
solo durante `Pack.load_data`, sin cambiar el contrato del pack. Las rutas absolutas,
con `..` o con contenido que no sea texto degradan únicamente al negocio afectado.
Los errores de lectura se asocian a la fuente; un fallo de secretos desactiva el canal
principal sin degradar el negocio.

## Carga y fijado del registro

La fuente de BD lee revisión, documentos, datasets y secretos con cuatro consultas,
sin una consulta por negocio. Fuera de una transacción existente usa una instantánea
`REPEATABLE READ READ ONLY`; los secretos se descifran después de cerrar la lectura.
La caché por proceso comprueba la revisión como máximo cada dos segundos bajo un
candado; solo publica la nueva instantánea cuando termina de construirla. Un fallo
de BD conserva la anterior, salvo en la primera carga, que propaga el error.

`registry_scope` fija de forma perezosa el primer registro leído durante una petición
o trabajo, incluidos ámbitos anidados. Así `/health` puede capturar también el fallo
de primera carga y devolver 503. `loaded_registry` sirve a la redacción de logs sin
consultas y conserva los secretos de la instantánea fijada durante cada trabajo.

Los webhooks principales responden también 503 si falla la primera carga de config:
el proveedor conserva el evento para reintentarlo, igual que si falla su persistencia.

## Escrituras y activación

`tenancy.store` serializa cada escritura con `SELECT FOR UPDATE` de la revisión y
valida un registro candidato antes de crear versiones, actualizar el espejo, incrementar
la revisión y auditar en la misma transacción `owner`. Las versiones anteriores no se
modifican. Los conflictos de versión y los cambios de los seis campos protegidos se
rechazan; volver atrás crea otra versión y mantiene esos campos vigentes. Los errores
contienen rutas y tipos de validación, sin reproducir los valores recibidos.

Las altas pueden adoptar un espejo sin versiones; `bus` copia el dataset de su plantilla
si no se proporcionan otros. La importación con el mismo hash no crea versiones ni
auditorías. Los secretos se sustituyen completos y solo sus nombres de campo se auditan.

La lista de activación fuerza la salud fuera de la transacción de escritura, consulta
la actividad con RLS y separa los bloqueos del aviso de dueño sin enlazar. Dentro de la
transacción se vuelve a comprobar el estado. Los demos también pueden quedar
`offboarded` mediante la baja por terminal, de acuerdo con los cinco niveles de salud
que centraliza `ops.status.tenant_status` (`ok`, `notice`, `warning`, `critical`,
`unknown`) para todas las vistas.
