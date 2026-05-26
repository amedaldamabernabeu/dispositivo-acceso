"""
Cliente HTTP compartido para SGACCUV (NestJS registro-acceso).
Usado por JetsonFinal.py en el dispositivo y por probar_sgaccuv_cli.py en Windows.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import requests


def env_str(name: str, default: str) -> str:
    v = os.environ.get(name)
    return default if v is None else str(v).strip()


def env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class ConfigSgaccuv:
    """Parámetros de integración leídos de SGACCUV_* (mismos defaults que JetsonFinal)."""

    base_url: str
    device_token: str
    tipo_ingreso_rfid: int
    tipo_ingreso_teclado: int
    dispositivo_id: int


def cargar_config_sgaccuv() -> ConfigSgaccuv:
    return ConfigSgaccuv(
        base_url=env_str("SGACCUV_BASE_URL", "http://api-accesocuvalles.dokploy.devspartans.com").rstrip("/"),
        device_token=env_str(
            "SGACCUV_DEVICE_TOKEN",
            "5cb4e4801b10204db46ff28f5e46aade5211a81cc68299e50e915a8f6cb61221",
        ),
        tipo_ingreso_rfid=env_int("SGACCUV_TIPO_INGRESO_RFID", 2),
        tipo_ingreso_teclado=env_int("SGACCUV_TIPO_INGRESO_TECLADO", 5),
        dispositivo_id=env_int("SGACCUV_DISPOSITIVO_ID", 13),
    )


def cabeceras_bearer(device_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {device_token}"}


def respuesta_registro_exitosa(payload: object) -> bool:
    """POST entrada / PATCH salida: éxito solo si el JSON trae success === true."""
    return isinstance(payload, dict) and payload.get("success") is True


def validar_codigo_http(
    cfg: ConfigSgaccuv, codigo: str, timeout: float = 15
) -> dict[str, Any] | None:
    """GET /registro-acceso/validar/{codigo}. Devuelve dict JSON o None si error HTTP/red."""
    if not cfg.device_token.strip():
        print("SGACCUV: DEVICE_TOKEN vacío")
        return None
    url = f"{cfg.base_url}/registro-acceso/validar/{quote(str(codigo), safe='')}"
    try:
        respuesta = requests.get(
            url, headers=cabeceras_bearer(cfg.device_token), timeout=timeout
        )
        print(respuesta.status_code, url)
        if respuesta.status_code != 200:
            return None
        try:
            return respuesta.json()
        except ValueError:
            print("SGACCUV: respuesta no es JSON")
            return None
    except requests.exceptions.RequestException as e:
        print(f"Error al realizar la solicitud: {e}")
        return None


def registrar_entrada_http(
    cfg: ConfigSgaccuv,
    codigo_usuario: str,
    tipo_ingreso_entrada_id: int,
    timeout: float = 15,
) -> tuple[requests.Response | None, bool]:
    """POST /registro-acceso/entrada. Devuelve (respuesta, ok)."""
    url = f"{cfg.base_url}/registro-acceso/entrada"
    respuesta: requests.Response | None = None
    try:
        respuesta = requests.post(
            url,
            json={
                "codigoUsuario": str(codigo_usuario),
                "tipoIngresoEntradaId": tipo_ingreso_entrada_id,
                "dispositivoId": cfg.dispositivo_id,
            },
            headers=cabeceras_bearer(cfg.device_token),
            timeout=timeout,
        )
        payload = respuesta.json() if respuesta.content else {}
        ok = respuesta_registro_exitosa(payload)
        return respuesta, ok
    except (requests.exceptions.RequestException, ValueError) as e:
        print("Error entrada SGACCUV:", e)
        return respuesta, False


def registrar_salida_http(
    cfg: ConfigSgaccuv,
    registro_id: int,
    tipo_ingreso_salida_id: int,
    timeout: float = 15,
) -> tuple[requests.Response | None, bool]:
    """PATCH /registro-acceso/:id/salida. Devuelve (respuesta, ok)."""
    url = f"{cfg.base_url}/registro-acceso/{int(registro_id)}/salida"
    respuesta: requests.Response | None = None
    try:
        respuesta = requests.patch(
            url,
            json={"tipoIngresoSalidaId": tipo_ingreso_salida_id},
            headers=cabeceras_bearer(cfg.device_token),
            timeout=timeout,
        )
        payload = respuesta.json() if respuesta.content else {}
        ok = respuesta_registro_exitosa(payload)
        return respuesta, ok
    except (requests.exceptions.RequestException, ValueError, TypeError) as e:
        print("Error salida SGACCUV:", e)
        return respuesta, False
