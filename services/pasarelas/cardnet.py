"""
CardNet — Botón de pago con pantalla (sesiones).

Flujo (guía "Integración con Pantalla (POST)" de developers.cardnet.com.do):
  1. El servidor crea una sesión: POST {base}/sessions (JSON) → devuelve SESSION y session-key.
  2. El navegador del cliente hace POST a {base}/authorize con el campo SESSION.
  3. CardNet devuelve al cliente a ReturnUrl (o CancelUrl).
  4. El servidor consulta el resultado: GET {base}/sessions/{SESSION}?sk={session-key}.
     Aprobada: ResponseCode == "00".

AVISO: la guía oficial está protegida contra lectura automática; los formatos de campos se
tomaron de la guía pública (vía buscador) y de integraciones existentes: TransactionType "0200",
CurrencyCode "214" (DOP), Amount/Tax con 12 dígitos en centavos, MerchantName de 40 caracteres,
TransactionId de 6 dígitos. VALIDAR en el laboratorio de CardNet con las credenciales de prueba
del comercio antes de producción. CARDNET_URL_BASE permite cambiar el servidor sin tocar código.
"""
import json
from decimal import Decimal, ROUND_HALF_UP

import requests
from flask import current_app

from services.pasarelas import ErrorPasarela

URLS_BASE = {
    'pruebas': 'https://labservicios.cardnet.com.do',
    'produccion': 'https://ecommerce.cardnet.com.do',
}
TIMEOUT = 20


def configurada() -> bool:
    c = current_app.config
    return all(c.get(k) for k in ('CARDNET_MERCHANT_NUMBER', 'CARDNET_MERCHANT_TERMINAL',
                                  'CARDNET_ACQUIRING_CODE', 'CARDNET_MERCHANT_TYPE'))


def url_base() -> str:
    c = current_app.config
    return (c.get('CARDNET_URL_BASE') or URLS_BASE.get(c.get('CARDNET_AMBIENTE', 'pruebas'),
                                                       URLS_BASE['pruebas'])).rstrip('/')


def formato_monto(valor) -> str:
    """Decimal → 12 dígitos en centavos: 10.00 → "000000001000"."""
    centavos = int((Decimal(str(valor)) * 100).quantize(Decimal('1'), ROUND_HALF_UP))
    if centavos < 0 or centavos >= 10 ** 12:
        raise ErrorPasarela('Monto fuera de rango')
    return f'{centavos:012d}'


def datos_sesion(pago, url_retorno: str, url_cancelar: str) -> dict:
    c = current_app.config
    nombre = (c.get('CARDNET_MERCHANT_NAME') or c.get('BROKER_NOMBRE') or 'BuscatodoRD')[:40]
    return {
        'TransactionType': '0200',
        'CurrencyCode': '214',
        'AcquiringInstitutionCode': c['CARDNET_ACQUIRING_CODE'],
        'MerchantType': c['CARDNET_MERCHANT_TYPE'],
        'MerchantNumber': c['CARDNET_MERCHANT_NUMBER'],
        'MerchantTerminal': c['CARDNET_MERCHANT_TERMINAL'],
        'ReturnUrl': url_retorno,
        'CancelUrl': url_cancelar,
        'PageLanguaje': 'ESP',
        'OrdenId': str(pago.id),
        'TransactionId': str(pago.id % 1000000).zfill(6),
        'Tax': formato_monto(pago.itbis),
        'MerchantName': nombre.ljust(40),
        'AVS': '',
        'Amount': formato_monto(pago.monto),
    }


def crear_sesion(pago, url_retorno: str, url_cancelar: str):
    """Devuelve (session, session_key). Lanza ErrorPasarela si CardNet no responde bien."""
    if not configurada():
        raise ErrorPasarela('CardNet no está configurado')
    try:
        r = requests.post(f'{url_base()}/sessions', json=datos_sesion(pago, url_retorno, url_cancelar),
                          timeout=TIMEOUT)
        r.raise_for_status()
        datos = r.json()
    except (requests.RequestException, ValueError) as e:
        raise ErrorPasarela(f'No se pudo iniciar el pago con CardNet ({type(e).__name__})')
    sesion = datos.get('SESSION') or datos.get('Session') or datos.get('session')
    clave = datos.get('session-key') or datos.get('SessionKey') or datos.get('sessionKey')
    if not sesion or not clave:
        raise ErrorPasarela('CardNet no devolvió una sesión válida')
    return str(sesion), str(clave)


def url_autorizar() -> str:
    return f'{url_base()}/authorize'


def consultar(sesion: str, clave: str) -> dict:
    """Consulta servidor a servidor el resultado de una sesión."""
    try:
        r = requests.get(f'{url_base()}/sessions/{sesion}', params={'sk': clave}, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()
    except (requests.RequestException, ValueError) as e:
        raise ErrorPasarela(f'No se pudo consultar el resultado en CardNet ({type(e).__name__})')


def aprobada(resultado: dict) -> bool:
    return str(resultado.get('ResponseCode', '')).strip() == '00'


def resumen_seguro(resultado: dict) -> str:
    """JSON de la respuesta sin datos sensibles de la tarjeta (solo últimos 4 dígitos, sin tokens)."""
    limpio = {}
    for k, v in (resultado or {}).items():
        if 'token' in k.lower():
            continue
        if 'card' in k.lower() and isinstance(v, str):
            v = ('****' + v[-4:]) if len(v) >= 4 else '****'
        limpio[k] = v
    return json.dumps(limpio, ensure_ascii=False)[:4000]
