import re


def extraer_email(s: str):
    m = re.search(r"[\w\.-]+@[\w\.-]+\.\w+", s or "")
    return m.group(0).strip() if m else None