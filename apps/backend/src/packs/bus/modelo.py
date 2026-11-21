"""packs/bus/modelo.py — entidades del modelo de horarios.

Estos objetos son el resultado de cargar y validar `horarios/` con
`packs/bus/formato/`. No se construyen a mano en ningún otro sitio (salvo en
tests).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from functools import cached_property

from core.dates import MONTH_NUMBER


@dataclass(frozen=True)
class Localidad:
    id: str
    nombre: str
    alias: tuple[str, ...] = ()
    # Localidad pendiente: aldea sin hora de paso propia. `ver` es la
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
    Validado por `formato/` como el resto de `horarios/`; `calendario.py`
    solo hace lógica pura sobre este objeto ya validado."""

    vigencia_inicio: date
    vigencia_fin: date
    festivos: dict[date, str]
    inicio_clases: date
    fin_clases: date
    vacaciones: tuple[tuple[date, date], ...] = ()
    no_lectivos: tuple[date, ...] = ()
    pendientes: tuple[str, ...] = ()
    # Días (mes, día) de todos los años sin servicio en ninguna línea.
    sin_servicio_todas_las_lineas: frozenset[tuple[int, int]] = frozenset()
    # localidad (id) -> {fecha: nombre} de festivos locales.
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

    @cached_property
    def meses_no_circula(self) -> frozenset[int]:
        """Números de mes (1-12) de `no_circula`, calculados una vez. Un nombre
        que no es un mes se ignora, como siempre."""
        meses = (MONTH_NUMBER.get(str(m).strip().lower()) for m in self.no_circula)
        return frozenset(m for m in meses if m is not None)

    @property
    def titulo(self) -> str:
        """Único sitio que decide el título visible de la línea en el bot."""
        return self.nombre_corto or self.nombre


@dataclass
class Modelo:
    localidades: dict[str, Localidad]
    paradas: dict[str, Parada]
    observaciones: dict[str, Observacion]
    lineas: dict[str, Linea]
    pendientes: tuple[str, ...] = ()  # pendientes declarados en paradas.yaml
    # Pares de localidades entre las que la empresa no vende billetes, en
    # ninguno de los dos sentidos, declarados en paradas.yaml.
    no_vendibles: frozenset[frozenset[str]] = frozenset()
    # None solo si la validación no llegó a construirlo (errores);
    # `formato.validar()` siempre lo rellena si no hay errores. Los tests
    # construyen Modelo(...) a mano sin validar y dependen de este valor por defecto.
    calendario: Calendario | None = None


@dataclass
class Resultado:
    modelo: Modelo | None
    errores: list[str]
    avisos: list[str]
