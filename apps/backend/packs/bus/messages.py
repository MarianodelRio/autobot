"""packs/bus/messages.py — todos los textos en español que ve el cliente.
`messages.py` solo da formato: el texto de las observaciones vive en
`observaciones.yaml` del dataset.

El teléfono, el horario de oficina y los enlaces del negocio llegan en la
config del tenant (`BusConfig`)."""

from __future__ import annotations

from datetime import date

from core.dates import MONTHS_ES, weekday_es
from core.limits import MAX_TEXT
from packs.bus.config import BusConfig
from packs.bus.formato import NOMBRES_PUBLICOS_TEMPORADA
from packs.bus.loader import Horarios
from packs.bus.query import Consulta

_DIAS_ES_ABREV = ("lun", "mar", "mié", "jue", "vie", "sáb", "dom")

# Hasta cuántos días de distancia el siguiente día con salidas se cuenta sin
# aclarar que la falta de servicio es de este trayecto.
_DIAS_SIGUIENTE_CERCANO = 7

_MARCAS_NUMERO = "¹²³⁴⁵⁶⁷⁸⁹"


def nombre_dia_es(fecha: date) -> str:
    return weekday_es(fecha)


def nombre_dia_abrev_es(fecha: date) -> str:
    return _DIAS_ES_ABREV[fecha.weekday()]


def nombre_mes_es(fecha: date) -> str:
    return MONTHS_ES[fecha.month - 1]


_DIAS_OFICINA = {
    "lunes": "lunes",
    "martes": "martes",
    "miercoles": "miércoles",
    "jueves": "jueves",
    "viernes": "viernes",
    "sabado": "sábado",
    "domingo": "domingo",
}
_ORDEN_DIAS_OFICINA = tuple(_DIAS_OFICINA)
_LABORABLES = frozenset(_ORDEN_DIAS_OFICINA[:5])


def _unir(partes: list[str]) -> str:
    if len(partes) <= 1:
        return "".join(partes)
    return ", ".join(partes[:-1]) + " y " + partes[-1]


def _dias_oficina_txt(dias: tuple[str, ...]) -> str:
    """'lunes a miércoles' para 3 o más días consecutivos; 'jueves y viernes'
    para dos; lista con 'y' si no son consecutivos."""
    indices = sorted(_ORDEN_DIAS_OFICINA.index(d) for d in dias)
    tramos: list[list[int]] = []
    for i in indices:
        if tramos and i == tramos[-1][-1] + 1:
            tramos[-1].append(i)
        else:
            tramos.append([i])
    partes: list[str] = []
    for tramo in tramos:
        nombres = [_DIAS_OFICINA[_ORDEN_DIAS_OFICINA[i]] for i in tramo]
        if len(nombres) >= 3:
            partes.append(f"{nombres[0]} a {nombres[-1]}")
        else:
            partes.append(" y ".join(nombres))
    return _unir(partes)


def _horario_oficina_txt(cfg: BusConfig) -> str:
    """Texto del horario de oficina por bloques de días (solo para mostrar)."""
    bloques = []
    for bloque in cfg.office_hours:
        dias = tuple(bloque.days)
        franjas = [franja.split("-") for franja in bloque.ranges]
        laborables = " laborables" if set(dias) <= _LABORABLES else ""
        horas = " y ".join(f"de {ini} a {fin}" for ini, fin in franjas)
        bloques.append(f"{_dias_oficina_txt(dias)}{laborables} {horas}")
    return "; ".join(bloques)


def tel_y_horario(cfg: BusConfig) -> str:
    # Sin horario de oficina en la config, solo el teléfono.
    if not cfg.office_hours:
        return f"📞 {cfg.contact_phone}"
    return f"📞 {cfg.contact_phone} (horario de oficina: {_horario_oficina_txt(cfg)})"


# ── Menú / información ──────────────────────────────────────────────────


def msg_menu_footer(cfg: BusConfig) -> str:
    return f"📞 Para otras consultas, llámanos al {cfg.contact_phone}"


def msg_info(cfg: BusConfig) -> str:
    lineas = [
        "ℹ️ Información",
        "",
        f"📞 Teléfono: {cfg.contact_phone}",
    ]
    if cfg.office_hours:
        lineas.append(f"🕒 Horario de oficina: {_horario_oficina_txt(cfg)}")
    etiquetas = {
        "web": "🌐 Web",
        "compra_online": "🛒 Compra online",
        "bonos": "🎫 Bonos",
        "pdf_horarios": "📄 PDF de horarios",
    }
    for clave, etiqueta in etiquetas.items():
        valor = cfg.links.get(clave)  # type: ignore[call-overload]
        if valor:
            lineas.append(f"{etiqueta}: {valor}")
    return "\n".join(lineas)


# ── Origen / destino / búsqueda ──────────────────────────────────────────


def msg_pedir_pueblo(campo: str) -> str:
    palabra = "origen" if campo == "origen" else "destino"
    return f"Escribe el nombre del pueblo de {palabra}:"


def msg_no_conozco_ese_pueblo() -> str:
    return "No conozco ese pueblo."


def msg_sin_lineas() -> str:
    return "Ahora mismo no puedo mostrarte la lista de líneas."


def msg_demasiadas_coincidencias() -> str:
    return "Hay muchos pueblos que coinciden. Sé más concreto, por favor."


def msg_confirmar_errata(nombre: str) -> str:
    return f"¿Querías decir {nombre}?"


def msg_escribelo_de_otra_forma() -> str:
    return "Vale, escríbelo de otra forma."


def msg_destino_distinto() -> str:
    return "Elige un destino distinto."


def msg_sin_destinos_desde_origen(cfg: BusConfig, origen_nombre: str) -> str:
    return f"No hay autobuses directos desde {origen_nombre}.\n{tel_y_horario(cfg)}"


def msg_localidad_pendiente(aldea: str, ver_nombre: str, minutos: int) -> str:
    return (
        f"Algunos autobuses paran en {aldea}, a unos {minutos} minutos de "
        f"{ver_nombre}, pero aún no tenemos su hora de paso."
    )


def msg_sin_trayecto(cfg: BusConfig, origen_nombre: str, destino_nombre: str) -> str:
    return f"No hay trayecto directo de {origen_nombre} a {destino_nombre}.\n{tel_y_horario(cfg)}"


def msg_no_vendible(origen_nombre: str, destino_nombre: str) -> str:
    return (
        f"Entre {origen_nombre} y {destino_nombre} no vendemos billetes, en"
        " ninguno de los dos sentidos. Puedes elegir otro destino."
    )


# ── Fechas ─────────────────────────────────────────────────────────────


def msg_formato_fecha() -> str:
    return "📅 Escribe la fecha así: día/mes\nPor ejemplo: 25/12"


def msg_fecha_no_entendida() -> str:
    return "No he entendido la fecha. Escríbela así: día/mes, por ejemplo 25/12."


def msg_fecha_pasada() -> str:
    return "Esa fecha ya ha pasado."


def msg_elige_de_la_lista() -> str:
    return "Elige un día de la lista o pulsa 📅 Otra fecha."


def msg_fecha_pasada_con_formato() -> str:
    return f"{msg_fecha_pasada()} {msg_formato_fecha()}"


# ── Resultado ──────────────────────────────────────────────────────────


def msg_que_mas() -> str:
    """Cuerpo de los botones cuando el resultado no cabe en ellos (nuevo)."""
    return "¿Qué quieres hacer ahora?"


def msg_reintentar() -> str:
    return "Ha habido un problema. Por favor, inténtalo de nuevo."


def msg_input_no_soportado() -> str:
    return "No puedo leer audios, imágenes ni stickers. Escríbeme o usa los botones."


def _nombre_parada(horarios: Horarios, codigo: str) -> str:
    parada = horarios.modelo.paradas.get(codigo)
    return parada.nombre if parada is not None else codigo


def _cabecera_fecha(consulta: Consulta, fecha: date, horarios: Horarios) -> str:
    info = consulta.info_dia
    dia_txt = f"{nombre_dia_es(fecha).capitalize()} {fecha.day:02d}/{fecha.month:02d}"
    if info is not None and info.es_festivo:
        # el festivo general gana sobre el local si coinciden
        return f"📅 {dia_txt} · festivo ({info.nombre_festivo})"
    if consulta.festivo_local is not None:
        nombre_festivo, localidad_id = consulta.festivo_local
        localidad = horarios.modelo.localidades.get(localidad_id)
        nombre_localidad = localidad.nombre if localidad is not None else localidad_id
        return f"📅 {dia_txt} · festivo en {nombre_localidad} ({nombre_festivo})"
    # solo una temporada única con nombre público; nunca se une con " / "
    nombres_temporada = {t.nombre for _, t in consulta.temporadas}
    if len(nombres_temporada) == 1:
        publico = NOMBRES_PUBLICOS_TEMPORADA.get(next(iter(nombres_temporada)))
        if publico is not None:
            return f"📅 {dia_txt} · horario de {publico}"
    return f"📅 {dia_txt}"


def msg_resultado(
    cfg: BusConfig,
    consulta: Consulta,
    horarios: Horarios,
    origen_nombre: str,
    destino_nombre: str,
    fecha: date,
) -> str:
    """Mensaje de resultado. `consulta.estado` decide el
    contenido; nunca se deriva de si `salidas` está vacío (`sin_datos`
    también produce salidas vacías)."""
    cabecera = f"🚌 {origen_nombre} → {destino_nombre}"

    if consulta.estado == "no_vendible":
        return f"{cabecera}\n\n" + msg_no_vendible(origen_nombre, destino_nombre)

    if consulta.estado == "sin_trayecto":
        return f"{cabecera}\n\n" + msg_sin_trayecto(cfg, origen_nombre, destino_nombre)

    if consulta.estado == "sin_datos":
        return (
            f"{cabecera}\n{_cabecera_fecha(consulta, fecha, horarios)}\n\n"
            "No tengo el horario de ese día.\n"
            f"{tel_y_horario(cfg)}"
        )

    if consulta.estado == "sin_servicio" and consulta.sin_servicio_general:
        cuerpo = (
            f"{cabecera}\n{_cabecera_fecha(consulta, fecha, horarios)}\n\n"
            f"El {fecha.day:02d}/{fecha.month:02d} no hay servicio en ninguna"
            " línea.\n"
        )
        if consulta.siguiente_con_servicio is not None:
            sig = consulta.siguiente_con_servicio
            cuerpo += (
                f"El siguiente día con salidas es {nombre_dia_es(sig)}"
                f" {sig.day:02d}/{sig.month:02d}.\n"
            )
        return cuerpo + tel_y_horario(cfg)

    if consulta.estado == "sin_servicio":
        cuerpo = f"{cabecera}\n{_cabecera_fecha(consulta, fecha, horarios)}\n\n"
        if consulta.siguiente_con_servicio is not None:
            sig = consulta.siguiente_con_servicio
            if (sig - fecha).days <= _DIAS_SIGUIENTE_CERCANO:
                cuerpo += "Ese día no hay servicio. "
            else:
                cuerpo += "Ese día no hay servicio en este trayecto. "
            cuerpo += (
                f"El siguiente día con salidas es"
                f" {nombre_dia_es(sig)} {sig.day:02d}/{sig.month:02d}."
            )
        else:
            cuerpo += "No hay salidas en los próximos días.\n" + tel_y_horario(cfg)
        return cuerpo

    # con_salidas
    listadas = [s for s in consulta.salidas if not s.ya_salio]
    ya_salidas = len(consulta.salidas) - len(listadas)

    if not listadas:
        return (
            f"{cabecera}\n{_cabecera_fecha(consulta, fecha, horarios)}\n\nHoy ya no quedan salidas."
        )

    origenes = {s.parada_origen for s in listadas}
    destinos = {s.parada_destino for s in listadas}
    mismo_origen = len(origenes) == 1
    mismo_destino = len(destinos) == 1

    # notas comunes a TODAS las salidas listadas -> una línea sin número
    notas_por_salida = [list(s.notas) for s in listadas]
    todas_notas = [n for notas in notas_por_salida for n in notas]
    comunes = [
        n for n in dict.fromkeys(todas_notas) if all(n in notas for notas in notas_por_salida)
    ]

    marcas: dict[str, str] = {}
    siguiente_marca = 0

    def _marca_de(nota: str) -> str:
        nonlocal siguiente_marca
        if nota not in marcas:
            marcas[nota] = _MARCAS_NUMERO[min(siguiente_marca, len(_MARCAS_NUMERO) - 1)]
            siguiente_marca += 1
        return marcas[nota]

    lineas_salidas = []
    for s in listadas:
        if s.duracion_min >= 60:
            duracion = f"{s.duracion_min // 60}h {s.duracion_min % 60:02d}"
        else:
            duracion = f"{s.duracion_min} min"
        hora_ini = s.hora_salida.strftime("%H:%M")
        hora_fin = s.hora_llegada.strftime("%H:%M")
        fila = f"{hora_ini} → {hora_fin}  ({duracion})"
        marcas_fila = ""
        for nota in s.notas:
            if nota in comunes:
                continue
            marcas_fila += _marca_de(nota)
        if marcas_fila:
            fila += marcas_fila
        if not mismo_origen or not mismo_destino:
            origen_parada = _nombre_parada(horarios, s.parada_origen)
            destino_parada = _nombre_parada(horarios, s.parada_destino)
            fila += f"  ({origen_parada} → {destino_parada})"
        lineas_salidas.append(fila)

    partes = [cabecera, _cabecera_fecha(consulta, fecha, horarios), ""]
    partes.extend(lineas_salidas)
    partes.append("")

    if mismo_origen:
        origen_parada = _nombre_parada(horarios, listadas[0].parada_origen)
        partes.append(f"📍 Salidas desde: {origen_parada}")

    for nota, marca in marcas.items():
        partes.append(f"⚠️ {marca} {nota}")
    for nota in comunes:
        partes.append(f"⚠️ {nota}")

    if consulta.lineas_sin_datos:
        partes.append(f"⚠️ Puede haber más salidas: llama al {cfg.contact_phone}.")

    if ya_salidas:
        partes.append(f"(hoy ya han salido {ya_salidas})")

    texto = "\n".join(partes)
    if len(texto) > MAX_TEXT:
        # Trunca por la última salida completa.
        acumulado = []
        largo = 0
        cabecera_txt = "\n".join(partes[:3]) + "\n"
        largo = len(cabecera_txt)
        for fila in lineas_salidas:
            if largo + len(fila) + 1 > MAX_TEXT - 80:
                break
            acumulado.append(fila)
            largo += len(fila) + 1
        restantes = len(lineas_salidas) - len(acumulado)
        texto = (
            cabecera_txt
            + "\n".join(acumulado)
            + f"\n\n…y {restantes} salidas más, llama al {cfg.contact_phone}."
        )
    return texto
