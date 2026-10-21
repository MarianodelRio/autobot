# FlowPilot

Plataforma de automatización para pequeños negocios: atiende a sus clientes por WhatsApp o Telegram, gestiona reservas sobre la agenda que ya usan (peluquerías) o responde consultas de horarios (autobuses) y avisa al dueño por Telegram.

Sustituye a los bots independientes `Peluqueria` y `buscaBus` por una sola plataforma para 5–15 negocios, en una VPS con Docker Compose.

**Estado:** implementación en curso; el avance está en [IMPLEMENTATION.md](IMPLEMENTATION.md).

## Cómo empezar

1. La idea del producto: [IDEA.md](IDEA.md).
2. El diseño técnico completo: [design.md](design.md).
3. El plan de implementación y su estado: [IMPLEMENTATION.md](IMPLEMENTATION.md).
4. Las reglas para trabajar en el repo: [CLAUDE.md](CLAUDE.md).

## Desarrollo local

Requisitos: [uv](https://docs.astral.sh/uv/) (instala Python 3.14 por su cuenta).

```bash
uv sync          # dependencias, incluidas las de desarrollo
make check       # ruff, mypy, import-linter y pytest (CI añade migraciones, pip-audit e imagen)
```

Con Docker Compose (`db`, `web` y `worker`, con el código montado):

```bash
cp .env.example .env   # opcional en local: sin .env se usan los valores de desarrollo
make up                # construye la imagen y levanta los servicios; web en http://127.0.0.1:8000
make shell             # shell de Django dentro de web
make down
```
