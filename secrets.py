# ===================== ZOHO CREDENTIALS =====================
# Credenciales de Zoho CRM (desde variables de entorno)
ZOHO_CLIENT_ID = None  # Set from environment: os.environ.get("ZOHO_CLIENT_ID")
ZOHO_CLIENT_SECRET = None  # Set from environment: os.environ.get("ZOHO_CLIENT_SECRET")
ZOHO_REFRESH_TOKEN = None  # Set from environment: os.environ.get("ZOHO_REFRESH_TOKEN")

# ===================== USUARIOS (OWNERS) =====================
# IDs de los ejecutivos/propietarios de deals
OWNERS_POSIBLES = [
    {
        "nombre": "Alexander Leiva",
        "id": "4358923000065728001",
        "email": "alexander@selec.cl"
    },
]

# ===================== SENDER USER INFO =====================
# Usuario que envía los correos
SENDER_USER_ID = "4358923000014266001"
SENDER_USER_EMAIL = "elian@selec.cl"
SENDER_USER_NAME = "Elian Barra"

# ===================== CC EMAILS =====================
# Correos que se incluyen en copia
CC_GERENCIA_EMAIL = "gerencia@selec.cl"
CC_Elian_EMAIL = "elian@selec.cl"

# ===================== ZOHO CRM =====================
# Identificadores de Zoho CRM
CRM_ORG_UI = "org706345205"

# URLs base de Zoho
CRM_BASE = "https://www.zohoapis.com/crm/v2.1"
ACCOUNTS_BASE = "https://accounts.zoho.com"
