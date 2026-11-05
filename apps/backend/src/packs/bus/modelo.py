"""packs/bus/modelo.py — entidades inmutables del modelo de horarios.

Estos objetos son el resultado de cargar y validar
`horarios/` con `packs/bus/formato.py`. No se construyen a mano en
ningún otro sitio.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class Localidad:
    id: str
    nombre: str
    alias: tuple[str, ...] = ()
    # Localidad pendiente (P15/P32): aldea sin hora de paso propia. `ver` es la
    # localidad en cuyo lugar se consulta; `minutos` la distancia hasta ella;
    # `aviso` la observación (viaje) opcional que relaciona viajes con la aldea.
    pendiente: str | None = None
    ver: str | None = None
    minutos: int | None = None
    aviso: str | None = None


@dataclass(frozen=True)
class Parada:
    codigo: str
    nombre: str
    localidad: str


@dataclass(frozen=True)
class Observacion:
    id: str
    letra: str | None
    tipo: str  # "condicion" | "aviso"
    ambitos: tuple[str, ...]  # subset of ("parada", "viaje", "linea")
    texto: str


@dataclass(frozen=True)
class Temporada:
    nombre: str
    rango: str  # "DD/MM - DD/MM" o "todo el año", tal como está en el fichero


@dataclass(frozen=True)
class Paso:
    parada: str  # código de parada
    llegada: str  # "HH:MM"; en una celda simple, igual que `salida`
    salida: str  # "HH:MM"
    observaciones: tuple[str, ...] = ()  # ids de observaciones de ámbito parada


@dataclass(frozen=True)
class Tabla:
    """Una tabla `horarios:` tal como está escrita en el fichero de línea:
    conserva el sentido y el orden de columnas. La vista de revisión pinta
    una tabla por `Tabla`, nunca mezcla tablas."""

    linea: str  # id de línea
    temporada: str
    dias: str
    paradas: tuple[str, ...]  # cabecera ordenada, tal cual escrita
    posicion: int  # orden de aparición en el fichero, 0-based


@dataclass(frozen=True)
class Viaje:
    linea: str  # id de línea
    temporada: str
    dias: str  # clave de días de esta tabla concreta
    tabla: Tabla
    observaciones: tuple[str, ...] = ()  # ids de observaciones de ámbito viaje
    pendientes: tuple[str, ...] = ()
    pasos: tuple[Paso, ...] = ()
    bus: str | None = None  # id de `bus:<id>`: mismo autobús declarado


@dataclass(frozen=True)
class Calendario:
    """Festivos y periodo escolar (`horarios/calendario.yaml`).
    Validado por `formato.py` como el resto de `horarios/`; `calendario.py`
    (fase 2) solo hace lógica pura sobre este objeto ya validado."""

    vigencia_inicio: date
    vigencia_fin: date
    festivos: dict[date, str]
    inicio_clases: date
    fin_clases: date
    vacaciones: tuple[tuple[date, date], ...] = ()
    no_lectivos: tuple[date, ...] = ()
    pendientes: tuple[str, ...] = ()
    # Días (mes, día) de todos los años sin servicio en ninguna línea (P03g).
    sin_servicio_todas_las_lineas: frozenset[tuple[int, int]] = frozenset()
    # localidad (id) -> {fecha: nombre} de festivos locales (P03e).
    festivos_locales: dict[str, dict[date, str]] = field(default_factory=dict)


@dataclass(frozen=True)
class Linea:
    id: str
    nombre: str
    telefono_demanda: str | None
    avisos: tuple[str, ...]
    no_circula: tuple[str, ...]
    temporadas: tuple[Temporada, ...]
    dias: dict[str, dict[str, str]] = field(default_factory=dict)  # temporada -> {clase: estado}
    pendientes: tuple[str, ...] = ()
    viajes: tuple[Viaje, ...] = ()
    tablas: tuple[Tabla, ...] = ()  # en orden de aparición en el fichero
    # Título corto para la lista de líneas del bot (WhatsApp: 24 caracteres).
    nombre_corto: str | None = None

    @property
    def titulo(self) -> str:
        """Único sitio que decide el título visible de la línea en el bot."""
        return self.nombre_corto or self.nombre
