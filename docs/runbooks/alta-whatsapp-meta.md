# Cómo se monta el canal WhatsApp de un negocio (explicación no técnica)

Esta guía explica, en lenguaje sencillo, cómo se relacionan las cuentas de Meta de
cada negocio con la persona operadora, qué tiene que hacer cada parte, y cómo
cambiaría esto si la persona operadora se da de alta como autónoma o empresa en el
futuro. Complementa el checklist técnico de `alta-baja-negocio.md`; esta guía es la
que se usa para explicárselo a un negocio que no tiene ni idea de Meta ni de
desarrollo.

## 1. El modelo actual: una "casita" de Meta por negocio

Cada negocio tiene su propia carpeta en Meta, completamente separada de las demás.
La persona operadora no es propietaria de nada de eso: solo tiene permiso para
entrar y trabajar dentro, con su propia cuenta.

```
Negocio A                                  Negocio B
  Business Portfolio del negocio             Business Portfolio del negocio
       └── App del negocio                        └── App del negocio
              └── WABA del negocio                       └── WABA del negocio
  Operador: rol de administrador             Operador: rol de administrador
  (con su propia cuenta de Facebook)         (con su propia cuenta de Facebook)
```

- **Business Portfolio**: una carpeta/oficina virtual de Meta donde viven los datos
  del negocio (su número, su nombre visible, etc.). Se crea gratis, en minutos, sin
  tener que estar de alta como empresa.
- **App**: la pieza técnica dentro de esa carpeta que permite enviar y recibir
  mensajes de WhatsApp.
- **WABA**: la cuenta de WhatsApp Business del negocio (el número, las plantillas de
  mensaje, etc.), dentro de esa misma App.

La app, la WABA y el número están siempre en el Business Portfolio del **negocio**,
nunca en uno de la persona operadora. Una app y un número por negocio (ver el
checklist técnico en `alta-baja-negocio.md`).

## 2. Qué tiene que hacer el negocio (una vez, al darlo de alta)

1. Tener (o crear) una **cuenta de Facebook** propia del negocio. No hace falta que
   sea el perfil personal de nadie: puede ser una cuenta nueva solo para esto.
2. Crear su **Business Portfolio** (gratis, sin papeleo, sin verificación de
   empresa en este punto).
3. Crear su **App** dentro de esa carpeta y añadir el producto WhatsApp: esto le da
   automáticamente un número de pruebas para empezar.
4. **Dar acceso a la persona operadora**: dentro de la carpeta (Configuración del
   negocio → Personas) y dentro de la App (Roles), añadir el email de la persona
   operadora con permiso de administrador/desarrollador.

A partir de aquí, el negocio no vuelve a tocar nada de Meta. Solo hace falta estar
con él (en persona o por videollamada) para este alta inicial; el resto lo hace la
persona operadora en remoto.

## 3. Cómo trabaja la persona operadora

- **Acceso remoto, sin volver a ver al negocio.** Una vez tiene el rol de
  administrador en la carpeta y la App del negocio, entra con su propia cuenta
  personal de Facebook a business.facebook.com y developers.facebook.com y gestiona
  todo desde ahí, en cualquier momento, sin que el negocio tenga que estar presente
  ni conectado. Solo hace falta volver a coordinarse con el negocio si hay que
  cambiar algo que exige su identidad (por ejemplo, la verificación de empresa de
  ese negocio, si algún día la necesita para subir de límite de mensajería).
- **Datos que se guardan por negocio:** de cada App se sacan tres datos (el id del
  número, el id de la cuenta de WhatsApp, y un token de acceso) y se guardan en la
  configuración de ese tenant (secretos en `secrets.yaml` del servidor, nunca en
  claro ni en git). Cada negocio tiene su propio conjunto, completamente aislado de
  los demás — igual que ya aísla sus datos de cliente con `tenant_id` y RLS.
- **Plantillas de mensaje:** las crea la persona operadora directamente en la App
  del negocio, con su acceso de administrador. El negocio no tiene que crear ni
  aprobar nada en Meta, aunque conviene que apruebe el **texto** antes de mandarlo a
  revisión, porque habla en su nombre.
- **No hace falta estar dado de alta como autónomo ni empresa** para montar esto.
  Solo se necesita cuando se quiere pasar al modelo centralizado del punto 4.

## 4. Modelo futuro: si la persona operadora se da de alta

Si más adelante la persona operadora se registra como autónoma o empresa, puede
pasar a un modelo centralizado: una sola carpeta (Business Portfolio) propia, y los
negocios simplemente "comparten" su número con ella en vez de darle un rol de
administrador dentro de su propia carpeta.

### Qué necesita la persona operadora en ese momento

1. **Darse de alta** (trámite fiscal, decisión suya, no técnica).
2. **Verificación de negocio** ante Meta: enseñar un documento (certificado de
   autónomo o de empresa) que demuestre que el negocio existe.
3. **Revisión de la App** (App Review): explicar por escrito y con un vídeo cómo se
   va a usar el acceso a los números de los negocios.
4. Con eso aprobado, su App central queda habilitada para que cualquier negocio
   pueda compartirle su número sin tener que darle acceso de administrador a toda
   su carpeta.

### Qué necesita el negocio en ese modelo

Mucho menos que antes: solo entra en la configuración de su WhatsApp, pulsa
"Compartir con un socio", pone el identificador de la carpeta central, y listo.

## 5. Cómo se migra de un modelo al otro

No hace falta mover nada ni se pierde nada. El número, el historial, las plantillas
ya aprobadas y la reputación del número se quedan donde están. Lo único que cambia
es que se **añade un acceso nuevo** por encima del que ya había:

1. Se comparte el mismo WABA también con la carpeta central nueva (Configuración de
   WhatsApp → Socios → añadir el id de la carpeta central).
2. A partir de ahí, la App central también puede gestionar ese número, sin tocar el
   acceso anterior.
3. Se puede hacer negocio por negocio, sin prisa, con los dos accesos convivendo el
   tiempo que haga falta durante la transición.

Lo único "costoso" de este cambio es el trámite de alta y verificación (el
papeleo), no el trabajo técnico de mover cosas de un sitio a otro.

## 6. Resumen

| | Modelo actual (sin alta) | Modelo centralizado (con alta) |
|---|---|---|
| Quién es dueño de la App/WABA | El negocio | El negocio (no cambia) |
| Cómo accede la persona operadora | Rol de administrador en la carpeta del negocio | Acceso compartido desde su propia carpeta |
| Qué hace el negocio al compartir | Darle un rol de administrador | Un clic de "compartir con socio" |
| Requiere alta/verificación | No | Sí, de la persona operadora |
| Visitas presenciales necesarias | Solo la primera vez (alta inicial) | Solo la primera vez (alta inicial) |
| Pérdida de datos al pasar de uno a otro | — | Ninguna |
