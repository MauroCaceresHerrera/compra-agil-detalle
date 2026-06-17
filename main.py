import argparse
import time
from datetime import datetime

import pandas as pd
import requests


BASE_URL = "https://api2.mercadopublico.cl"
SHEET_NAME = "Compras Ágiles"


def log(message: str):
    now = datetime.now().strftime("%H:%M:%S")
    print(f"[{now}] {message}", flush=True)


def leer_ids_desde_excel(excel_path: str) -> list[str]:
    df = pd.read_excel(excel_path, sheet_name=SHEET_NAME)

    if "ID" not in df.columns:
        raise Exception("El Excel no tiene una columna llamada 'ID'")

    return (
        df["ID"]
        .dropna()
        .astype(str)
        .str.strip()
        .drop_duplicates()
        .tolist()
    )


def mostrar_headers_rate_limit(response: requests.Response):
    log("Headers rate limit")
    log(f"  x_ratelimit_limit     : {response.headers.get('X-RateLimit-Limit', 'no informado')}")
    log(f"  x_ratelimit_remaining : {response.headers.get('X-RateLimit-Remaining', 'no informado')}")
    log(f"  retry_after           : {response.headers.get('Retry-After', 'no informado')}")


def mostrar_error_http(compra_id: str, response: requests.Response):
    log("ERROR HTTP")
    log(f"  compra_id    : {compra_id}")
    log(f"  status_code  : {response.status_code}")
    log(f"  url          : {response.url}")
    log(f"  content_type : {response.headers.get('Content-Type', 'no informado')}")

    body = response.text.strip()
    log(f"  body         : {body[:1200] if body else 'vacío'}")


def obtener_detalle(compra_id: str, token: str) -> dict:
    url = f"{BASE_URL}/v2/compra-agil/{compra_id}"

    response = requests.get(
        url,
        headers={"ticket": token},
        timeout=30,
    )

    mostrar_headers_rate_limit(response)

    if response.status_code != 200:
        mostrar_error_http(compra_id, response)

        if response.status_code == 401:
            raise Exception("401: falta ticket o ticket inválido")

        if response.status_code == 403:
            raise Exception("403: ticket bloqueado, inactivo o sin permisos")

        if response.status_code == 404:
            raise Exception("404: compra no encontrada")

        if response.status_code == 429:
            raise Exception("429: Too Many Requests")

        raise Exception(f"{response.status_code}: error HTTP no controlado")

    data = response.json()

    if data.get("success") != "OK":
        log("ERROR API NOK")
        log(f"  compra_id : {compra_id}")
        log(f"  errors    : {data.get('errors')}")
        raise Exception("La API respondió success=NOK")

    return data


def mostrar_resumen_ok(compra_id: str, data: dict):
    payload = data.get("payload") or {}

    nombre = payload.get("nombre", "sin nombre")
    estado = (payload.get("estado") or {}).get("glosa", "sin estado")
    institucion = (payload.get("institucion") or {}).get(
        "organismo_comprador",
        "sin institución",
    )

    productos = len(payload.get("productos_solicitados") or [])
    proveedores = len(payload.get("proveedores_cotizando") or [])

    orden_compra = payload.get("orden_compra") or {}
    id_orden_compra = orden_compra.get("id_orden_compra")

    log(f"OK compra {compra_id}")
    log(f"  nombre          : {nombre}")
    log(f"  estado          : {estado}")
    log(f"  institución     : {institucion}")
    log(f"  productos       : {productos}")
    log(f"  proveedores     : {proveedores}")
    log(f"  id_orden_compra : {id_orden_compra}")


def main():
    parser = argparse.ArgumentParser(
        description="Consulta secuencial de detalle de Compras Ágiles"
    )

    parser.add_argument("--token", required=True)
    parser.add_argument("--excel", required=True)
    parser.add_argument("--sleep", type=float, default=1)

    args = parser.parse_args()

    log("Iniciando proceso secuencial")
    log(f"Excel: {args.excel}")
    log(f"Sleep entre llamadas: {args.sleep} segundo(s)")
    log("Leyendo archivo...")

    ids = leer_ids_desde_excel(args.excel)

    log(f"Compras encontradas: {len(ids)}")
    log("Comenzando llamadas a la API")
    log("-" * 70)

    exitosas = 0
    errores = 0
    rate_limits = 0

    for index, compra_id in enumerate(ids, start=1):
        log(f"[{index}/{len(ids)}] Consultando compra: {compra_id}")

        try:
            data = obtener_detalle(compra_id, args.token)
            mostrar_resumen_ok(compra_id, data)
            exitosas += 1

        except Exception as e:
            errores += 1
            mensaje = str(e)

            log(f"ERROR compra {compra_id}")
            log(f"  motivo: {mensaje}")

            if "401" in mensaje or "403" in mensaje:
                log("Deteniendo proceso: problema con el ticket.")
                break

            if "429" in mensaje:
                rate_limits += 1
                log("429 recibido: la API limitó esta llamada.")
                log("No se detiene el proceso. Se continúa con la siguiente compra.")

        log("-" * 70)

        if index < len(ids):
            log(f"Esperando {args.sleep} segundo(s)...")
            time.sleep(args.sleep)

    log("Proceso terminado")
    log(f"Exitosas: {exitosas}")
    log(f"Errores: {errores}")
    log(f"429 recibidos: {rate_limits}")


if __name__ == "__main__":
    main()
