# FlowPilot — Idea

## ¿Qué problema resuelve?

Los pequeños negocios (peluquerías, empresas de autobuses…) pierden horas cada semana contestando WhatsApps, gestionando reservas a mano y copiando datos entre herramientas que no se hablan entre sí.

FlowPilot automatiza esas tareas repetitivas: atiende a los clientes por WhatsApp, gestiona reservas y avisa al dueño cuando hace falta.

## ¿Quién lo usa?

- **Dueños de pequeños negocios** (1–15 empleados) y **su clientela**, que escribe por el canal del negocio: WhatsApp o Telegram.
- **El desarrollador** (Mariano), como operador de la plataforma: da de alta negocios, configura packs y vigila que todo funcione.

## ¿Cómo funciona a alto nivel?

1. Llega algo que hay que atender: un mensaje de WhatsApp ("quiero cita el sábado por la mañana"), un correo, un Excel o un calendario que cambia. Son las fuentes de la automatización.
2. FlowPilot entiende la petición, consulta o actualiza sus datos (Google Calendar, hojas de cálculo, etc.), responde al cliente si hace falta y deja registro de lo ocurrido.
3. El dueño recibe avisos por Telegram (nueva cita, cancelación, algo que requiere su atención).
4. Otro ejemplo, sin reservas: el operador carga los horarios de una empresa de autobuses y el bot responde a quien pregunta por un trayecto.
5. Esto son solo casos concretos: puede haber automatizaciones a distintos niveles y para distintos usos

## ¿Hay algo técnico que ya quieres?

- **Lenguaje y framework:** Python + Django.
- **Base de datos:** PostgreSQL.
- **Colas de trabajo:** en Postgres, con Procrastinate.
- **Infraestructura:** una VPS en la UE con Docker Compose (Caddy, web, worker y PostgreSQL), como máximo unos 20 €/mes para 5–15 negocios.
- **Canales:** un canal por negocio (WhatsApp o Telegram) y un bot de Telegram compartido para probar cualquier negocio.
- **Aislamiento:** los datos de cada negocio están separados del resto (tenant) y la base de datos lo refuerza con RLS.

## ¿Qué NO es parte de esto?

- **No es un chatbot de IA de propósito general.** La primera versión no usa IA: las respuestas son deterministas. Si algún día se añade, solo responderá preguntas sobre el negocio y no decidirá nada.
- **No es un software de reservas que compita con Booksy.** FlowPilot se conecta a la agenda que el negocio ya usa.
- **No es un CRM.**
- **No incluye facturación propia.**
- **No usa SMS como canal principal.**
