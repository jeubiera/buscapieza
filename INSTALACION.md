# Instalación de BuscatodoRD en un servidor Windows con Cloudflare Tunnel

Guía para dejar la aplicación funcionando en un servidor Windows, publicada en tu dominio
a través de un túnel de Cloudflare (sin abrir puertos en el router ni en el firewall).

```
Internet ──https──▶ Cloudflare ──túnel──▶ cloudflared (servicio) ──▶ http://localhost:5050 ──▶ BuscatodoRD
```

---

## 1. Antes de empezar

| Necesitas | Detalle |
|---|---|
| Windows 10/11 o Windows Server 2016+ | Con una cuenta de administrador |
| **PostgreSQL 14 o superior** | https://www.postgresql.org/download/windows/ — durante la instalación **apunta la contraseña del usuario `postgres`** |
| **Tu dominio en Cloudflare** | El dominio (p. ej. `buscatodo.com.do`) tiene que estar añadido a tu cuenta de Cloudflare con sus DNS gestionados por Cloudflare |
| Python 3.12 y cloudflared | Si no están, el instalador ofrece instalarlos con `winget` |

> **Dominios `.do`:** se compran en NIC.DO. Después, en el panel de NIC.DO cambia los
> *nameservers* a los dos que te indique Cloudflare al añadir el dominio.

---

## 2. Instalar

1. Copia `BuscatodoRD-AAAAMMDD-xxxxxxx.zip` al servidor y **descomprímelo** (p. ej. en `C:\Instaladores\BuscaPieza`).
2. Doble clic en **`INSTALAR-SERVIDOR.bat`** (pedirá permisos de administrador).
3. Responde al asistente:
   - **Dominio público**: el hostname que publicará el túnel, p. ej. `buscatodo.com.do`
   - **Email y contraseña del admin**
   - **WhatsApp del broker** y nombre del negocio
   - Integraciones (Green API, Cloudinary): opcionales, se pueden poner luego en *Admin → Configuración*
   - **Contraseña de `postgres`**: la del instalador de PostgreSQL (no se guarda)
4. En el paso del túnel (8/8), si el servidor **no** tiene ya un túnel:
   1. Entra en https://one.dash.cloudflare.com → **Networks → Tunnels → Create a tunnel → Cloudflared**
   2. Nombre: `buscatodo` → en *Install and run a connector* elige **Windows**
   3. Copia el comando que aparece (`cloudflared.exe service install eyJ...`) y **pégalo en el instalador**
   4. Pulsa *Next* y en **Public Hostname** pon:
      - *Subdomain*: vacío (o `app` si usarás `app.tudominio`) · *Domain*: tu dominio
      - *Service*: **HTTP** · *URL*: **`localhost:5050`**
   5. *Save tunnel*

   Si el servidor **ya** tiene un túnel (por ejemplo, de otro sitio web), el instalador no instala otro:
   añade un *Public Hostname* nuevo a ese túnel con los datos de arriba.

Al terminar verás un resumen con la URL pública. La instalación queda en **`C:\BuscatodoRD`**
(para otra carpeta: `INSTALAR-SERVIDOR.bat -Destino D:\BuscatodoRD`).

---

## 3. Qué queda instalado

| Componente | Dónde / cómo |
|---|---|
| Aplicación | `C:\BuscatodoRD` (servidor waitress en `127.0.0.1:5050`, no accesible desde fuera salvo por el túnel) |
| Arranque automático | Tarea programada **BuscatodoRD-Servidor** (al iniciar Windows, cuenta SYSTEM). Si el proceso cae, `scripts\supervisor.py` lo relanza |
| Túnel | Servicio de Windows **cloudflared** |
| Base de datos | PostgreSQL, base y usuario `buscatodo` (contraseña aleatoria guardada en `.env`) |
| Configuración | `C:\BuscatodoRD\.env` (solo legible por Administradores y SYSTEM) |
| Respaldos | Tarea **BuscatodoRD-Respaldo**, diaria a las 02:30 → `C:\BuscatodoRD\backups` (se guardan 14 días) |
| Logs | `C:\BuscatodoRD\logs` (`app.log`, `errors.log`, `servidor-consola.log`, `supervisor.log`) |

Comprobar el estado: abre `http://127.0.0.1:5050/salud` en el servidor o `https://tudominio/salud` desde fuera
→ debe responder `{"db": true, "ok": true}`.

---

## 4. Tareas habituales

**Reiniciar la aplicación**
```powershell
Stop-ScheduledTask BuscatodoRD-Servidor; Start-ScheduledTask BuscatodoRD-Servidor
```
(o reinicia el servidor: arranca sola)

**Actualizar a una versión nueva**
1. Descomprime el paquete nuevo en una carpeta **distinta** de `C:\BuscatodoRD`
2. Doble clic en **`ACTUALIZAR.bat`**

Hace un respaldo de la base, copia el código, instala dependencias, aplica migraciones y vuelve a arrancar.
Conserva `.env`, base de datos, logs, respaldos y fotos.

**Olvidé la contraseña del admin**
```powershell
cd C:\BuscatodoRD
venv\Scripts\python -m flask --app "app:create_app" admin-password
```

**Respaldo manual / restaurar**
```powershell
cd C:\BuscatodoRD
venv\Scripts\python scripts\respaldar_db.py
# Restaurar (detén antes la app):
& "C:\Program Files\PostgreSQL\18\bin\pg_restore.exe" -h localhost -U buscatodo -d buscatodo --clean --if-exists backups\buscatodo_AAAAMMDD_HHMM.dump
```
La contraseña del usuario `buscatodo` está en `DATABASE_URL` dentro del `.env`.
Copia periódicamente la carpeta `backups` **fuera del servidor** (otro disco, nube).

**Credenciales de Firebase (push)**: guarda el JSON en `C:\BuscatodoRD\secrets\` y pon en *Admin → Configuración*
la ruta `secrets\firebase-credentials.json`. (Esa carpeta no se toca al actualizar.)

**Desinstalar** (quita las tareas; conserva archivos y base de datos)
```powershell
powershell -ExecutionPolicy Bypass -File C:\BuscatodoRD\instalador\desinstalar.ps1
```

---

## 5. Cobros en línea (opcional)

En **Admin → Configuración → Pagos en línea**:

| Forma de pago | Qué necesitas |
|---|---|
| **Transferencia** | Escribe los datos de tu cuenta. El cliente transfiere, sube la foto o PDF del comprobante y tú lo apruebas en **Admin → Pagos**. |
| **Tarjeta con Azul** | Afiliación de comercio con Azul: *MerchantId*, nombre del comercio y *AuthKey*. Prueba primero con el ambiente **Pruebas**. |
| **Tarjeta con CardNet** | Afiliación con CardNet: *MerchantNumber*, *MerchantTerminal*, *AcquiringInstitutionCode* y *MerchantType*. Valida en el **laboratorio** antes de pasar a Producción. |

- Las pasarelas vuelven a `APP_URL` (`https://tu-dominio/pagos/...`): debe ser la URL pública con **https**.
- **ITBIS**: por defecto 0 %. Cámbialo solo cuando tu contador lo confirme (en una venta se calcula sobre
  la comisión de BuscatodoRD; en un destacado, sobre el precio del plan). El recibo **no** es un comprobante fiscal (NCF).
- **Destacados**: los planes (días y precio) se editan en **Admin → Planes de destacado**.

---

## 6. Programa de referidos (opcional)

En **Admin → Referidos** (viene **desactivado**):

- Cada usuario tiene su enlace en **Mi red** (icono 👥) para compartir por WhatsApp. Quien se registra con
  ese enlace queda en su red.
- Cuando alguien de la red **paga una compra**, se generan comisiones para los niveles de arriba
  (porcentajes configurables; por defecto sobre la comisión de BuscatodoRD en esa venta).
- **Cierre mensual**: el día 1 pulsa *Cerrar periodo* (o prográmalo con
  `venv\Scripts\python -m flask --app app:create_app cerrar-referidos`). Quien llegó a la meta del mes cobra;
  lo demás se acumula los meses configurados y después vence.
- En *Por pagar* registras cada pago a los referidos; el usuario recibe un aviso por WhatsApp.
- Consulta con tu contador las retenciones aplicables a estos pagos.

---

## 7. Problemas frecuentes

| Síntoma | Qué revisar |
|---|---|
| El instalador dice que la app no responde | `C:\BuscatodoRD\logs\servidor-consola.log` y `errors.log`. Suele ser la conexión a PostgreSQL (`DATABASE_URL`) |
| `https://tudominio` da error 1033 / 502 | El servicio **cloudflared** no está en ejecución (`services.msc`) o el Public Hostname no apunta a `HTTP localhost:5050` |
| Error 404 de Cloudflare con un túnel ya existente | En su `config.yml`, la regla de BuscatodoRD debe ir **antes** de `service: http_status:404` |
| No se puede iniciar sesión | Entra siempre por `https://tudominio` (las cookies de sesión son solo HTTPS) |
| Los enlaces de WhatsApp apuntan a otro sitio | `APP_URL` en `.env` o en *Admin → Configuración* |
