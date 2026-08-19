#!/usr/bin/env python3
"""
Organizador automático de Gmail para PayPal, Uber, Revolut, BBVA, PlayStation,
Skrill, Stripe, Binance, Epic Games, Crunchyroll, Google Seguridad y Steam.

Qué hace en cada ejecución:
  1. Busca correos NUEVOS en la bandeja de entrada (de los últimos 2 días,
     y que el script todavía no haya tocado).
  2. Si el remitente pertenece a uno de los 12 servicios de la lista,
     le aplica la etiqueta correspondiente y lo deja en la bandeja.
  3. Si NO pertenece a esos 12 pero el asunto o el cuerpo contiene alguna
     de las frases de seguridad (inicio de sesión, verificación en dos
     pasos, código de seguridad / 2FA, registro), lo deja tranquilo en
     la bandeja de entrada (no se toca).
  4. Si no es ninguno de los dos casos anteriores, lo manda a Spam.
  5. Marca el correo con la etiqueta interna "Auto-organizado" para no
     volver a procesarlo en la siguiente ejecución.

Pensado para lanzarse cada X minutos vía cron en un Mini PC.
"""

import base64
import os
import re
import sys
import time
import unicodedata
from email.utils import parseaddr

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# ---------------------------------------------------------------------------
# CONFIGURACIÓN
# ---------------------------------------------------------------------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CREDENTIALS_FILE = os.path.join(BASE_DIR, "credentials.json")
TOKEN_FILE = os.path.join(BASE_DIR, "token.json")

# Necesitamos poder leer, etiquetar, archivar y marcar como spam.
SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]

# Solo miramos correos de los últimos N días en cada pasada, para no tocar
# jamás el historial antiguo aunque el script lleve tiempo sin ejecutarse.
LOOKBACK_DAYS = 2

# Etiqueta interna que usa el script para saber qué correos ya procesó.
# (Sin espacios a propósito: el operador de búsqueda "label:" de Gmail no
# funciona de forma fiable con nombres de etiqueta que llevan espacios).
MARKER_LABEL = "Auto-organizado"

# Remitente (dominio) -> nombre de etiqueta en Gmail.
#
# Ojo: el matching es por "dominio o subdominio de". Por ejemplo
# "uber.com" en la lista de Uber también engancha "message.uber.com",
# "eng.uber.com", etc. automáticamente, sin tener que listar cada
# subdominio a mano. Lo que SÍ hay que añadir a mano son dominios raíz
# distintos que la misma empresa use bajo otro nombre (p. ej. BBVA usando
# tanto bbva.com como grupobbva.com). Estos son los dominios raíz
# conocidos/públicos de cada empresa; si te llega un correo legítimo desde
# uno que no está aquí, dímelo y lo añado.
CATEGORY_DOMAINS = {
    "PayPal": ["paypal.com", "paypal.es", "paypalobjects.com"],
    "Uber": ["uber.com"],
    "Revolut": ["revolut.com"],
    "BBVA": ["bbva.com", "bbva.es", "comunica.bbva.com", "grupobbva.com"],
    "PlayStation": ["playstation.com", "playstationnetwork.com"],
    "Skrill": ["skrill.com"],
    "Stripe": ["stripe.com"],
    "Binance": ["binance.com"],
    "Epic Games": ["epicgames.com", "unrealengine.com"],
    "Crunchyroll": ["crunchyroll.com"],
    "Steam": ["steampowered.com", "steamcommunity.com"],
}

# Google manda sus avisos de cuenta/seguridad desde varias direcciones que
# NO son accounts.google.com (p. ej. no-reply@google.com,
# noreply-accounts@google.com). Para no etiquetar como "Google Seguridad"
# también el marketing normal de Google (Search Console, Gemini, etc.),
# cualquier remitente de este dominio "genérico" solo cuenta como
# Google Seguridad si además el asunto/cuerpo contiene alguna frase de
# seguridad (las mismas SECURITY_PHRASES de más abajo, más un par
# específicas de Google).
GOOGLE_GENERIC_DOMAIN = "google.com"
GOOGLE_SECURITY_DOMAIN = "accounts.google.com"

# Frases que, si aparecen en el asunto o el cuerpo, hacen que el correo se
# quede en la bandeja de entrada aunque no sea de uno de los 12 servicios
# (y que, si además viene de un dominio de Google, lo etiquetan como
# "Google Seguridad" en vez de dejarlo sin etiqueta).
SECURITY_PHRASES = [
    "inicio de sesion",
    "iniciar sesion",
    "verificacion en dos pasos",
    "verificacion en 2 pasos",
    "codigo de seguridad",
    "codigo de verificacion",
    "alerta de seguridad",
    "actividad inusual",
    "nuevo dispositivo",
    "restablecer tu contrasena",
    "2fa",
    "registro",
]

GOOGLE_SECURITY_HINTS = SECURITY_PHRASES + [
    "cuenta de google",
    "se ha recuperado correctamente",
]

# Si el asunto (y, según SCAN_FULL_BODY más abajo, también el cuerpo) del
# correo menciona tu nombre o alguno de estos términos, el correo NUNCA se
# manda a Spam (pase lo que pase con las reglas de arriba) y además se
# marca como Importante en Gmail. Personalízalo con tu propio nombre y lo
# que quieras proteger (número de expediente, "matrícula", "beca", etc.).
# Estos valores son solo un ejemplo — cópialos a config.py (ver
# config.example.py) para no tener que tocar este archivo ni subir tus
# datos personales al repositorio.
PERSONAL_KEEP_PHRASES = [
    # "tu nombre",
    # "tu nombre y apellidos",
    # "matricula",
    # "beca",
]

# Por defecto solo se mira el asunto y el fragmento inicial del correo
# (más rápido, y evita falsos positivos por palabras sueltas en el pie de
# página). Si prefieres que también escanee el cuerpo completo del
# mensaje (más fiable para detectar tu nombre/frases de seguridad si
# aparecen más abajo, pero un poco más lento), pon
# GMAIL_ORGANIZER_FULL_BODY=1 como variable de entorno.
SCAN_FULL_BODY = os.environ.get("GMAIL_ORGANIZER_FULL_BODY") == "1"

try:
    from config import PERSONAL_KEEP_PHRASES  # noqa: F811  (config.py es opcional y no se sube a git)
except ImportError:
    pass

# ---------------------------------------------------------------------------
# UTILIDADES
# ---------------------------------------------------------------------------


def strip_accents(text):
    """Quita acentos para poder comparar frases sin depender de tildes."""
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if not unicodedata.combining(c))


def normalize(text):
    return strip_accents(text or "").lower()


def get_domain(from_header):
    _, addr = parseaddr(from_header or "")
    if "@" not in addr:
        return ""
    return addr.rsplit("@", 1)[-1].lower()


HTML_TAG_RE = re.compile(r"<[^>]+>")


def strip_html(html):
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    text = HTML_TAG_RE.sub(" ", text)
    return text


def decode_body_data(data):
    if not data:
        return ""
    try:
        return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode(
            "utf-8", errors="ignore"
        )
    except Exception:
        return ""


def extract_full_text(payload, max_chars=20000):
    """Recorre el payload (puede ser multipart anidado) y junta todo el
    texto legible del correo: primero las partes text/plain, y si no hay
    ninguna, cae en text/html quitando las etiquetas."""
    if payload is None:
        return ""

    plain_chunks = []
    html_chunks = []

    def walk(part):
        mime = part.get("mimeType", "")
        body = part.get("body", {})
        data = body.get("data")

        if mime == "text/plain" and data:
            plain_chunks.append(decode_body_data(data))
        elif mime == "text/html" and data:
            html_chunks.append(decode_body_data(data))

        for sub_part in part.get("parts", []) or []:
            walk(sub_part)

    walk(payload)

    text = "\n".join(plain_chunks).strip()
    if not text:
        text = strip_html("\n".join(html_chunks)).strip()

    return text[:max_chars]


def domain_matches(domain, base):
    """True si `domain` es exactamente `base` o un subdominio suyo
    (p. ej. "message.uber.com" cuenta como "uber.com")."""
    return domain == base or domain.endswith("." + base)


def matches_category(domain, normalized_text):
    if domain_matches(domain, GOOGLE_SECURITY_DOMAIN):
        return "Google Seguridad"
    if domain_matches(domain, GOOGLE_GENERIC_DOMAIN) and any(
        hint in normalized_text for hint in GOOGLE_SECURITY_HINTS
    ):
        return "Google Seguridad"

    for label_name, domains in CATEGORY_DOMAINS.items():
        if any(domain_matches(domain, base) for base in domains):
            return label_name
    return None


def contains_security_phrase(normalized_text):
    return any(phrase in normalized_text for phrase in SECURITY_PHRASES)


def contains_personal_keep_phrase(normalized_text):
    return any(phrase in normalized_text for phrase in PERSONAL_KEEP_PHRASES)


def get_header(headers, name):
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


# ---------------------------------------------------------------------------
# AUTENTICACIÓN
# ---------------------------------------------------------------------------


def get_service():
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(CREDENTIALS_FILE):
                sys.exit(
                    f"No encuentro {CREDENTIALS_FILE}. "
                    "Sigue las instrucciones del README para descargarlo "
                    "desde Google Cloud Console."
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                CREDENTIALS_FILE, SCOPES
            )
            # Si el Mini PC no tiene navegador (SSH sin entorno gráfico),
            # usa run_console() en lugar de run_local_server().
            if os.environ.get("GMAIL_ORGANIZER_HEADLESS") == "1":
                creds = flow.run_console()
            else:
                creds = flow.run_local_server(port=0)

        with open(TOKEN_FILE, "w") as token:
            token.write(creds.to_json())

    return build("gmail", "v1", credentials=creds)


# ---------------------------------------------------------------------------
# ETIQUETAS
# ---------------------------------------------------------------------------


def ensure_labels(service):
    """Devuelve {nombre_etiqueta: labelId}, creando las que falten."""
    existing = {}
    resp = service.users().labels().list(userId="me").execute()
    for lbl in resp.get("labels", []):
        existing[lbl["name"]] = lbl["id"]

    needed = list(CATEGORY_DOMAINS.keys()) + ["Google Seguridad", MARKER_LABEL]
    for name in needed:
        if name not in existing:
            created = (
                service.users()
                .labels()
                .create(userId="me", body={"name": name})
                .execute()
            )
            existing[name] = created["id"]
            print(f"Creada etiqueta que faltaba: {name}")

    return existing


# ---------------------------------------------------------------------------
# PROCESO PRINCIPAL
# ---------------------------------------------------------------------------


def list_new_messages(service):
    query = f"in:inbox -label:{MARKER_LABEL} newer_than:{LOOKBACK_DAYS}d"
    message_ids = []
    page_token = None
    while True:
        resp = (
            service.users()
            .messages()
            .list(userId="me", q=query, pageToken=page_token, maxResults=100)
            .execute()
        )
        message_ids.extend(m["id"] for m in resp.get("messages", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return message_ids


def process_message(service, msg_id, label_ids):
    if SCAN_FULL_BODY:
        # Trae el mensaje completo para poder leer también el cuerpo (no
        # solo el asunto y el fragmento inicial).
        msg = (
            service.users()
            .messages()
            .get(userId="me", id=msg_id, format="full")
            .execute()
        )
        payload = msg.get("payload", {})
        body_text = extract_full_text(payload)
    else:
        msg = (
            service.users()
            .messages()
            .get(userId="me", id=msg_id, format="metadata",
                 metadataHeaders=["From", "Subject"])
            .execute()
        )
        payload = msg.get("payload", {})
        body_text = ""

    headers = payload.get("headers", [])
    from_header = get_header(headers, "From")
    subject = get_header(headers, "Subject")
    snippet = msg.get("snippet", "")

    domain = get_domain(from_header)
    normalized_text = normalize(f"{subject} {snippet} {body_text}")
    category = matches_category(domain, normalized_text)
    is_personal = contains_personal_keep_phrase(normalized_text)

    add_labels = [label_ids[MARKER_LABEL]]
    remove_labels = []
    action_parts = []

    # Esto manda por encima de todo lo demás: si aparece tu nombre o
    # matrícula/beca, nunca se manda a Spam y siempre se marca Importante.
    if is_personal:
        add_labels.append("IMPORTANT")
        action_parts.append("marcado como importante (nombre/matrícula/beca detectado)")

    if category:
        add_labels.append(label_ids[category])
        action_parts.append(f"etiquetado como {category}")
    elif is_personal:
        pass  # ya cubierto arriba; no se manda a spam ni se deja sin marcar
    elif contains_security_phrase(normalized_text):
        action_parts.append("dejado en la bandeja (frase de seguridad detectada)")
    else:
        add_labels.append("SPAM")
        remove_labels.append("INBOX")
        action_parts.append("marcado como spam")

    action = "; ".join(action_parts)

    service.users().messages().modify(
        userId="me",
        id=msg_id,
        body={"addLabelIds": add_labels, "removeLabelIds": remove_labels},
    ).execute()

    print(f"  {msg_id} de {domain or from_header!r} ({subject[:60]!r}) -> {action}")


# Cada cuántos segundos se repite la revisión cuando el script se deja
# corriendo de forma continua (ver run_forever). Se puede cambiar sin tocar
# el código exportando la variable de entorno GMAIL_ORGANIZER_INTERVAL.
DEFAULT_INTERVAL_SECONDS = 300  # 5 minutos


def timestamp():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def run_once(service, label_ids):
    message_ids = list_new_messages(service)
    print(f"[{timestamp()}] Correos nuevos por revisar: {len(message_ids)}")

    for msg_id in message_ids:
        for attempt in range(3):
            try:
                process_message(service, msg_id, label_ids)
                break
            except HttpError as e:
                if e.resp.status in (429, 500, 503) and attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
                print(f"  ERROR con {msg_id}: {e}")
                break

    print(f"[{timestamp()}] Pasada terminada.")


def run_forever():
    interval = int(os.environ.get("GMAIL_ORGANIZER_INTERVAL", DEFAULT_INTERVAL_SECONDS))
    service = get_service()
    label_ids = ensure_labels(service)

    print(f"[{timestamp()}] Organizador arrancado. Revisando cada {interval}s.")
    while True:
        try:
            run_once(service, label_ids)
        except Exception as e:
            # Un fallo puntual (red, token caducado un instante, etc.) no debe
            # tumbar el servicio: lo registramos y lo intentamos otra vez en
            # la siguiente pasada.
            print(f"[{timestamp()}] ERROR en la pasada: {e}")
        time.sleep(interval)


def main():
    # Modo clásico: una sola pasada y termina (útil para cron o para probar
    # a mano). Si se ejecuta como servicio (ver systemd más abajo), se usa
    # run_forever() para que se quede corriendo indefinidamente.
    if os.environ.get("GMAIL_ORGANIZER_LOOP") == "1":
        run_forever()
        return

    service = get_service()
    label_ids = ensure_labels(service)
    run_once(service, label_ids)


if __name__ == "__main__":
    main()
