import sys
from dotenv import load_dotenv

load_dotenv()
from agente.nucleo import responder  # después de cargar .env

canal = sys.argv[1] if len(sys.argv) > 1 else "whatsapp"
historial = []
print(f"Probando canal: {canal}. Escribe 'salir' para terminar.\n")

while True:
    contexto = {"registros": {}}  # igual que la sesión del webhook

    mensaje = input("Cliente: ").strip()
    if mensaje.lower() in ("salir", ""):
        break
    historial.append({"role": "user", "content": mensaje})
    texto, acciones = responder(historial, canal)
    for a in acciones:
        print(f"  [acción] {a['herramienta']} → {a['resultado']}")
    print(f"Sofía: {texto}\n")
    historial.append({"role": "assistant", "content": texto})