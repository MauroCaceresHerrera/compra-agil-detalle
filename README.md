# Compra Ágil Detalle - Prueba API Mercado Público

Script mínimo en Python para consultar secuencialmente el detalle de Compras Ágiles usando la API v2 de Mercado Público.

## Objetivo

Leer un Excel con una columna `ID`, consultar cada Compra Ágil en forma secuencial y mostrar un log claro de cada llamada.

## Stack

- Python
- uv
- pandas
- requests
- openpyxl

## Instalación

```bash
uv sync
```

## Ejecución

```bash
uv run python main.py --token TU_TICKET --excel "Cotizaciones 15-junio.xlsx" --sleep 1
```

## Importante

El ticket se envía como header HTTP:

```python
headers = {"ticket": token}
```

No se envía como query parameter.

## Endpoint usado

```txt
GET https://api2.mercadopublico.cl/v2/compra-agil/{codigo}
```

## Problema observado

Al ejecutar llamadas secuenciales, la API puede responder intermitentemente:

```txt
HTTP 429 Too Many Requests
{"message":"Too Many Requests"}
```

Incluso usando `sleep` entre llamadas.

Este repositorio busca facilitar la revisión técnica del comportamiento.