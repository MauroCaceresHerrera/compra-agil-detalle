import argparse
import json
import random
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests


BASE_URL = "https://api2.mercadopublico.cl"
SHEET_NAME = "Sheet"


DEFAULT_OUTPUT_DIR = r"C:\clarita\compra_agil"
USER_AGENT = (
    "compra-agil-detalle/0.1 "
    "(consulta secuencial; contacto: Mauricio Caceres)"
)


class RateLimitError(Exception):
    def __init__(self, retry_after: int | None = None):
        super().__init__("429: Too Many Requests")
        self.retry_after = retry_after


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


def obtener_retry_after(response: requests.Response) -> int | None:
    retry_after = response.headers.get("Retry-After")

    if not retry_after:
        return None

    try:
        return max(1, int(retry_after))
    except ValueError:
        return None


def guardar_json(compra_id: str, data: dict, output_dir: Path):
    output_dir.mkdir(parents=True, exist_ok=True)

    json_path = output_dir / f"{compra_id}.json"

    with json_path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)

    log(f"JSON guardado: {json_path}")


def esperar_entre_llamadas(segundos_base: float, jitter: float):
    segundos = segundos_base + random.uniform(0, jitter)
    log(f"Esperando {segundos:.1f} segundo(s)...")
    time.sleep(segundos)


def mostrar_error_http(compra_id: str, response: requests.Response):
    log("ERROR HTTP")
    log(f"  compra_id    : {compra_id}")
    log(f"  status_code  : {response.status_code}")
    log(f"  url          : {response.url}")
    log(f"  content_type : {response.headers.get('Content-Type', 'no informado')}")

    body = response.text.strip()
    log(f"  body         : {body[:1200] if body else 'vacío'}")


def obtener_detalle(
    compra_id: str,
    token: str,
    session: requests.Session,
) -> dict:
    url = f"{BASE_URL}/v2/compra-agil/{compra_id}"

    response = session.get(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
            "ticket": token,
        },
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
            raise RateLimitError(obtener_retry_after(response))

        raise Exception(f"{response.status_code}: error HTTP no controlado")

    data = response.json()

    if data.get("success") != "OK":
        log("ERROR API NOK")
        log(f"  compra_id : {compra_id}")
        log(f"  errors    : {data.get('errors')}")
        raise Exception("La API respondió success=NOK")

    return data


def obtener_detalle_con_reintentos(
    compra_id: str,
    token: str,
    session: requests.Session,
    max_retries: int,
    backoff_base: int,
) -> dict:
    intento = 0

    while True:
        try:
            return obtener_detalle(compra_id, token, session)
        except RateLimitError as error:
            intento += 1

            if intento > max_retries:
                raise

            espera = error.retry_after or min(backoff_base * (2 ** (intento - 1)), 1800)
            espera = int(espera + random.uniform(5, 30))

            log(f"429 recibido. Pausando {espera} segundo(s) antes de reintentar.")
            log(f"Reintento {intento}/{max_retries} para compra {compra_id}.")
            time.sleep(espera)


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


def main_legacy():
    return main_resiliente()

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


def main_resiliente():
    parser = argparse.ArgumentParser(
        description="Consulta secuencial de detalle de Compras Agiles"
    )

    parser.add_argument("--token", required=True)
    parser.add_argument("--excel", required=True)
    parser.add_argument("--sleep", type=float, default=10)
    parser.add_argument("--jitter", type=float, default=3)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--max-retries", type=int, default=5)
    parser.add_argument("--backoff-base", type=int, default=300)
    parser.add_argument("--force", action="store_true")

    args = parser.parse_args()
    output_dir = Path(args.output_dir)

    log("Iniciando proceso secuencial")
    log(f"Excel: {args.excel}")
    log(f"Sleep entre llamadas: {args.sleep} segundo(s)")
    log(f"Jitter adicional: 0 a {args.jitter} segundo(s)")
    log(f"Directorio JSON: {output_dir}")
    log(f"Reintentos ante 429: {args.max_retries}")
    log("Leyendo archivo...")

    ids = leer_ids_desde_excel(args.excel)

    log(f"Compras encontradas: {len(ids)}")
    log("Comenzando llamadas a la API")
    log("-" * 70)

    exitosas = 0
    errores = 0
    rate_limits = 0
    omitidas = 0

    with requests.Session() as session:
        for index, compra_id in enumerate(ids, start=1):
            json_path = output_dir / f"{compra_id}.json"

            if json_path.exists() and not args.force:
                omitidas += 1
                log(f"[{index}/{len(ids)}] Omitida compra {compra_id}: JSON ya existe.")
                log("-" * 70)
                continue

            log(f"[{index}/{len(ids)}] Consultando compra: {compra_id}")

            try:
                data = obtener_detalle_con_reintentos(
                    compra_id=compra_id,
                    token=args.token,
                    session=session,
                    max_retries=args.max_retries,
                    backoff_base=args.backoff_base,
                )
                mostrar_resumen_ok(compra_id, data)
                guardar_json(compra_id, data, output_dir)
                exitosas += 1

            except RateLimitError as e:
                errores += 1
                rate_limits += 1
                log(f"ERROR compra {compra_id}")
                log(f"  motivo: {e}")
                log("Se agotaron los reintentos ante 429 para esta compra.")

            except Exception as e:
                errores += 1
                mensaje = str(e)

                log(f"ERROR compra {compra_id}")
                log(f"  motivo: {mensaje}")

                if "401" in mensaje or "403" in mensaje:
                    log("Deteniendo proceso: problema con el ticket.")
                    break

            log("-" * 70)

            if index < len(ids):
                esperar_entre_llamadas(args.sleep, args.jitter)

    log("Proceso terminado")
    log(f"Exitosas: {exitosas}")
    log(f"Omitidas por JSON existente: {omitidas}")
    log(f"Errores: {errores}")
    log(f"429 recibidos sin recuperacion: {rate_limits}")


if __name__ == "__main__":
    main_resiliente()
