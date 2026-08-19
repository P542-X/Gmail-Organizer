# Copia este archivo a config.py (mismo directorio) y edítalo con tus
# propios datos. config.py NO se sube a git (está en .gitignore) —
# aquí es donde vive tu información personal, separada del código.
#
#   cp config.example.py config.py
#
# Si no creas config.py, el script simplemente no protege ningún nombre
# de correo en particular (PERSONAL_KEEP_PHRASES se queda vacío) — sigue
# funcionando igual con las 12 categorías de empresas.

PERSONAL_KEEP_PHRASES = [
    "tu nombre",
    "tu nombre y tus apellidos",
    "matricula",
    "beca",
    # añade lo que quieras: número de expediente, el nombre de tu empresa...
]
