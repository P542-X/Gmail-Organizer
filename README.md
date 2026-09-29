# Organizador automático de Gmail

Script en Python que revisa tu bandeja de entrada de Gmail y organiza el
correo nuevo automáticamente:

- Si el remitente pertenece a una lista de empresas/servicios que tú
  definas, le aplica la etiqueta correspondiente y lo deja en la bandeja.
- Si no pertenece a ninguna, pero el asunto (y opcionalmente el cuerpo)
  contiene una frase típica de aviso de seguridad ("inicio de sesión",
  "verificación en dos pasos", "código de seguridad", "2FA", "registro"…),
  lo deja tranquilo en la bandeja sin tocarlo.
- Si el correo menciona tu nombre (o cualquier otra palabra que tú
  definas — número de expediente, "matrícula", "beca", etc.), nunca se
  manda a Spam y además se marca como Importante.
- Todo lo demás se manda a Spam.

Solo actúa sobre correos **nuevos** (por defecto, de los últimos 2 días) —
nunca toca tu correo antiguo ni nada que ya tengas etiquetado a mano.

Pensado para dejarlo corriendo de forma indefinida en un servidor casero /
Mini PC / Raspberry Pi que esté siempre encendido, aunque también funciona
lanzado a mano o vía cron.

## Por qué existe

Gmail no deja crear filtros con lógica de "si NO es de esta lista de
remitentes Y no contiene estas palabras, manda a Spam" desde su propia
interfaz de filtros. Este script hace justo eso, con tu propia lista de
remitentes de confianza.

## 1. Personaliza las categorías

Abre `gmail_organizer.py` y edita `CATEGORY_DOMAINS` con las
empresas/servicios que te interesa mantener organizados en tu bandeja, y
sus dominios de correo:

```python
CATEGORY_DOMAINS = {
    "PayPal": ["paypal.com", "paypal.es"],
    "Stripe": ["stripe.com"],
    # añade aquí lo que necesites...
}
```

El matching es por dominio **o subdominio** — si añades `"uber.com"`,
también engancha automáticamente `message.uber.com`, `eng.uber.com`, etc.
No hace falta listar cada subdominio a mano, solo dominios raíz distintos
que la misma empresa use bajo otro nombre.

También puedes ajustar `SECURITY_PHRASES` (las frases que hacen que un
correo se quede en la bandeja aunque no sea de la lista) a tu idioma o
gusto.

## 2. Configura tus datos personales (opcional, recomendado)

```bash
cp config.example.py config.py
```

Edita `config.py` con tu propio nombre y cualquier palabra que quieras
proteger de ir a Spam (y marcar como Importante). `config.py` está en
`.gitignore` — nunca se sube al repositorio, así que tus datos personales
se quedan solo en tu máquina.

## 3. Conecta tu cuenta de Gmail (Google Cloud Console)

1. Entra a https://console.cloud.google.com/ con la cuenta de Gmail que
   quieres organizar.
2. Crea un proyecto nuevo.
3. Ve a **APIs y servicios → Biblioteca**, busca **Gmail API** y pulsa
   **Habilitar**.
4. Ve a **APIs y servicios → Pantalla de consentimiento de OAuth** (o
   **Google Auth Platform → Público** en la interfaz más reciente):
   - Tipo de usuario: **Externo**.
   - Añade tu propio correo en **Usuarios de prueba**. Mientras la app
     esté en modo "Prueba" solo funcionará para las cuentas que añadas
     ahí, lo cual está bien si es solo para ti.
5. Ve a **Credenciales → Crear credenciales → ID de cliente de OAuth**:
   - Tipo de aplicación: **Aplicación de escritorio**.
   - Descarga el JSON generado.
6. Renombra ese archivo a `credentials.json` y colócalo en la misma
   carpeta que `gmail_organizer.py`. `credentials.json` también está en
   `.gitignore`.

## 4. Instalar

Necesitas Python 3.9+.

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## 5. Primera ejecución (autorización)

```bash
python3 gmail_organizer.py
```

- Con entorno gráfico: se abre el navegador para iniciar sesión y aceptar
  el permiso.
- Sin entorno gráfico (solo SSH/terminal):

  ```bash
  GMAIL_ORGANIZER_HEADLESS=1 python3 gmail_organizer.py
  ```

  Te da un enlace para abrir desde cualquier otro dispositivo, iniciar
  sesión ahí, y pegar el código de vuelta en la terminal.

Tras autorizar una vez, se guarda `token.json` en la misma carpeta (ya
está en `.gitignore`) — las siguientes ejecuciones no vuelven a pedir
permiso.

## 6. Dejarlo siempre corriendo (systemd)

```bash
cp organizador-gmail.service.example organizador-gmail.service
```

Edita `organizador-gmail.service`: cambia `User=` y las rutas
(`WorkingDirectory`, `ExecStart`) para que apunten a tu usuario y a la
carpeta real donde tengas el proyecto.

```bash
sudo cp organizador-gmail.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now organizador-gmail.service
systemctl status organizador-gmail.service
journalctl -u organizador-gmail.service -f   # ver el registro en vivo
```

### Alternativa: cron

Si prefieres una revisión periódica en vez de un servicio siempre activo
(sin `GMAIL_ORGANIZER_LOOP=1`, cada llamada hace una sola pasada):

```bash
crontab -e
```

```
*/10 * * * * cd /ruta/a/gmail-organizer && venv/bin/python3 gmail_organizer.py >> log.txt 2>&1
```

## Variables de entorno

| Variable | Por defecto | Qué hace |
|---|---|---|
| `GMAIL_ORGANIZER_LOOP` | (sin definir) | `1` = corre indefinidamente en bucle (para systemd). Sin definir = una sola pasada y termina (para cron). |
| `GMAIL_ORGANIZER_INTERVAL` | `300` | Segundos entre pasadas cuando `GMAIL_ORGANIZER_LOOP=1`. |
| `GMAIL_ORGANIZER_FULL_BODY` | (sin definir) | `1` = además del asunto, escanea el cuerpo completo del correo (más fiable, algo más lento). Sin definir = solo asunto + fragmento inicial. |
| `GMAIL_ORGANIZER_HEADLESS` | (sin definir) | `1` = usa el flujo de autorización por consola en vez de abrir un navegador local (solo hace falta la primera vez). |

## Seguridad y privacidad

- El script solo pide el scope `gmail.modify` (leer, etiquetar,
  archivar, marcar como spam) — no puede enviar correos en tu nombre ni
  borrarlos definitivamente.
- Nunca borra correos ni toca etiquetas que no haya creado él mismo.
- `credentials.json`, `token.json` y `config.py` nunca se suben al
  repositorio (están en `.gitignore`); son los únicos archivos con datos
  sensibles.
- Revisa `CATEGORY_DOMAINS` y `SECURITY_PHRASES` antes de dejarlo
  corriendo: la regla de "todo lo demás va a Spam" es agresiva a
  propósito, así que la primera semana conviene echarle un ojo a la
  carpeta de Spam por si hay que añadir algún remitente nuevo.

## Licencia

MIT — ver [LICENSE](LICENSE).

## Aviso por email cuando caduca el token

Si Google revoca o deja caducar el token OAuth (`invalid_grant`), el organizador puede enviarte un correo con los pasos para renovarlo antes de detenerse. Es opcional: si no configuras estas variables, el error solo queda en el log.

| Variable | Descripción |
|---|---|
| `GMAIL_ALERT_TO` | Dirección que envía y recibe el aviso (tu cuenta de Gmail) |
| `GMAIL_APP_PASSWORD` | Contraseña de aplicación de esa cuenta (https://myaccount.google.com/apppasswords, requiere verificación en 2 pasos) |
| `GMAIL_ALERT_NAME` | Opcional. Nombre para el saludo y el asunto del correo |

Guárdalas en un fichero `.env` (ya está en `.gitignore`, no se sube al repositorio):

~~~
GMAIL_ALERT_TO=tu_correo@gmail.com
GMAIL_APP_PASSWORD=xxxxxxxxxxxxxxxx
GMAIL_ALERT_NAME=TuNombre
~~~

Protégelo con `chmod 600 .env` y cárgalo en el servicio añadiendo esta línea en la sección `[Service]` de `organizador-gmail.service`:

~~~
EnvironmentFile=/ruta/al/proyecto/.env
~~~

Después ejecuta `sudo systemctl daemon-reload && sudo systemctl restart organizador-gmail.service`.
