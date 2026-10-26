# 4. Google Calendar sin acceso o con errores

**Síntoma:** el pack `salon` no muestra huecos, no crea citas o el barrido avisa de
Calendar. **Diagnóstico:** `tenant_health <slug>` en `web` muestra
`calendar_unavailable` sin distinguir causa. Verifica que el calendario está
compartido con la cuenta de servicio (el real de un negocio en `main`, o el único
calendario de un negocio de demo, usado por sus puertas). Consulta permisos y estado
de Google para separar falta de acceso de errores transitorios, sin copiar el JSON de
credenciales.

**Pasos:** el negocio vuelve a compartir el calendario con permiso para modificar
eventos si se retiró el acceso. Para 429/5xx, espera y observa el reintento normal;
no repitas manualmente una creación cuyo resultado sea ambiguo. Para un hueco recién
ocupado, el cliente debe recibir nuevas horas. Si el error persiste, pausa el canal
afectado por cambio de configuración aprobado y avisa al negocio.

**Verificación:** `tenant_health` confirma acceso. Para un negocio de demo, una
reserva de prueba por cualquiera de sus puertas aparece una sola vez en su
calendario.
