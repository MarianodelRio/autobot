"""Comprobaciones entre viajes: grupos `bus:<id>` y aviso heurístico de mismo autobús."""

from __future__ import annotations

from dataclasses import dataclass

from packs.bus.modelo import Linea, Localidad, Parada, Paso, Viaje


@dataclass
class InfoViaje:
    """Datos auxiliares de un viaje para las comprobaciones entre líneas
    (grupos `bus:` y aviso heurístico). No forma parte del modelo publicado."""

    viaje: Viaje
    ruta: str  # fichero de la línea
    etiqueta: str  # "fichero [temporada, dias, tabla], fila N"
    indices: frozenset[int]  # días del año (índices de DIAS_DEL_ANIO)
    clases: frozenset[str]  # clases de día de la tabla


def _solapan(a: InfoViaje, b: InfoViaje) -> bool:
    """True si los dos viajes pueden circular el mismo día del año: sus
    temporadas comparten alguna fecha Y sus clases de día comparten alguna."""
    return not a.indices.isdisjoint(b.indices) and not a.clases.isdisjoint(b.clases)


def _texto_hora_paso(paso: Paso) -> str:
    if paso.llegada == paso.salida:
        return paso.llegada
    return f"{paso.llegada}>{paso.salida}"


def _horas_distintas_en_comunes(
    a: Viaje, b: Viaje, codigos: list[str]
) -> list[tuple[str, Paso, Paso]]:
    """Paradas comunes de `codigos` (en orden) cuyas horas no cuadran entre los
    dos viajes: la llegada siempre, y la salida solo si la parada no es la
    última de ninguno de los dos viajes (un viaje que termina ahí no tiene
    salida que comparar)."""
    idx_a = {p.parada: i for i, p in enumerate(a.pasos)}
    idx_b = {p.parada: i for i, p in enumerate(b.pasos)}
    distintas: list[tuple[str, Paso, Paso]] = []
    for codigo in codigos:
        ia, ib = idx_a[codigo], idx_b[codigo]
        pa, pb = a.pasos[ia], b.pasos[ib]
        ultima_alguno = ia == len(a.pasos) - 1 or ib == len(b.pasos) - 1
        if pa.llegada != pb.llegada or (not ultima_alguno and pa.salida != pb.salida):
            distintas.append((codigo, pa, pb))
    return distintas


def validar_buses(
    infos: list[InfoViaje],
    paradas: dict[str, Parada],
    localidades: dict[str, Localidad],
    errores: list[str],
) -> None:
    """Grupos `bus:<id>` declarados: todo lo declarado tiene
    que cuadrar; si no, error concreto. Solo compara entre sí los miembros que
    circulan algún mismo día (el mismo `bus:` puede repartirse entre viajes
    de días distintos, p.ej. una línea lunes-jueves y viernes)."""
    grupos: dict[str, list[InfoViaje]] = {}
    for info in infos:
        if info.viaje.bus is not None:
            grupos.setdefault(info.viaje.bus, []).append(info)

    def loc_de(codigo: str) -> str | None:
        parada = paradas.get(codigo)
        return parada.localidad if parada is not None else None

    for bus_id in sorted(grupos):
        miembros = grupos[bus_id]
        if len(miembros) == 1:
            errores.append(
                f"bus:{bus_id} aparece en un solo viaje ({miembros[0].etiqueta}); "
                "¿errata en el identificador?"
            )
            continue

        sin_pareja = [
            m for m in miembros if not any(o is not m and _solapan(m, o) for o in miembros)
        ]
        if sin_pareja:
            errores.append(
                f"bus:{bus_id}: los viajes no coinciden en ningún día "
                f"({' / '.join(m.etiqueta for m in sin_pareja)})"
            )

        vistos: set[str] = set()

        # `registrar` solo se usa dentro de esta iteración, con su `vistos`.
        def registrar(mensaje: str) -> None:
            if mensaje not in vistos:  # noqa: B023
                vistos.add(mensaje)  # noqa: B023
                errores.append(mensaje)

        for i, a in enumerate(miembros):
            for b in miembros[i + 1 :]:
                if not _solapan(a, b):
                    continue
                par = f"{a.etiqueta} / {b.etiqueta}"
                if a.viaje.linea == b.viaje.linea:
                    registrar(
                        f"bus:{bus_id}: dos viajes de la misma línea "
                        f"'{a.viaje.linea}' con días solapados ({par}); "
                        "¿son dos autobuses?"
                    )
                locs_a = {loc_de(p.parada) for p in a.viaje.pasos} - {None}
                locs_b = {loc_de(p.parada) for p in b.viaje.pasos} - {None}
                comunes = locs_a & locs_b
                if len(comunes) < 2:
                    registrar(f"bus:{bus_id}: comparten menos de 2 localidades ({par})")
                    continue
                for loc in sorted(comunes):  # type: ignore[type-var]
                    seq_a = [p.parada for p in a.viaje.pasos if loc_de(p.parada) == loc]
                    seq_b = [p.parada for p in b.viaje.pasos if loc_de(p.parada) == loc]
                    if seq_a != seq_b:
                        nombre = localidades[loc].nombre if loc in localidades else loc
                        registrar(
                            f"bus:{bus_id}: paradas distintas en {nombre} "
                            f"({'+'.join(seq_a)} / {'+'.join(seq_b)}; {par})"
                        )
                codigos_comunes = [
                    p.parada for p in a.viaje.pasos if p.parada in {q.parada for q in b.viaje.pasos}
                ]
                for codigo, pa, pb in _horas_distintas_en_comunes(
                    a.viaje, b.viaje, codigos_comunes
                ):
                    registrar(
                        f"bus:{bus_id}: horas distintas en '{codigo}' "
                        f"({a.etiqueta}: {_texto_hora_paso(pa)} / "
                        f"{b.etiqueta}: {_texto_hora_paso(pb)})"
                    )


def avisos_mismo_bus(
    infos: list[InfoViaje],
    paradas: dict[str, Parada],
    lineas: dict[str, Linea],
    avisos: list[str],
) -> None:
    """Aviso heurístico: pares de viajes de líneas distintas y
    NO declarados como el mismo `bus:` que parecen el mismo autobús (2 o más
    localidades comunes en el mismo orden, días solapados y la misma hora en la
    primera parada común) pero discrepan más adelante. Solo avisa: la fusión
    del motor sigue siendo por horas idénticas. Un aviso por (línea, línea,
    primera parada común, parada discrepante), sin repetirlo por temporada."""
    codigos_de = [frozenset(p.parada for p in i.viaje.pasos) for i in infos]

    def nombre_linea(lid: str) -> str:
        linea = lineas.get(lid)
        return linea.nombre if linea is not None else lid

    def nombre_parada(codigo: str) -> str:
        parada = paradas.get(codigo)
        return parada.nombre if parada is not None else codigo

    claves: dict[tuple[str, str, str, str], dict[str, list[str]]] = {}
    cabeceras: dict[tuple[str, str, str, str], str] = {}
    for i, a in enumerate(infos):
        for j in range(i + 1, len(infos)):
            b = infos[j]
            if a.viaje.linea == b.viaje.linea:
                continue
            if a.viaje.bus is not None and a.viaje.bus == b.viaje.bus:
                continue
            comunes = codigos_de[i] & codigos_de[j]
            if len(comunes) < 2 or not _solapan(a, b):
                continue
            seq_a = [p.parada for p in a.viaje.pasos if p.parada in comunes]
            seq_b = [p.parada for p in b.viaje.pasos if p.parada in comunes]
            if seq_a != seq_b:
                continue
            locs = {paradas[c].localidad for c in seq_a if c in paradas}
            if len(locs) < 2:
                continue
            distintas = _horas_distintas_en_comunes(a.viaje, b.viaje, seq_a)
            if not distintas or distintas[0][0] == seq_a[0]:
                continue  # todo igual, o ya discrepa en la primera parada común
            primera = seq_a[0]
            codigo, pa, pb = distintas[0]
            clave = (a.viaje.linea, b.viaje.linea, primera, codigo)
            orden_a = [p.parada for p in a.viaje.pasos]
            paso_primero = a.viaje.pasos[orden_a.index(primera)]
            dias = (
                a.viaje.dias if a.viaje.dias == b.viaje.dias else f"{a.viaje.dias} / {b.viaje.dias}"
            )
            detalle = (
                f"{nombre_parada(primera)} {_texto_hora_paso(paso_primero)} en "
                f"ambas y {nombre_parada(codigo)} {_texto_hora_paso(pa)} frente a "
                f"{_texto_hora_paso(pb)}"
            )
            cabeceras[clave] = (
                f"{a.ruta}: posible mismo autobús con horas distintas: "
                f"'{nombre_linea(a.viaje.linea)}' y '{nombre_linea(b.viaje.linea)}'"
            )
            dias_previos = claves.setdefault(clave, {}).setdefault(detalle, [])
            if dias not in dias_previos:
                dias_previos.append(dias)

    for clave, detalles in claves.items():
        texto = "; ".join(f"{detalle} ({', '.join(dias)})" for detalle, dias in detalles.items())
        avisos.append(f"{cabeceras[clave]}: {texto} (no se fusionará)")
