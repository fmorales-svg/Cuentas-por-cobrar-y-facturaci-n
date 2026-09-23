#!/usr/bin/env python3
"""
Revisa facturas.json y, si hay facturas vencidas (más de PLAZO_DIAS desde la
emision y no pagadas), envia un correo de aviso via SMTP.

Pensado para correr desde GitHub Actions cada lunes (ver
.github/workflows/aviso-cobranza.yml). No requiere librerias externas.
"""

import json
import os
import re
import smtplib
import sys
from datetime import datetime, date
from email.mime.text import MIMEText

PLAZO_DIAS = int(os.environ.get("PLAZO_DIAS", "30"))
FACTURAS_PATH = os.environ.get("FACTURAS_PATH", "facturas.json")
DASHBOARD_URL = os.environ.get("DASHBOARD_URL", "")

def clean_env(name, default=None):
    """Reads an env var and strips ANY control/whitespace-like character
    wherever it sits in the value (start, middle, or end) — not just
    plain \\r\\n, but also stray tabs, non-breaking spaces, zero-width
    characters, etc. that a copy-paste from Word/Notes/WhatsApp can leave
    behind. GitHub secrets pasted that way are a common cause of
    'folded header contains newline' when building the email — this
    makes that whole class of typo harmless."""
    value = os.environ.get(name, default)
    if not isinstance(value, str):
        return value
    # Drop ASCII control chars (incl. \r, \n, \t) and common invisible
    # unicode whitespace (NBSP, zero-width space/joiner, BOM), then trim.
    value = re.sub(r"[\x00-\x1f\x7f ​‌‍﻿]", "", value)
    return value.strip()


SMTP_HOST = clean_env("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(clean_env("SMTP_PORT", "587"))
SMTP_USER = clean_env("SMTP_USER")
SMTP_PASS = clean_env("SMTP_PASS")
EMAIL_TO = clean_env("EMAIL_TO", SMTP_USER)


def parse_date(value):
    # Acepta "YYYY-MM-DD", ISO con hora, o "DD-MM-YYYY".
    value = value.strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(value[:19] if "T" in value else value, fmt).date()
        except ValueError:
            continue
    raise ValueError("Formato de fecha no reconocido: %r" % value)


def fmt_clp(n):
    return "$" + format(round(n), ",").replace(",", ".")


def main():
    if not SMTP_USER or not SMTP_PASS:
        print("Faltan SMTP_USER / SMTP_PASS (configura los secrets del repo).", file=sys.stderr)
        sys.exit(1)

    print("Diagnostico (sin mostrar valores reales): "
          "SMTP_USER largo=%d, EMAIL_TO largo=%d" % (len(SMTP_USER), len(EMAIL_TO)))

    with open(FACTURAS_PATH, "r", encoding="utf-8") as fh:
        facturas = json.load(fh)

    hoy = date.today()
    vencidas = []
    for f in facturas:
        if f.get("pagada"):
            continue
        try:
            emision = parse_date(str(f.get("emision", "")))
        except ValueError:
            continue
        dias_transcurridos = (hoy - emision).days
        if dias_transcurridos > PLAZO_DIAS:
            f = dict(f)
            f["diasVencida"] = dias_transcurridos - PLAZO_DIAS
            vencidas.append(f)

    if not vencidas:
        print("Sin facturas vencidas (> %d dias desde emision). No se envia correo." % PLAZO_DIAS)
        return

    vencidas.sort(key=lambda f: -f["diasVencida"])
    total_vencido = sum(f.get("total", 0) for f in vencidas)

    filas = "\n".join(
        "  - Folio {folio} · {razon} · {rut} · {total} · vencida hace {dias} dia(s)".format(
            folio=f.get("folio"),
            razon=f.get("razonSocial", ""),
            rut=f.get("rut", ""),
            total=fmt_clp(f.get("total", 0)),
            dias=f["diasVencida"],
        )
        for f in vencidas
    )

    cuerpo = (
        "Aviso semanal de cobranza - {fecha}\n\n"
        "Hay {n} factura(s) vencida(s) (más de {plazo} días desde su emisión y sin pago),\n"
        "por un total de {total}:\n\n"
        "{filas}\n\n"
        "{link}"
    ).format(
        fecha=hoy.strftime("%d-%m-%Y"),
        n=len(vencidas),
        plazo=PLAZO_DIAS,
        total=fmt_clp(total_vencido),
        filas=filas,
        link=("Dashboard: " + DASHBOARD_URL) if DASHBOARD_URL else "",
    )

    msg = MIMEText(cuerpo, "plain", "utf-8")
    msg["Subject"] = "Cobranza DMZ: {n} factura(s) vencida(s) ({total})".format(
        n=len(vencidas), total=fmt_clp(total_vencido)
    )
    msg["From"] = SMTP_USER
    msg["To"] = EMAIL_TO

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(SMTP_USER, [EMAIL_TO], msg.as_string())

    print("Correo enviado a %s con %d factura(s) vencida(s)." % (EMAIL_TO, len(vencidas)))


if __name__ == "__main__":
    main()
