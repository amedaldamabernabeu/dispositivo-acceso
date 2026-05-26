"""
Simulación de carga / estrés contra la API de dispositivos SGACCUV.
Lee .docs/prueba_dispositivo.md, ejecuta validar → entrada/salida de forma aleatoria
entre 3 torniquetes y genera un reporte HTML autocontenido.

No modifica backend ni frontend. Reutiliza la misma API que sgaccuv_api.py.

Uso (PowerShell, desde dispositivo/):

  py -m pip install -r requirements-cli.txt
  py simular_carga_dispositivo.py
  py simular_carga_dispositivo.py --iteraciones 200 --concurrencia 8
  py simular_carga_dispositivo.py --abrir-reporte
"""

from __future__ import annotations

import argparse
import html
import json
import random
import statistics
import sys
import time
import webbrowser
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests

from cargar_prueba_dispositivo import (
    DatosPruebaDispositivo,
    DispositivoPrueba,
    cargar_prueba_dispositivo,
)
from sgaccuv_api import cabeceras_bearer, env_str, respuesta_registro_exitosa


@dataclass
class ResultadoOperacion:
    indice: int
    codigo: str
    grupo: str
    dispositivo: str
    dispositivo_id: int
    tipo_ingreso_id: int
    tipo_ingreso_nombre: str
    operacion: str
    http_status: int | None
    latencia_ms: float
    exito: bool
    detalle: str
    valido: bool | None = None
    tipo_flujo: str | None = None
    registro_id: int | None = None
    motivo: str | None = None
    error_red: str | None = None


@dataclass
class ResumenSimulacion:
    inicio_utc: str
    fin_utc: str
    duracion_seg: float
    base_url: str
    iteraciones: int
    concurrencia: int
    semilla: int
    archivo_datos: str
    resultados: list[ResultadoOperacion] = field(default_factory=list)
    preflight: list[dict[str, Any]] = field(default_factory=list)


def _ahora_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _latencia_ms(inicio: float) -> float:
    return round((time.perf_counter() - inicio) * 1000, 2)


def _validar_silencioso(
    base_url: str, token: str, codigo: str, timeout: float
) -> tuple[int | None, dict[str, Any] | None, float, str | None]:
    inicio = time.perf_counter()
    url = f"{base_url.rstrip('/')}/registro-acceso/validar/{quote(str(codigo), safe='')}"
    try:
        resp = requests.get(
            url, headers=cabeceras_bearer(token), timeout=timeout
        )
        ms = _latencia_ms(inicio)
        try:
            data = resp.json() if resp.content else {}
        except ValueError:
            return resp.status_code, None, ms, "JSON inválido en validar"
        return resp.status_code, data, ms, None
    except requests.exceptions.RequestException as e:
        return None, None, _latencia_ms(inicio), str(e)


def _entrada_silenciosa(
    base_url: str,
    token: str,
    dispositivo_id: int,
    codigo: str,
    tipo_id: int,
    timeout: float,
) -> tuple[int | None, dict[str, Any] | None, float, str | None]:
    inicio = time.perf_counter()
    url = f"{base_url.rstrip('/')}/registro-acceso/entrada"
    try:
        resp = requests.post(
            url,
            json={
                "codigoUsuario": str(codigo),
                "tipoIngresoEntradaId": tipo_id,
                "dispositivoId": dispositivo_id,
            },
            headers=cabeceras_bearer(token),
            timeout=timeout,
        )
        ms = _latencia_ms(inicio)
        try:
            data = resp.json() if resp.content else {}
        except ValueError:
            return resp.status_code, None, ms, "JSON inválido en entrada"
        return resp.status_code, data, ms, None
    except requests.exceptions.RequestException as e:
        return None, None, _latencia_ms(inicio), str(e)


def _salida_silenciosa(
    base_url: str,
    token: str,
    registro_id: int,
    tipo_id: int,
    timeout: float,
) -> tuple[int | None, dict[str, Any] | None, float, str | None]:
    inicio = time.perf_counter()
    url = f"{base_url.rstrip('/')}/registro-acceso/{int(registro_id)}/salida"
    try:
        resp = requests.patch(
            url,
            json={"tipoIngresoSalidaId": tipo_id},
            headers=cabeceras_bearer(token),
            timeout=timeout,
        )
        ms = _latencia_ms(inicio)
        try:
            data = resp.json() if resp.content else {}
        except ValueError:
            return resp.status_code, None, ms, "JSON inválido en salida"
        return resp.status_code, data, ms, None
    except requests.exceptions.RequestException as e:
        return None, None, _latencia_ms(inicio), str(e)


def _preflight_dispositivo(
    base_url: str, disp: DispositivoPrueba, timeout: float
) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}/registro-acceso/dispositivo/validar"
    try:
        resp = requests.get(
            url, headers=cabeceras_bearer(disp.token), timeout=timeout
        )
        cuerpo: Any = None
        try:
            cuerpo = resp.json() if resp.content else {}
        except ValueError:
            cuerpo = {"error": "JSON inválido"}
        return {
            "dispositivo": disp.nombre,
            "dispositivo_id_esperado": disp.dispositivo_id,
            "http_status": resp.status_code,
            "ok": resp.status_code == 200,
            "respuesta": cuerpo,
        }
    except requests.exceptions.RequestException as e:
        return {
            "dispositivo": disp.nombre,
            "dispositivo_id_esperado": disp.dispositivo_id,
            "http_status": None,
            "ok": False,
            "respuesta": {"error": str(e)},
        }


def _ejecutar_lectura(
    indice: int,
    codigo: str,
    grupo: str,
    disp: DispositivoPrueba,
    base_url: str,
    timeout: float,
    rng: random.Random,
) -> list[ResultadoOperacion]:
    tipo_id = rng.choice(disp.tipos.ids())
    tipo_nombre = disp.tipos.nombre_por_id(tipo_id)
    filas: list[ResultadoOperacion] = []

    status, data, ms, err = _validar_silencioso(base_url, disp.token, codigo, timeout)
    valido = data.get("valido") if data else None
    tipo_flujo = data.get("tipo") if data else None
    registro_id = data.get("registroId") if data else None
    motivo = data.get("motivo") if data else None

    filas.append(
        ResultadoOperacion(
            indice=indice,
            codigo=codigo,
            grupo=grupo,
            dispositivo=disp.nombre,
            dispositivo_id=disp.dispositivo_id,
            tipo_ingreso_id=tipo_id,
            tipo_ingreso_nombre=tipo_nombre,
            operacion="validar",
            http_status=status,
            latencia_ms=ms,
            exito=status == 200 and data is not None,
            detalle=json.dumps(data, ensure_ascii=False)[:500] if data else (err or ""),
            valido=valido if isinstance(valido, bool) else None,
            tipo_flujo=str(tipo_flujo) if tipo_flujo is not None else None,
            registro_id=int(registro_id) if registro_id is not None else None,
            motivo=str(motivo) if motivo is not None else None,
            error_red=err,
        )
    )

    if err or data is None or not valido:
        return filas

    if tipo_flujo == "entrada":
        st2, d2, ms2, err2 = _entrada_silenciosa(
            base_url, disp.token, disp.dispositivo_id, codigo, tipo_id, timeout
        )
        ok = respuesta_registro_exitosa(d2)
        filas.append(
            ResultadoOperacion(
                indice=indice,
                codigo=codigo,
                grupo=grupo,
                dispositivo=disp.nombre,
                dispositivo_id=disp.dispositivo_id,
                tipo_ingreso_id=tipo_id,
                tipo_ingreso_nombre=tipo_nombre,
                operacion="entrada",
                http_status=st2,
                latencia_ms=ms2,
                exito=ok,
                detalle=json.dumps(d2, ensure_ascii=False)[:500] if d2 else (err2 or ""),
                registro_id=int(d2["registroId"]) if d2 and d2.get("registroId") else None,
                error_red=err2,
            )
        )
    elif tipo_flujo == "salida" and registro_id is not None:
        st2, d2, ms2, err2 = _salida_silenciosa(
            base_url, disp.token, int(registro_id), tipo_id, timeout
        )
        ok = respuesta_registro_exitosa(d2)
        filas.append(
            ResultadoOperacion(
                indice=indice,
                codigo=codigo,
                grupo=grupo,
                dispositivo=disp.nombre,
                dispositivo_id=disp.dispositivo_id,
                tipo_ingreso_id=tipo_id,
                tipo_ingreso_nombre=tipo_nombre,
                operacion="salida",
                http_status=st2,
                latencia_ms=ms2,
                exito=ok,
                detalle=json.dumps(d2, ensure_ascii=False)[:500] if d2 else (err2 or ""),
                registro_id=int(registro_id),
                error_red=err2,
            )
        )

    return filas


def _percentil(valores: list[float], p: float) -> float | None:
    if not valores:
        return None
    orden = sorted(valores)
    k = (len(orden) - 1) * (p / 100)
    f = int(k)
    c = min(f + 1, len(orden) - 1)
    if f == c:
        return round(orden[f], 2)
    return round(orden[f] + (orden[c] - orden[f]) * (k - f), 2)


def _stats_latencia(filas: list[ResultadoOperacion], operacion: str) -> dict[str, Any]:
    vals = [r.latencia_ms for r in filas if r.operacion == operacion]
    if not vals:
        return {"n": 0}
    return {
        "n": len(vals),
        "min": round(min(vals), 2),
        "max": round(max(vals), 2),
        "media": round(statistics.mean(vals), 2),
        "p50": _percentil(vals, 50),
        "p95": _percentil(vals, 95),
        "p99": _percentil(vals, 99),
    }


def _esc(texto: Any) -> str:
    return html.escape("" if texto is None else str(texto))


def _generar_html(resumen: ResumenSimulacion) -> str:
    filas = resumen.resultados
    total_ops = len(filas)
    exitosas = sum(1 for r in filas if r.exito)
    por_op: dict[str, list[ResultadoOperacion]] = {}
    for r in filas:
        por_op.setdefault(r.operacion, []).append(r)

    validaciones = por_op.get("validar", [])
    validas_api = sum(1 for r in validaciones if r.valido is True)
    entradas = por_op.get("entrada", [])
    salidas = por_op.get("salida", [])
    entradas_ok = sum(1 for r in entradas if r.exito)
    salidas_ok = sum(1 for r in salidas if r.exito)

    por_disp: dict[str, list[ResultadoOperacion]] = {}
    for r in filas:
        por_disp.setdefault(r.dispositivo, []).append(r)

    errores: dict[str, int] = {}
    for r in filas:
        if r.exito:
            continue
        clave = r.error_red or r.motivo or f"HTTP {r.http_status}" or "desconocido"
        errores[clave] = errores.get(clave, 0) + 1

    stats_validar = _stats_latencia(filas, "validar")
    stats_entrada = _stats_latencia(filas, "entrada")
    stats_salida = _stats_latencia(filas, "salida")

    max_lat = max((r.latencia_ms for r in filas), default=1) or 1

    filas_tabla = "\n".join(
        f"""<tr class="{'ok' if r.exito else 'fail'}">
<td>{r.indice}</td><td>{_esc(r.operacion)}</td><td>{_esc(r.codigo)}</td>
<td>{_esc(r.grupo)}</td><td>{_esc(r.dispositivo)}</td><td>{r.dispositivo_id}</td>
<td>{_esc(r.tipo_ingreso_nombre)} ({r.tipo_ingreso_id})</td>
<td>{_esc(r.http_status)}</td><td>{r.latencia_ms}</td>
<td>{'Sí' if r.exito else 'No'}</td><td>{_esc(r.valido)}</td>
<td>{_esc(r.tipo_flujo)}</td><td>{_esc(r.registro_id)}</td>
<td class="detalle">{_esc(r.detalle or r.motivo or r.error_red)}</td>
</tr>"""
        for r in filas
    )

    barras_disp = ""
    for nombre, lista in sorted(por_disp.items()):
        media = statistics.mean(r.latencia_ms for r in lista) if lista else 0
        pct = min(100, (media / max_lat) * 100)
        ok_n = sum(1 for r in lista if r.exito)
        barras_disp += f"""
        <div class="barra-fila">
          <span class="barra-etiq">{_esc(nombre)}</span>
          <div class="barra-track"><div class="barra-fill" style="width:{pct:.1f}%"></div></div>
          <span class="barra-val">{media:.0f} ms · {ok_n}/{len(lista)} ok</span>
        </div>"""

    preflight_html = ""
    for p in resumen.preflight:
        estado = "ok" if p.get("ok") else "fail"
        preflight_html += f"""<tr class="{estado}">
<td>{_esc(p.get('dispositivo'))}</td>
<td>{_esc(p.get('dispositivo_id_esperado'))}</td>
<td>{_esc(p.get('http_status'))}</td>
<td><pre class="json-mini">{_esc(json.dumps(p.get('respuesta'), ensure_ascii=False, indent=2)[:800])}</pre></td>
</tr>"""

    errores_html = "".join(
        f"<li><strong>{_esc(k)}</strong>: {v}</li>" for k, v in sorted(errores.items(), key=lambda x: -x[1])
    ) or "<li>Sin errores registrados</li>"

    def _tarjeta_stats(titulo: str, s: dict[str, Any]) -> str:
        if s.get("n", 0) == 0:
            return f'<div class="card"><h3>{_esc(titulo)}</h3><p>Sin muestras</p></div>'
        return f"""<div class="card">
<h3>{_esc(titulo)}</h3>
<ul class="stats-list">
<li><span>n</span><strong>{s['n']}</strong></li>
<li><span>min</span><strong>{s['min']} ms</strong></li>
<li><span>media</span><strong>{s['media']} ms</strong></li>
<li><span>p50</span><strong>{s['p50']} ms</strong></li>
<li><span>p95</span><strong>{s['p95']} ms</strong></li>
<li><span>p99</span><strong>{s['p99']} ms</strong></li>
<li><span>max</span><strong>{s['max']} ms</strong></li>
</ul></div>"""

    tasa = round(100 * exitosas / total_ops, 2) if total_ops else 0

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Reporte simulación dispositivos SGACCUV</title>
<style>
:root {{
  --bg: #0f1419; --card: #1a2332; --text: #e7ecf3; --muted: #8b9cb3;
  --accent: #3d8bfd; --ok: #3dd68c; --fail: #f07178; --border: #2a3548;
}}
* {{ box-sizing: border-box; }}
body {{ margin: 0; font-family: "Segoe UI", system-ui, sans-serif; background: var(--bg); color: var(--text); line-height: 1.5; }}
header {{ padding: 1.5rem 2rem; border-bottom: 1px solid var(--border); background: linear-gradient(135deg, #1a2332 0%, #0f1419 100%); }}
header h1 {{ margin: 0 0 0.25rem; font-size: 1.5rem; }}
header p {{ margin: 0; color: var(--muted); font-size: 0.9rem; }}
main {{ padding: 1.5rem 2rem 3rem; max-width: 1400px; margin: 0 auto; }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 1rem; margin-bottom: 1.5rem; }}
.card {{ background: var(--card); border: 1px solid var(--border); border-radius: 10px; padding: 1rem 1.25rem; }}
.card h3 {{ margin: 0 0 0.75rem; font-size: 0.95rem; color: var(--muted); font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em; }}
.card .big {{ font-size: 1.75rem; font-weight: 700; color: var(--accent); }}
.stats-list {{ list-style: none; margin: 0; padding: 0; }}
.stats-list li {{ display: flex; justify-content: space-between; padding: 0.25rem 0; border-bottom: 1px solid var(--border); font-size: 0.9rem; }}
.stats-list li span {{ color: var(--muted); }}
section {{ margin-bottom: 2rem; }}
section h2 {{ font-size: 1.1rem; margin-bottom: 0.75rem; }}
.table-wrap {{ overflow: auto; border: 1px solid var(--border); border-radius: 10px; max-height: 480px; }}
table {{ width: 100%; border-collapse: collapse; font-size: 0.82rem; }}
th, td {{ padding: 0.45rem 0.6rem; text-align: left; border-bottom: 1px solid var(--border); }}
th {{ position: sticky; top: 0; background: #243044; z-index: 1; }}
tr.ok td {{ background: rgba(61, 214, 140, 0.06); }}
tr.fail td {{ background: rgba(240, 113, 120, 0.08); }}
td.detalle {{ max-width: 280px; word-break: break-word; font-size: 0.75rem; color: var(--muted); }}
.barra-fila {{ display: grid; grid-template-columns: 120px 1fr 140px; gap: 0.75rem; align-items: center; margin-bottom: 0.5rem; }}
.barra-track {{ height: 10px; background: var(--border); border-radius: 5px; overflow: hidden; }}
.barra-fill {{ height: 100%; background: var(--accent); border-radius: 5px; }}
.barra-etiq, .barra-val {{ font-size: 0.85rem; }}
.json-mini {{ margin: 0; font-size: 0.7rem; white-space: pre-wrap; color: var(--muted); max-height: 120px; overflow: auto; }}
ul.errores {{ margin: 0; padding-left: 1.25rem; }}
.meta {{ font-size: 0.85rem; color: var(--muted); }}
</style>
</head>
<body>
<header>
  <h1>Reporte de simulación — API dispositivos SGACCUV</h1>
  <p class="meta">Generado { _esc(resumen.fin_utc) } · Duración {resumen.duracion_seg:.2f} s · { _esc(resumen.base_url) }</p>
</header>
<main>
  <div class="grid">
    <div class="card"><h3>Lecturas simuladas</h3><div class="big">{resumen.iteraciones}</div></div>
    <div class="card"><h3>Operaciones HTTP</h3><div class="big">{total_ops}</div></div>
    <div class="card"><h3>Éxito global</h3><div class="big">{tasa}%</div><p>{exitosas}/{total_ops} operaciones</p></div>
    <div class="card"><h3>Validar (valido=true)</h3><div class="big">{validas_api}</div><p>de {len(validaciones)} validaciones</p></div>
    <div class="card"><h3>Entradas OK</h3><div class="big">{entradas_ok}</div><p>de {len(entradas)} POST entrada</p></div>
    <div class="card"><h3>Salidas OK</h3><div class="big">{salidas_ok}</div><p>de {len(salidas)} PATCH salida</p></div>
    <div class="card"><h3>Concurrencia</h3><div class="big">{resumen.concurrencia}</div></div>
    <div class="card"><h3>Semilla</h3><div class="big">{resumen.semilla}</div></div>
  </div>

  <section>
    <h2>Parámetros de ejecución</h2>
    <p class="meta">Datos: {_esc(resumen.archivo_datos)} · Inicio {_esc(resumen.inicio_utc)} · Fin {_esc(resumen.fin_utc)}</p>
  </section>

  <section>
    <h2>Preflight — dispositivo/validar (token)</h2>
    <div class="table-wrap">
      <table>
        <thead><tr><th>Dispositivo</th><th>ID esperado</th><th>HTTP</th><th>Respuesta</th></tr></thead>
        <tbody>{preflight_html}</tbody>
      </table>
    </div>
  </section>

  <section>
    <h2>Latencias por operación</h2>
    <div class="grid">
      {_tarjeta_stats("GET validar", stats_validar)}
      {_tarjeta_stats("POST entrada", stats_entrada)}
      {_tarjeta_stats("PATCH salida", stats_salida)}
    </div>
  </section>

  <section>
    <h2>Latencia media por torniquete</h2>
    {barras_disp}
  </section>

  <section>
    <h2>Errores agrupados</h2>
    <ul class="errores">{errores_html}</ul>
  </section>

  <section>
    <h2>Detalle de operaciones</h2>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>#</th><th>Op</th><th>Código</th><th>Grupo</th><th>Torniquete</th>
            <th>ID disp.</th><th>Tipo ingreso</th><th>HTTP</th><th>ms</th><th>OK</th>
            <th>Valido</th><th>Flujo</th><th>Registro</th><th>Detalle</th>
          </tr>
        </thead>
        <tbody>{filas_tabla}</tbody>
      </table>
    </div>
  </section>
</main>
</body>
</html>"""


def ejecutar_simulacion(
    datos: DatosPruebaDispositivo,
    base_url: str,
    iteraciones: int,
    concurrencia: int,
    semilla: int,
    timeout: float,
    archivo_datos: str,
    hacer_preflight: bool,
) -> ResumenSimulacion:
    inicio_ts = time.perf_counter()
    inicio_utc = _ahora_iso()
    rng = random.Random(semilla)
    codigos = datos.todos_los_codigos()
    dispositivos = datos.dispositivos

    resumen = ResumenSimulacion(
        inicio_utc=inicio_utc,
        fin_utc="",
        duracion_seg=0,
        base_url=base_url,
        iteraciones=iteraciones,
        concurrencia=max(1, concurrencia),
        semilla=semilla,
        archivo_datos=archivo_datos,
    )

    if hacer_preflight:
        for d in dispositivos:
            resumen.preflight.append(_preflight_dispositivo(base_url, d, timeout))

    tareas: list[tuple[int, str, str, DispositivoPrueba]] = []
    for i in range(iteraciones):
        codigo, grupo = rng.choice(codigos)
        disp = rng.choice(dispositivos)
        tareas.append((i + 1, codigo, grupo, disp))

    def _worker(tarea: tuple[int, str, str, DispositivoPrueba]) -> list[ResultadoOperacion]:
        idx, cod, grp, dev = tarea
        local_rng = random.Random(semilla + idx * 9973)
        return _ejecutar_lectura(idx, cod, grp, dev, base_url, timeout, local_rng)

    if resumen.concurrencia <= 1:
        for t in tareas:
            resumen.resultados.extend(_worker(t))
    else:
        with ThreadPoolExecutor(max_workers=resumen.concurrencia) as pool:
            futures = [pool.submit(_worker, t) for t in tareas]
            for fut in as_completed(futures):
                resumen.resultados.extend(fut.result())

    resumen.resultados.sort(key=lambda r: (r.indice, r.operacion))
    resumen.duracion_seg = round(time.perf_counter() - inicio_ts, 2)
    resumen.fin_utc = _ahora_iso()
    return resumen


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Simulación de carga API dispositivos SGACCUV con reporte HTML."
    )
    parser.add_argument(
        "--datos",
        type=Path,
        default=None,
        help="Ruta a prueba_dispositivo.md (default: ../.docs/prueba_dispositivo.md)",
    )
    parser.add_argument(
        "--base-url",
        default=env_str("SGACCUV_BASE_URL", "http://localhost:3001"),
        help="URL del API NestJS",
    )
    parser.add_argument(
        "--iteraciones",
        type=int,
        default=100,
        help="Número de lecturas simuladas (código + torniquete aleatorios)",
    )
    parser.add_argument(
        "--concurrencia",
        type=int,
        default=3,
        help="Hilos paralelos (simula varios torniquetes a la vez)",
    )
    parser.add_argument("--semilla", type=int, default=42, help="Semilla RNG reproducible")
    parser.add_argument("--timeout", type=float, default=20.0, help="Timeout HTTP (s)")
    parser.add_argument(
        "--sin-preflight",
        action="store_true",
        help="Omitir GET dispositivo/validar al inicio",
    )
    parser.add_argument(
        "--salida",
        type=Path,
        default=None,
        help="Ruta del reporte HTML (default: reportes-carga/reporte_YYYYMMDD_HHMMSS.html)",
    )
    parser.add_argument(
        "--abrir-reporte",
        action="store_true",
        help="Abrir el HTML en el navegador al terminar",
    )
    args = parser.parse_args()

    ruta_datos = args.datos
    try:
        datos = cargar_prueba_dispositivo(ruta_datos)
    except (FileNotFoundError, ValueError) as e:
        print(f"Error al cargar datos: {e}", file=sys.stderr)
        return 1

    archivo_str = str(ruta_datos or Path(__file__).resolve().parent.parent / ".docs" / "prueba_dispositivo.md")
    print(f"Datos: {len(datos.trabajadores)} trabajadores, {len(datos.alumnos)} alumnos, {len(datos.dispositivos)} dispositivos")
    print(f"API: {args.base_url} · iteraciones={args.iteraciones} · concurrencia={args.concurrencia}")

    resumen = ejecutar_simulacion(
        datos=datos,
        base_url=args.base_url,
        iteraciones=args.iteraciones,
        concurrencia=args.concurrencia,
        semilla=args.semilla,
        timeout=args.timeout,
        archivo_datos=archivo_str,
        hacer_preflight=not args.sin_preflight,
    )

    carpeta = Path(__file__).resolve().parent / "reportes-carga"
    carpeta.mkdir(parents=True, exist_ok=True)
    if args.salida:
        ruta_reporte = args.salida
    else:
        marca = datetime.now().strftime("%Y%m%d_%H%M%S")
        ruta_reporte = carpeta / f"reporte_{marca}.html"

    html_out = _generar_html(resumen)
    ruta_reporte.write_text(html_out, encoding="utf-8")

    total = len(resumen.resultados)
    ok = sum(1 for r in resumen.resultados if r.exito)
    print(f"Finalizado en {resumen.duracion_seg}s — {ok}/{total} operaciones OK")
    print(f"Reporte: {ruta_reporte.resolve()}")

    if args.abrir_reporte:
        webbrowser.open(ruta_reporte.resolve().as_uri())

    return 0 if ok > 0 else 2


if __name__ == "__main__":
    sys.exit(main())
