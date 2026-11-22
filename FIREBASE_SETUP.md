# Configuración de Firebase para BuscatodoRD

Esta guía te muestra cómo obtener las credenciales de Firebase para las notificaciones push.

## ¿Qué es Firebase Cloud Messaging (FCM)?

Firebase Cloud Messaging es el servicio de Google para enviar notificaciones push a navegadores web, iOS y Android. Es **100% gratuito** hasta 1 millón de mensajes por mes.

---

## Paso 1: Crear un Proyecto en Firebase

1. Ve a **Firebase Console**: https://console.firebase.google.com/

2. Click en **"Agregar proyecto"** (o "Add project")

3. Completa los siguientes pasos:
   - **Nombre del proyecto**: `BuscatodoRD` (o el nombre que prefieras)
   - **Habilitar Google Analytics**: Puedes dejarlo deshabilitado (no es necesario para FCM)
   - Click en **"Crear proyecto"**

4. Espera a que se cree el proyecto (toma 30-60 segundos)

5. Click en **"Continuar"** cuando esté listo

---

## Paso 2: Obtener las Credenciales (Service Account)

### Opción Recomendada: Service Account JSON

1. En Firebase Console, con tu proyecto seleccionado, click en el **ícono de engranaje ⚙️** (arriba a la izquierda)

2. Selecciona **"Project Settings"** (Configuración del proyecto)

3. Ve a la pestaña **"Service accounts"** (Cuentas de servicio)

4. En la sección **"Firebase Admin SDK"**, verás:
   - Lenguaje seleccionado: **Python**
   - Un botón que dice **"Generate new private key"** (Generar nueva clave privada)

5. Click en **"Generate new private key"**

6. Aparecerá un diálogo de confirmación que dice:
   > "Your private key gives access to your project's Firebase services. Keep it confidential and never store it in a public repository."

7. Click en **"Generate key"** (Generar clave)

8. Se descargará automáticamente un archivo JSON con un nombre como:
   ```
   buscapieza-rd-a1b2c3d4e5f6.json
   ```

---

## Paso 3: Guardar el Archivo JSON en tu Proyecto

1. **Renombra el archivo** descargado a algo más simple:
   ```
   firebase-credentials.json
   ```

2. **Mueve el archivo** a la carpeta raíz de tu proyecto BuscatodoRD:
   ```
   C:\buscapieza\firebase-credentials.json
   ```

3. **IMPORTANTE**: Verifica que el archivo JSON esté en `.gitignore` para NO subirlo a git (ya está configurado)

---

## Paso 4: Configurar la Variable de Entorno

1. Abre tu archivo `.env` (si no existe, copia `.env.example` y renómbralo a `.env`)

2. Busca la línea de `FIREBASE_CREDENTIALS_PATH`

3. Actualízala con la **ruta completa** al archivo JSON:

   **Windows:**
   ```env
   FIREBASE_CREDENTIALS_PATH=C:\buscapieza\firebase-credentials.json
   ```

   **Linux/Mac:**
   ```env
   FIREBASE_CREDENTIALS_PATH=/home/usuario/buscapieza/firebase-credentials.json
   ```

4. Guarda el archivo `.env`

---

## Paso 5: Verificar que Funciona

1. **Instala las nuevas dependencias**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Inicia el servidor**:
   ```bash
   python app.py
   ```

3. **Verifica en los logs** que veas:
   ```
   Firebase Admin SDK inicializado correctamente
   ```

4. **Prueba las notificaciones**:
   - Ve a `/admin/configuracion`
   - Baja hasta la sección de notificaciones
   - Verás el estado de Firebase

---

## Paso 6 (OPCIONAL): Configurar el Frontend

Para que los usuarios puedan recibir notificaciones push en sus navegadores, necesitas:

### 6.1. Obtener la Configuración Web de Firebase

1. En Firebase Console, ve a **Project Settings** > **General**

2. Baja hasta **"Your apps"** (Tus aplicaciones)

3. Click en el ícono **Web** (`</>`)

4. Registra una nueva app:
   - **App nickname**: `BuscatodoRD Web`
   - **Habilitar Firebase Hosting**: NO (desmarcado)
   - Click en **"Register app"**

5. Copia la configuración que aparece (algo como esto):
   ```javascript
   const firebaseConfig = {
     apiKey: "AIzaSyXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX",
     authDomain: "buscapieza-rd.firebaseapp.com",
     projectId: "buscapieza-rd",
     storageBucket: "buscapieza-rd.appspot.com",
     messagingSenderId: "123456789012",
     appId: "1:123456789012:web:abcdef1234567890"
   };
   ```

### 6.2. Obtener el VAPID Key

1. En Firebase Console, ve a **Project Settings** > **Cloud Messaging**

2. Baja hasta **"Web Push certificates"**

3. Si no existe, click en **"Generate key pair"**

4. Copia el **"Key pair"** generado (comienza con `B...`)

### 6.3. Pegar la configuración (sin tocar código)

Ya no hace falta editar `sw.js`. Elige una de estas dos opciones:

- **Panel admin** → ⚙️ Configuración → sección Firebase: pega el `firebaseConfig`
  **como JSON** (claves entre comillas) y la clave pública VAPID.
- **.env**:
  ```env
  FIREBASE_WEB_CONFIG={"apiKey":"AIza...","authDomain":"buscapieza-rd.firebaseapp.com","projectId":"buscapieza-rd","messagingSenderId":"123456789012","appId":"1:123456789012:web:abcdef"}
  FIREBASE_VAPID_PUBLIC=BLxxxxxxxx...
  ```

Con eso, los usuarios **admin y proveedor** ven un icono 🔔 en el menú. Al pulsarlo,
el navegador pide permiso, obtiene el token FCM y lo registra en `/push-token`.
Los tokens caducados se borran solos cuando FCM los rechaza.

> Los enlaces de las notificaciones usan `APP_URL`. FCM solo acepta enlaces `https://`,
> así que en producción configura `APP_URL=https://tu-dominio`.

---

## Solución de Problemas

### Error: "FileNotFoundError"
- **Problema**: No encuentra el archivo JSON
- **Solución**: Verifica que la ruta en `.env` sea correcta y que el archivo exista

### Error: "ValueError: already exists"
- **Problema**: Firebase ya fue inicializado
- **Solución**: Reinicia el servidor Flask, el error desaparecerá

### Error: "Sender ID mismatch"
- **Problema**: El Service Worker usa una configuración diferente
- **Solución**: Verifica que el `messagingSenderId` coincida entre backend y frontend

### Las notificaciones no llegan
- **Problema**: El usuario no ha dado permisos
- **Solución**: Pide permisos de notificación desde el navegador

---

## Límites y Costos

Firebase Cloud Messaging es **GRATIS** con límites generosos:

- ✅ **1,000,000 mensajes/mes**: Sin costo
- ✅ **Usuarios ilimitados**: Sin costo
- ✅ **Sin tarjeta de crédito requerida**: Para empezar

Si excedes 1M mensajes/mes, Firebase te contactará para actualizar tu plan.

---

## Recursos Adicionales

- **Documentación oficial**: https://firebase.google.com/docs/cloud-messaging
- **Firebase Admin SDK Python**: https://firebase.google.com/docs/admin/setup
- **FCM para Web**: https://firebase.google.com/docs/cloud-messaging/js/client

---

## Seguridad

### ⚠️ NUNCA subas el archivo JSON a git

El archivo `firebase-credentials.json` contiene credenciales sensibles que dan acceso completo a tu proyecto Firebase.

**Buenas prácticas:**
- ✅ Mantén el archivo fuera de git (ya configurado en `.gitignore`)
- ✅ No lo compartas por email, WhatsApp o Discord
- ✅ Si lo subes accidentalmente, **revoca la clave** y genera una nueva
- ✅ En producción, usa variables de entorno o servicios de secrets (AWS Secrets Manager, Google Secret Manager)

---

## Soporte

Si tienes problemas con la configuración:

1. Verifica los logs de Flask en `logs/app.log`
2. Revisa que todas las rutas sean correctas
3. Asegúrate de que instalaste `firebase-admin==6.5.0`

Si el problema persiste, abre un issue en el repositorio del proyecto.
