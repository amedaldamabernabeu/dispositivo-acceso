"""
Carga datos de prueba desde .docs/prueba_dispositivo.md (códigos y torniquetes).
Solo lectura; no modifica el sistema SGACCUV.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class TiposIngresoDispositivo:
    lector_rfid: int
    lector_qr: int
    teclado: int

    def ids(self) -> list[int]:
        return [self.lector_rfid, self.lector_qr, self.teclado]

    def nombre_por_id(self, tipo_id: int) -> str:
        if tipo_id == self.lector_rfid:
            return "Lector RFID"
        if tipo_id == self.lector_qr:
            return "Lector QR"
        if tipo_id == self.teclado:
            return "Teclado"
        return f"tipo-{tipo_id}"


@dataclass(frozen=True)
class DispositivoPrueba:
    nombre: str
    token: str
    dispositivo_id: int
    tipos: TiposIngresoDispositivo


@dataclass
class DatosPruebaDispositivo:
    trabajadores: list[str] = field(default_factory=list)
    alumnos: list[str] = field(default_factory=list)
    dispositivos: list[DispositivoPrueba] = field(default_factory=list)

    def todos_los_codigos(self) -> list[tuple[str, str]]:
        """(codigo, grupo) con grupo 'trabajador' | 'alumno'."""
        return (
            [(c, "trabajador") for c in self.trabajadores]
            + [(c, "alumno") for c in self.alumnos]
        )


_RE_TOKEN = re.compile(r"\b([a-f0-9]{64})\b", re.IGNORECASE)
_RE_DISPOSITIVO_ID = re.compile(r"dispositivo\s*id\s*:\s*(\d+)", re.IGNORECASE)
_RE_TIPOS = re.compile(
    r"ID\s+Lector\s+RFID:\s*(\d+)\s*,\s*ID\s+Lector\s+QR:\s*(\d+),?\s*ID\s+Teclado:\s*(\d+)",
    re.IGNORECASE,
)
_RE_CODIGO = re.compile(r"^\d+$")


def _ruta_md_por_defecto() -> Path:
    return Path(__file__).resolve().parent.parent / ".docs" / "prueba_dispositivo.md"


def cargar_prueba_dispositivo(ruta: Path | None = None) -> DatosPruebaDispositivo:
    archivo = ruta or _ruta_md_por_defecto()
    if not archivo.is_file():
        raise FileNotFoundError(f"No se encontró el archivo de prueba: {archivo}")

    texto = archivo.read_text(encoding="utf-8")
    lineas = texto.splitlines()
    datos = DatosPruebaDispositivo()
    seccion: str | None = None
    bloque_torniquete: list[str] = []

    def _flush_torniquete(bloque: list[str]) -> None:
        if not bloque:
            return
        contenido = "\n".join(bloque)
        nombre = "Torniquete"
        for ln in bloque:
            m = re.match(r"Torniquete\s+(\d+)\s*:", ln, re.IGNORECASE)
            if m:
                nombre = f"Torniquete {m.group(1)}"
                break
        tokens = _RE_TOKEN.findall(contenido)
        if not tokens:
            return
        m_id = _RE_DISPOSITIVO_ID.search(contenido)
        m_tipos = _RE_TIPOS.search(contenido)
        if not m_id or not m_tipos:
            return
        datos.dispositivos.append(
            DispositivoPrueba(
                nombre=nombre,
                token=tokens[0].lower(),
                dispositivo_id=int(m_id.group(1)),
                tipos=TiposIngresoDispositivo(
                    lector_rfid=int(m_tipos.group(1)),
                    lector_qr=int(m_tipos.group(2)),
                    teclado=int(m_tipos.group(3)),
                ),
            )
        )

    for linea in lineas:
        raw = linea.strip()
        if raw.startswith("#"):
            if bloque_torniquete:
                _flush_torniquete(bloque_torniquete)
                bloque_torniquete = []
            titulo = raw.lstrip("#").strip().lower()
            if "trabajador" in titulo:
                seccion = "trabajadores"
            elif "alumno" in titulo:
                seccion = "alumnos"
            elif "dispositivo" in titulo:
                seccion = "dispositivos"
            else:
                seccion = None
            continue

        if seccion == "dispositivos":
            if raw.lower().startswith("torniquete"):
                if bloque_torniquete:
                    _flush_torniquete(bloque_torniquete)
                bloque_torniquete = [raw]
            elif bloque_torniquete and raw:
                bloque_torniquete.append(raw)
            continue

        if not raw or not _RE_CODIGO.match(raw):
            continue
        if seccion == "trabajadores":
            datos.trabajadores.append(raw)
        elif seccion == "alumnos":
            datos.alumnos.append(raw)

    if bloque_torniquete:
        _flush_torniquete(bloque_torniquete)

    if not datos.trabajadores and not datos.alumnos:
        raise ValueError("No se encontraron códigos en el archivo de prueba.")
    if not datos.dispositivos:
        raise ValueError("No se encontraron dispositivos (torniquetes) en el archivo.")

    return datos
