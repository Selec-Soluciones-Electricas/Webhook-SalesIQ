from flask import Blueprint, abort, request, send_file

from services.excel_quote_service import generar_quote_xlsx

excel_bp = Blueprint("excel", __name__)

MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@excel_bp.post("/excel/quote")
def excel_quote():
    data = request.get_json(force=True) or {}
    try:
        buf = generar_quote_xlsx(data.get("fecha", ""), data.get("filas", []))
    except ValueError:
        abort(400, "fecha debe venir en formato dd-MM-yyyy")

    return send_file(
        buf,
        mimetype=MIME_XLSX,
        as_attachment=True,
        download_name=data.get("nombre_archivo", "Quote.xlsx"),
    )