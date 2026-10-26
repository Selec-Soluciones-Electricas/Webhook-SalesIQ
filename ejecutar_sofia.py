
import argparse
import os
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

from services.retell_procesador import (
    procesar_pendientes_sofia,
)


def main():
    # Permitir seleccionar un periodo opcional.
    parser = argparse.ArgumentParser(
        description="Procesador independiente de Sofia"
    )

    parser.add_argument(
        "--dias",
        type=int,
        default=None,
        help="Cantidad de dias UTC a recuperar (1 a 30)",
    )

    args = parser.parse_args()

    if args.dias is not None:
        if not 1 <= args.dias <= 30:
            print(
                "[SOFIA] ERROR: --dias debe estar "
                "entre 1 y 30"
            )
            return 1

    # Cargar configuracion local.
    ruta_env = Path(__file__).resolve().parent / ".env"
    load_dotenv(dotenv_path=ruta_env)

    agent_id = (
        os.getenv("RETELL_SOFIA_AGENT_ID") or ""
    ).strip()

    if not agent_id:
        print("[SOFIA] ERROR: Agent ID no configurado")
        return 1

    if not os.getenv("RETELL_API_KEY"):
        print("[SOFIA] ERROR: Retell API Key ausente")
        return 1

    inicio_ms = None
    fin_ms = None

    print("\n=== PROCESADOR INDEPENDIENTE DE SOFIA ===")
    print("Modo: SIMULACION")
    print("Escrituras Zoho: NO PERMITIDAS")

    # La recuperacion habitual se mantiene
    # cuando no se indica --dias.
    if args.dias is None:
        print("Recuperacion: HISTORIAL HABITUAL")

    else:
        # Trabajar con dias completos en UTC.
        hoy_utc = datetime.now(timezone.utc).date()

        primer_dia = (
            hoy_utc - timedelta(days=args.dias - 1)
        )

        dia_siguiente = (
            hoy_utc + timedelta(days=1)
        )

        inicio = datetime.combine(
            primer_dia,
            time.min,
            tzinfo=timezone.utc,
        )

        fin = datetime.combine(
            dia_siguiente,
            time.min,
            tzinfo=timezone.utc,
        )

        inicio_ms = int(inicio.timestamp() * 1000)
        fin_ms = int(fin.timestamp() * 1000)

        print("Recuperacion: POR PERIODOS")
        print("Dias solicitados:", args.dias)
        print("Inicio UTC:", inicio.date())
        print("Fin del rango UTC:", fin.date())

    try:
        resultado = procesar_pendientes_sofia(
            agent_id,
            max_paginas=5,
            limite_llamadas=10,
            simulacion=True,
            inicio_ms=inicio_ms,
            fin_ms=fin_ms,
        )

    except Exception as error:
        print(
            "[SOFIA] ERROR:",
            type(error).__name__,
        )
        return 1

    print("\n=== RESULTADO ===")
    print("Estado:", resultado.get("estado"))

    print(
        "Llamadas revisadas:",
        resultado.get("llamadas_revisadas", 0),
    )

    print(
        "Historial completo:",
        resultado.get("historial_completo", False),
    )

    print(
        "Cotizaciones candidatas:",
        resultado.get("candidatas", 0),
    )

    print(
        "Cotizaciones seleccionadas:",
        resultado.get("seleccionadas", 0),
    )

    print(
        "Llamadas en revision:",
        resultado.get(
            "total_revisiones_detectadas", 0
        ),
    )

    print(
        "Resumen:",
        resultado.get("resumen_registros", {}),
    )

    if (
        resultado.get("estado") != "simulacion"
        or resultado.get("historial_completo") is not True
    ):
        print("\n[SOFIA] Ejecucion no completada")
        return 1

    print(
        "\n[SOFIA] Simulacion completada correctamente"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
