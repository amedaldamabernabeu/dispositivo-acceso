"""
Prueba en consola (Windows/Linux) la API SGACCUV sin PyQt, cámara ni serial.
Misma lógica HTTP que JetsonFinal vía sgaccuv_api.

Uso (PowerShell, desde la carpeta dispositivo/):

  $env:SGACCUV_BASE_URL = "http://localhost:3001"
  $env:SGACCUV_DEVICE_TOKEN = "..."
  py probar_sgaccuv_cli.py validar 123456
  py probar_sgaccuv_cli.py entrada 123456
  py probar_sgaccuv_cli.py salida 42
"""

from __future__ import annotations

import argparse
import json
import sys

from sgaccuv_api import (
    cargar_config_sgaccuv,
    registrar_entrada_http,
    registrar_salida_http,
    validar_codigo_http,
)


def _imprimir_json(data: object) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def cmd_validar(cfg, codigo: str) -> int:
    data = validar_codigo_http(cfg, codigo)
    if data is None:
        print("Sin respuesta válida (red, HTTP != 200 o JSON inválido).")
        return 1
    _imprimir_json(data)
    return 0


def cmd_entrada(cfg, codigo: str, usar_rfid: bool) -> int:
    data = validar_codigo_http(cfg, codigo)
    if data is None:
        return 1
    _imprimir_json(data)
    if not data.get("valido"):
        print("valido=false: no se envía entrada.")
        return 2
    if data.get("tipo") != "entrada":
        print(f"tipo={data.get('tipo')!r}: no es entrada; no se llama POST entrada.")
        return 3
    tipo_tid = cfg.tipo_ingreso_rfid if usar_rfid else cfg.tipo_ingreso_teclado
    respuesta, ok = registrar_entrada_http(cfg, codigo, tipo_tid)
    if respuesta is not None:
        print(respuesta.status_code, getattr(respuesta, "text", "")[:500])
    print("entrada_ok=", ok)
    return 0 if ok else 4


def cmd_salida(cfg, registro_id: int, usar_rfid: bool) -> int:
    tipo_tid = cfg.tipo_ingreso_rfid if usar_rfid else cfg.tipo_ingreso_teclado
    respuesta, ok = registrar_salida_http(cfg, registro_id, tipo_tid)
    if respuesta is not None:
        print(respuesta.status_code, getattr(respuesta, "text", "")[:500])
    print("salida_ok=", ok)
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="CLI mínima SGACCUV (validar / entrada / salida)."
    )
    sub = parser.add_subparsers(dest="comando", required=True)

    p_val = sub.add_parser("validar", help="GET validar/:codigo")
    p_val.add_argument("codigo")

    p_ent = sub.add_parser(
        "entrada",
        help="Validar y, si tipo=entrada y valido, POST entrada",
    )
    p_ent.add_argument("codigo")
    p_ent.add_argument(
        "--rfid",
        action="store_true",
        help="Usar SGACCUV_TIPO_INGRESO_RFID en lugar de teclado",
    )

    p_sal = sub.add_parser("salida", help="PATCH :id/salida")
    p_sal.add_argument("registro_id", type=int)
    p_sal.add_argument(
        "--rfid",
        action="store_true",
        help="Usar SGACCUV_TIPO_INGRESO_RFID en lugar de teclado",
    )

    args = parser.parse_args()
    cfg = cargar_config_sgaccuv()

    if args.comando == "validar":
        return cmd_validar(cfg, args.codigo)
    if args.comando == "entrada":
        return cmd_entrada(cfg, args.codigo, usar_rfid=args.rfid)
    if args.comando == "salida":
        return cmd_salida(cfg, args.registro_id, usar_rfid=args.rfid)
    return 1


if __name__ == "__main__":
    sys.exit(main())
