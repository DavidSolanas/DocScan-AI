"""SII/AEAT XML export — Suministro Inmediato de Información."""
from __future__ import annotations

import io
import xml.etree.ElementTree as ET
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.schemas.extraction import ExtractionResult

# SII namespace
_NS_SOAPENV = "http://schemas.xmlsoap.org/soap/envelope/"
_NS_SII = "https://www2.agenciatributaria.gob.es/static_files/common/internet/dep/aplicaciones/es/aeat/ssii/fact/ws/SuministroInformacion.xsd"

ET.register_namespace("soapenv", _NS_SOAPENV)
ET.register_namespace("sii", _NS_SII)


def _fmt(v: Decimal | None, default: str = "0.00") -> str:
    """Format a Decimal to 2 decimal places string."""
    if v is None:
        return default
    return f"{v:.2f}"


def generate_sii_xml(
    result: ExtractionResult,
    titular_cif: str,
    titular_name: str,
    periodo: str,  # "YYYY-MM"
) -> tuple[bytes, list[str]]:
    """Generate SII/AEAT XML for a received invoice (FacturasRecibidas).

    Returns (xml_bytes, warnings).
    """
    warnings: list[str] = []
    a = result.anchor

    # Collect warnings for missing required fields
    if not a.issuer_cif:
        warnings.append("Missing issuer CIF")
    if not a.invoice_number:
        warnings.append("Missing invoice number")
    if a.base_imponible is None:
        warnings.append("Missing base imponible")

    # Parse periodo
    try:
        year, month = periodo.split("-")
        month_2digit = month.zfill(2)
    except (ValueError, AttributeError):
        year = str(date.today().year)
        month_2digit = str(date.today().month).zfill(2)

    today_str = date.today().isoformat()

    # Build XML tree
    soapenv_ns = f"{{{_NS_SOAPENV}}}"
    sii_ns = f"{{{_NS_SII}}}"

    envelope = ET.Element(f"{soapenv_ns}Envelope")
    body = ET.SubElement(envelope, f"{soapenv_ns}Body")
    suministro = ET.SubElement(body, f"{sii_ns}SuministroLRFacturasRecibidas")

    # Cabecera
    cabecera = ET.SubElement(suministro, f"{sii_ns}Cabecera")
    ET.SubElement(cabecera, f"{sii_ns}IDVersionSii").text = "1.1"
    titular_el = ET.SubElement(cabecera, f"{sii_ns}Titular")
    ET.SubElement(titular_el, f"{sii_ns}NombreRazon").text = titular_name
    ET.SubElement(titular_el, f"{sii_ns}NIF").text = titular_cif
    ET.SubElement(cabecera, f"{sii_ns}TipoComunicacion").text = "A0"

    # Registro
    registro = ET.SubElement(suministro, f"{sii_ns}RegistroLRFacturasRecibidas")

    periodo_el = ET.SubElement(registro, f"{sii_ns}PeriodoLiquidacion")
    ET.SubElement(periodo_el, f"{sii_ns}Ejercicio").text = year
    ET.SubElement(periodo_el, f"{sii_ns}Periodo").text = month_2digit

    id_factura = ET.SubElement(registro, f"{sii_ns}IDFactura")
    id_emisor = ET.SubElement(id_factura, f"{sii_ns}IDEmisorFactura")
    ET.SubElement(id_emisor, f"{sii_ns}NIF").text = a.issuer_cif or ""
    ET.SubElement(id_factura, f"{sii_ns}NumSerieFacturaEmisor").text = a.invoice_number or ""
    ET.SubElement(id_factura, f"{sii_ns}FechaExpedicionFacturaEmisor").text = a.issue_date or ""

    factura = ET.SubElement(registro, f"{sii_ns}FacturaRecibida")
    ET.SubElement(factura, f"{sii_ns}TipoFactura").text = "F1"
    ET.SubElement(factura, f"{sii_ns}ClaveRegimenEspecialOTrascendencia").text = "01"
    ET.SubElement(factura, f"{sii_ns}ImporteTotal").text = _fmt(a.total_amount)

    desglose = ET.SubElement(factura, f"{sii_ns}DesgloseIVA")
    detalle = ET.SubElement(desglose, f"{sii_ns}DetalleIVA")
    ET.SubElement(detalle, f"{sii_ns}TipoImpositivo").text = _fmt(a.iva_rate)
    ET.SubElement(detalle, f"{sii_ns}BaseImponible").text = _fmt(a.base_imponible)
    ET.SubElement(detalle, f"{sii_ns}CuotaSoportada").text = _fmt(a.iva_amount)

    contraparte = ET.SubElement(factura, f"{sii_ns}Contraparte")
    ET.SubElement(contraparte, f"{sii_ns}NombreRazon").text = a.issuer_name or ""
    ET.SubElement(contraparte, f"{sii_ns}NIF").text = a.issuer_cif or ""

    ET.SubElement(factura, f"{sii_ns}FechaRegContable").text = today_str
    ET.SubElement(factura, f"{sii_ns}CuotaDeducible").text = _fmt(a.iva_amount)

    # Serialize
    tree = ET.ElementTree(envelope)
    ET.indent(tree, space="  ")
    buf = io.BytesIO()
    tree.write(buf, encoding="utf-8", xml_declaration=True)
    return buf.getvalue(), warnings
