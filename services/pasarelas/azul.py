"""
Azul — Página de Pagos (Banco Popular).

Basado en el documento oficial "E-Commerce AZUL – Página de Pagos" (versión 2023-08):
- El navegador del cliente hace POST de un formulario a la Página de Pagos.
- Amount / ITBIS: sin punto ni coma, los 2 últimos dígitos son decimales ("1000" = 10.00);
  exento de ITBIS → "000".
- AuthHash de la petición = HMAC-SHA512 (clave AuthKey) de, en este orden:
  MerchantId + MerchantName + MerchantType + CurrencyCode + OrderNumber + Amount + ITBIS +
  ApprovedUrl + DeclinedUrl + CancelUrl + UseCustomField1 + CustomField1Label + CustomField1Value +
  UseCustomField2 + CustomField2Label + CustomField2Value + AuthKey
  calculado sobre la cadena en UNICODE (UTF-16LE), resultado en hexadecimal minúsculas.
- Azul vuelve a ApprovedUrl / DeclinedUrl con los datos en el querystring y un AuthHash de:
  OrderNumber + Amount + AuthorizationCode + DateTime + ResponseCode + IsoCode +
  ResponseMessage + ErrorDescription + RRN + AuthKey   (también UTF-16LE).
  CancelUrl no recibe parámetros.
- Aprobada: IsoCode == "00".
"""
import hashlib
import hmac
from decimal import Decimal, ROUND_HALF_UP

from flask import current_app

from services.pasarelas import ErrorPasarela

URLS = {
    'pruebas': 'https://pruebas.azul.com.do/PaymentPage/',
    'produccion': 'https://pagos.azul.com.do/PaymentPage/Default.aspx',
    'produccion_alterno': 'https://contpagos.azul.com.do/PaymentPage/Default.aspx',
}
CAMPOS_HASH_PETICION = ('MerchantId', 'MerchantName', 'MerchantType', 'CurrencyCode', 'OrderNumber', 'Amount',
                        'ITBIS', 'ApprovedUrl', 'DeclinedUrl', 'CancelUrl', 'UseCustomField1', 'CustomField1Label',
                        'CustomField1Value', 'UseCustomField2', 'CustomField2Label', 'CustomField2Value')
CAMPOS_HASH_RESPUESTA = ('OrderNumber', 'Amount', 'AuthorizationCode', 'DateTime', 'ResponseCode', 'IsoCode',
                         'ResponseMessage', 'ErrorDescription', 'RRN')


def configurada() -> bool:
    c = current_app.config
    return bool(c.get('AZUL_MERCHANT_ID') and c.get('AZUL_AUTH_KEY') and c.get('AZUL_MERCHANT_NAME'))


def formato_monto(valor) -> str:
    """Decimal → formato Azul: centavos sin separadores, mínimo 3 dígitos (0 → "000")."""
    centavos = int((Decimal(str(valor)) * 100).quantize(Decimal('1'), ROUND_HALF_UP))
    if centavos < 0:
        raise ErrorPasarela('Monto negativo')
    return f'{centavos:03d}'


def _hmac(texto: str, clave: str) -> str:
    return hmac.new(clave.encode('utf-8'), texto.encode('utf-16-le'), hashlib.sha512).hexdigest()


def hash_peticion(campos: dict, auth_key: str) -> str:
    return _hmac(''.join(str(campos.get(k, '')) for k in CAMPOS_HASH_PETICION) + auth_key, auth_key)


def hash_respuesta(params: dict, auth_key: str) -> str:
    return _hmac(''.join(str(params.get(k, '')) for k in CAMPOS_HASH_RESPUESTA) + auth_key, auth_key)


def url_pago() -> str:
    return URLS.get(current_app.config.get('AZUL_AMBIENTE', 'pruebas'), URLS['pruebas'])


def campos_formulario(pago, url_aprobado: str, url_declinado: str, url_cancelado: str) -> dict:
    """Campos del formulario (incluido AuthHash) para enviar al cliente a la Página de Pagos."""
    if not configurada():
        raise ErrorPasarela('Azul no está configurado')
    c = current_app.config
    campos = {
        'MerchantId': c['AZUL_MERCHANT_ID'],
        'MerchantName': c['AZUL_MERCHANT_NAME'][:30],
        'MerchantType': c.get('AZUL_MERCHANT_TYPE') or 'E-Commerce',
        'CurrencyCode': c.get('AZUL_CURRENCY_CODE') or '$',
        'OrderNumber': str(pago.id),
        'Amount': formato_monto(pago.monto),
        'ITBIS': formato_monto(pago.itbis),
        'ApprovedUrl': url_aprobado,
        'DeclinedUrl': url_declinado,
        'CancelUrl': url_cancelado,
        'UseCustomField1': '1',
        'CustomField1Label': 'Referencia',
        'CustomField1Value': pago.referencia,
        'UseCustomField2': '0',
        'CustomField2Label': '',
        'CustomField2Value': '',
        'ShowTransactionResult': '0',
        'Locale': 'ES',
    }
    campos['AuthHash'] = hash_peticion(campos, c['AZUL_AUTH_KEY'])
    return campos


def verificar_respuesta(params: dict) -> bool:
    """True si el AuthHash que trae Azul coincide (los datos no fueron alterados)."""
    recibido = (params.get('AuthHash') or '').strip().lower()
    if not recibido or not configurada():
        return False
    esperado = hash_respuesta(params, current_app.config['AZUL_AUTH_KEY'])
    return hmac.compare_digest(recibido, esperado)


def aprobada(params: dict) -> bool:
    return (params.get('IsoCode') or '').strip() == '00'
