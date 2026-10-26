
import re


def validar_rut_chileno(rut):
    """Valida el formato y digito verificador de un RUT chileno."""

    if not isinstance(rut, str):
        return False

    rut = re.sub(r"[.\s-]", "", rut.upper())

    if not re.fullmatch(r"\d{7,9}[0-9K]", rut):
        return False

    numero = rut[:-1]
    digito_verificador = rut[-1]

    suma = 0
    multiplicador = 2

    for digito in reversed(numero):
        suma += int(digito) * multiplicador
        multiplicador += 1

        if multiplicador > 7:
            multiplicador = 2

    resultado = 11 - (suma % 11)

    if resultado == 11:
        esperado = "0"
    elif resultado == 10:
        esperado = "K"
    else:
        esperado = str(resultado)

    return digito_verificador == esperado


def validar_email_retell(email):
    """Comprueba el formato basico de un correo electronico."""

    if not isinstance(email, str):
        return False

    email = email.strip()

    if len(email) > 254 or ".." in email:
        return False

    patron = (
        r"[A-Za-z0-9][A-Za-z0-9._%+\-]*"
        r"@[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?"
        r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)+"
    )

    if not re.fullmatch(patron, email):
        return False

    return len(email.rsplit(".", 1)[-1]) >= 2


def validar_telefono_retell(telefono):
    """Valida formatos telefonicos chilenos e internacionales."""

    if not isinstance(telefono, str):
        return False

    telefono = telefono.strip()

    if not re.fullmatch(r"\+?[\d\s().-]+", telefono):
        return False

    digitos = re.sub(r"\D", "", telefono)

    if len(set(digitos)) <= 1:
        return False

    # Telefono internacional con prefijo +
    if telefono.startswith("+"):
        if digitos.startswith("56"):
            return (
                len(digitos) == 11
                and digitos[2] in "23456789"
            )

        return (
            8 <= len(digitos) <= 15
            and digitos[0] != "0"
        )

    # Telefono nacional chileno
    if len(digitos) == 9:
        return digitos[0] in "23456789"

    # Telefono chileno con 56, sin +
    if len(digitos) == 11 and digitos.startswith("56"):
        return digitos[2] in "23456789"

    return False
