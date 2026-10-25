# Administración interna

El sitio está en `/admin/` y el panel en `/admin/estado/`, dentro del conjunto de URL
`internal`. Requiere usuario activo con `is_staff` y verificación TOTP. El proceso web
necesita `DB_OWNER_URL`; sin el alias `owner`, responde 503. El worker no lo necesita.
La publicación por túnel y la configuración de Caddy corresponden a F7.

El alta inicial se hace en una sesión local privada de operación, nunca mediante un
formulario público. Con la base local preparada:

```sh
uv run python manage.py migrate --database owner
uv run python manage.py createsuperuser --database owner
uv run python manage.py shell
```

En la shell, sustituye `USUARIO` por el usuario creado y registra el dispositivo una
sola vez:

```python
from django.contrib.auth import get_user_model
from django_otp.plugins.otp_totp.models import TOTPDevice

operator = get_user_model().objects.using("owner").get(username="USUARIO")
device = TOTPDevice.objects.using("owner").create(
    user_id=operator.pk, name="autenticador del operador", confirmed=True
)
```

Provisiona el valor de `device.config_url` en el autenticador dentro de esa sesión
privada. Esa URL contiene la semilla TOTP: se trata como una credencial y no se imprime
en logs ni se copia a tickets. Abre `/admin/login/`, introduce usuario y contraseña,
selecciona el dispositivo y proporciona su código TOTP. No hay un acceso al Admin que
omita el segundo factor.

Para revisar un envío `unknown` de más de diez minutos, selecciona «Marcar enviado»
si has comprobado su entrega. La confirmación registra ese hecho aunque haya caducado
el payload o se haya dado de baja el negocio. «Reenviar» requiere payload, tenant y
canal disponibles y una confirmación expresa del posible duplicado. Conserva la fila
y su identidad idempotente y encola un trabajo nuevo. Ambas acciones comprueban el
estado bajo bloqueo y guardan auditoría en la misma transacción.

Los modelos de Procrastinate son de consulta. «Reintentar trabajo fallido» solo admite
trabajos registrados en estado `failed`; nunca toma trabajos `doing`. No reintenta
los envíos de mensajes o avisos: hay que revisar el resultado externo y resolver el
mensaje expresamente cuando sea `unknown`. Cada reintento permitido queda auditado.

«Estado» consulta datos en `owner`, sin fijar tenant ni llamar a servicios externos.
Muestra la salud observada por el worker, con su fecha y aviso si falta o está
obsoleta; los contadores mensuales usan la zona del tenant. Los facturables se cuentan
por fecha de envío, aunque se hubieran creado el mes anterior.
