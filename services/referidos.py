"""
Programa de referidos: comisiones por las compras que pagan las personas de tu red.

Misma mecánica que el motor MLM de AmbarERP (clientes_red.py), adaptada a BuscatodoRD:
- Cada usuario tiene un código; quien se registra con él queda debajo (patrocinador).
- Cuando una compra queda PAGADA, se generan comisiones para los N niveles hacia arriba.
- Base configurable: la comisión de BuscatodoRD en esa venta (por defecto) o el precio pagado.
- Al cerrar cada mes: quien califica (compras personales del mes ≥ meta) cobra lo pendiente y lo
  acumulado; quien no, acumula hasta `meses_arrastre` meses y después vence.
- El admin liquida (paga) las comisiones disponibles.

Todo se configura en la tabla `configuracion` (claves referidos_*), desde Admin → Referidos.
El programa viene DESACTIVADO hasta que el admin lo active.
"""
import secrets
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from flask import current_app
from sqlalchemy import func

from extensions import db
from models import (Usuario, Transaccion, ComisionReferido, LiquidacionReferido, CierreReferido,
                    Configuracion, ahora_utc)

CENTAVO = Decimal('0.01')
ALFABETO = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'   # sin 0/O ni 1/I para evitar confusiones
POR_DEFECTO = {
    'referidos_activo': '0',
    'referidos_niveles': '10,5,3',          # % por nivel (1, 2, 3...)
    'referidos_base': 'comision',           # 'comision' (lo que gana BuscatodoRD) o 'precio'
    'referidos_meta': '0',                  # RD$ de compras personales en el mes para calificar (0 = todos)
    'referidos_meses_arrastre': '2',        # meses que se guarda lo no calificado antes de vencer
    'referidos_minimo_pago': '500',         # saldo mínimo para liquidar
}
MAX_NIVELES = 5


class ErrorReferidos(Exception):
    pass


# ── Configuración ─────────────────────────────────────────────────────────────

def _valor(clave):
    fila = Configuracion.query.filter_by(clave=clave).first()
    return fila.valor if fila and fila.valor not in (None, '') else POR_DEFECTO[clave]


def config() -> dict:
    niveles = []
    for parte in _valor('referidos_niveles').split(','):
        try:
            niveles.append(Decimal(parte.strip()))
        except InvalidOperation:
            pass
    return {
        'activo': _valor('referidos_activo') == '1',
        'niveles': niveles[:MAX_NIVELES],
        'base': 'precio' if _valor('referidos_base') == 'precio' else 'comision',
        'meta': Decimal(_valor('referidos_meta')),
        'meses_arrastre': int(_valor('referidos_meses_arrastre')),
        'minimo_pago': Decimal(_valor('referidos_minimo_pago')),
    }


def guardar_config(form) -> str:
    """Valida y guarda. Devuelve un mensaje de error o None."""
    try:
        niveles = [Decimal(p.strip()) for p in (form.get('niveles') or '').split(',') if p.strip()]
        meta = Decimal((form.get('meta') or '0').strip())
        minimo = Decimal((form.get('minimo_pago') or '0').strip())
        meses = int((form.get('meses_arrastre') or '0').strip())
    except (InvalidOperation, ValueError):
        return 'Revisa los valores: niveles separados por coma (p. ej. 10,5,3) y números válidos'
    base = 'precio' if form.get('base') == 'precio' else 'comision'
    if not 1 <= len(niveles) <= MAX_NIVELES:
        return f'Define entre 1 y {MAX_NIVELES} niveles'
    if any(n < 0 or n > 100 for n in niveles):
        return 'Cada porcentaje debe estar entre 0 y 100'
    if base == 'comision' and sum(niveles) > 100:
        return 'La suma de los niveles no puede pasar del 100 % de tu comisión'
    if base == 'precio' and sum(niveles) > 30:
        return 'Sobre el precio, la suma de niveles no puede pasar del 30 % (te quedarías sin margen)'
    if meta < 0 or minimo < 0 or not 0 <= meses <= 24:
        return 'Meta y mínimo deben ser ≥ 0 y los meses de arrastre entre 0 y 24'
    valores = {
        'referidos_activo': '1' if form.get('activo') else '0',
        'referidos_niveles': ','.join(format(n.normalize(), 'f') for n in niveles),
        'referidos_base': base,
        'referidos_meta': str(meta),
        'referidos_meses_arrastre': str(meses),
        'referidos_minimo_pago': str(minimo),
    }
    for clave, valor in valores.items():
        fila = Configuracion.query.filter_by(clave=clave).first()
        if fila:
            fila.valor = valor
        else:
            db.session.add(Configuracion(clave=clave, valor=valor))
    db.session.commit()
    return None


# ── Códigos y patrocinadores ──────────────────────────────────────────────────

def asegurar_codigo(usuario: Usuario) -> str:
    if not usuario.codigo_referido:
        while True:
            codigo = ''.join(secrets.choice(ALFABETO) for _ in range(7))
            if not Usuario.query.filter_by(codigo_referido=codigo).first():
                break
        usuario.codigo_referido = codigo
    return usuario.codigo_referido


def resolver_codigo(codigo):
    codigo = (codigo or '').strip().upper()[:12]
    if not codigo:
        return None
    return Usuario.query.filter_by(codigo_referido=codigo, activo=True).first()


def asignar_patrocinador(usuario: Usuario, codigo) -> bool:
    """Liga al usuario con quien lo invitó (solo una vez, nunca a sí mismo ni creando un ciclo)."""
    if usuario.patrocinador_id or usuario.rol == 'admin':
        return False
    patro = resolver_codigo(codigo)
    if not patro or patro.id == usuario.id or patro.rol == 'admin':
        return False
    # Evitar ciclos: el usuario no puede estar por encima de su patrocinador
    actual, vistos = patro, set()
    while actual is not None and actual.id not in vistos:
        if actual.id == usuario.id:
            return False
        vistos.add(actual.id)
        actual = actual.patrocinador
    usuario.patrocinador_id = patro.id
    return True


def linea_ascendente(usuario: Usuario, niveles: int) -> list:
    """[patrocinador, patrocinador del patrocinador, ...] hasta `niveles`, sin ciclos."""
    resultado, actual, vistos = [], usuario.patrocinador, {usuario.id}
    while actual is not None and len(resultado) < niveles and actual.id not in vistos:
        resultado.append(actual)
        vistos.add(actual.id)
        actual = actual.patrocinador
    return resultado


# ── Periodos ──────────────────────────────────────────────────────────────────

def periodo_de(fecha) -> str:
    return (fecha or ahora_utc()).strftime('%Y-%m')


def sumar_meses(periodo: str, meses: int) -> str:
    y, m = map(int, periodo.split('-'))
    total = y * 12 + (m - 1) + meses
    return f'{total // 12:04d}-{total % 12 + 1:02d}'


def _rango_periodo(periodo: str):
    from datetime import datetime
    y, m = map(int, periodo.split('-'))
    inicio = datetime(y, m, 1)
    fin_y, fin_m = (y + (m // 12), m % 12 + 1)
    return inicio, datetime(fin_y, fin_m, 1)


def compras_personales(usuario_id: int, periodo: str) -> Decimal:
    inicio, fin = _rango_periodo(periodo)
    total = db.session.query(func.sum(Transaccion.precio_cliente)).filter(
        Transaccion.cliente_id == usuario_id, Transaccion.estado_pago == 'pagado',
        Transaccion.fecha_pago >= inicio, Transaccion.fecha_pago < fin).scalar()
    return Decimal(total or 0)


def califica(usuario_id: int, periodo: str, cfg=None) -> bool:
    cfg = cfg or config()
    return cfg['meta'] <= 0 or compras_personales(usuario_id, periodo) >= cfg['meta']


# ── Generar / reversar ────────────────────────────────────────────────────────

def generar_comisiones(trans: Transaccion) -> list:
    """
    Llamar cuando una compra queda pagada (antes del commit). Idempotente.
    Devuelve las comisiones creadas.
    """
    cfg = config()
    if not cfg['activo'] or trans.estado_pago != 'pagado' or not trans.cliente:
        return []
    if ComisionReferido.query.filter_by(transaccion_id=trans.id).first():
        return []
    base = Decimal(trans.comision_broker if cfg['base'] == 'comision' else trans.precio_cliente or 0)
    if base <= 0:
        return []
    periodo = periodo_de(trans.fecha_pago)
    vence = sumar_meses(periodo, cfg['meses_arrastre'])
    creadas = []
    for nivel, (beneficiario, pct) in enumerate(zip(linea_ascendente(trans.cliente, len(cfg['niveles'])),
                                                     cfg['niveles']), start=1):
        # No cobra quien está inactivo, ni el vendedor por su propia venta
        if not beneficiario.activo or beneficiario.id == trans.proveedor_id:
            continue
        monto = (base * pct / 100).quantize(CENTAVO, ROUND_HALF_UP)
        if monto <= 0:
            continue
        c = ComisionReferido(beneficiario_id=beneficiario.id, comprador_id=trans.cliente_id, transaccion_id=trans.id,
                             nivel=nivel, porcentaje=pct, base=base, monto=monto, periodo=periodo, vence_periodo=vence)
        db.session.add(c)
        creadas.append(c)
    return creadas


def reversar(comision: ComisionReferido):
    if comision.estado == 'pagada':
        raise ErrorReferidos('No se puede reversar una comisión ya pagada')
    comision.estado = 'reversada'


# ── Cierre mensual ────────────────────────────────────────────────────────────

def cerrar_periodo(periodo: str, admin=None) -> CierreReferido:
    """
    Procesa las comisiones pendientes y acumuladas generadas hasta `periodo` (inclusive):
    califica en ese mes → disponible · no califica y ya llegó a su vencimiento → vencida · si no → acumulada.
    """
    if periodo >= periodo_de(ahora_utc()):
        raise ErrorReferidos('Solo se pueden cerrar meses ya terminados')
    if CierreReferido.query.filter_by(periodo=periodo).first():
        raise ErrorReferidos(f'El periodo {periodo} ya está cerrado')
    cfg = config()
    abiertas = ComisionReferido.query.filter(
        ComisionReferido.estado.in_(['pendiente_calificacion', 'acumulada']),
        ComisionReferido.periodo <= periodo).all()
    cache, cuenta = {}, {'disponible': 0, 'acumulada': 0, 'vencida': 0}
    for c in abiertas:
        if c.beneficiario_id not in cache:
            cache[c.beneficiario_id] = califica(c.beneficiario_id, periodo, cfg)
        if cache[c.beneficiario_id]:
            c.estado = 'disponible'
        elif periodo >= c.vence_periodo:
            c.estado = 'vencida'
        else:
            c.estado = 'acumulada'
        cuenta[c.estado] += 1
    cierre = CierreReferido(periodo=periodo, disponibles=cuenta['disponible'], acumuladas=cuenta['acumulada'],
                            vencidas=cuenta['vencida'], cerrado_por_id=admin.id if admin else None)
    db.session.add(cierre)
    return cierre


def ultimo_periodo_cerrable() -> str:
    return sumar_meses(periodo_de(ahora_utc()), -1)


# ── Saldos y liquidación ──────────────────────────────────────────────────────

def saldo(usuario_id: int) -> dict:
    filas = db.session.query(ComisionReferido.estado, func.sum(ComisionReferido.monto)).filter(
        ComisionReferido.beneficiario_id == usuario_id).group_by(ComisionReferido.estado).all()
    datos = {e: Decimal(0) for e in ('pendiente_calificacion', 'acumulada', 'disponible', 'pagada', 'vencida')}
    for estado, total in filas:
        if estado in datos:
            datos[estado] = Decimal(total or 0)
    datos['en_proceso'] = datos['pendiente_calificacion'] + datos['acumulada']
    return datos


def liquidar(beneficiario: Usuario, admin, metodo='transferencia', referencia=None, notas=None, forzar=False):
    disponibles = beneficiario.comisiones_referido.filter_by(estado='disponible').all()
    total = sum((c.monto for c in disponibles), Decimal(0))
    if total <= 0:
        raise ErrorReferidos('No tiene comisiones disponibles')
    minimo = config()['minimo_pago']
    if total < minimo and not forzar:
        raise ErrorReferidos(f'El saldo (RD${total:,.2f}) no llega al mínimo de pago (RD${minimo:,.2f})')
    liq = LiquidacionReferido(beneficiario_id=beneficiario.id, monto=total, metodo=(metodo or 'transferencia')[:40],
                              referencia=(referencia or '')[:120] or None, notas=notas,
                              registrado_por_id=admin.id if admin else None)
    db.session.add(liq)
    db.session.flush()
    for c in disponibles:
        c.estado, c.liquidacion_id = 'pagada', liq.id
    return liq


# ── Red ───────────────────────────────────────────────────────────────────────

def red_por_niveles(usuario: Usuario, niveles: int) -> list:
    """[[nivel 1], [nivel 2], ...] con los usuarios de la red (sin ciclos)."""
    resultado, actuales, vistos = [], [usuario], {usuario.id}
    for _ in range(niveles):
        siguientes = []
        for u in actuales:
            for r in u.referidos.order_by(Usuario.created_at).all():
                if r.id not in vistos:
                    vistos.add(r.id)
                    siguientes.append(r)
        if not siguientes:
            break
        resultado.append(siguientes)
        actuales = siguientes
    return resultado


def nombre_privado(usuario: Usuario) -> str:
    """'Ana Pérez' → 'Ana P.' (en la red no se muestran datos de contacto)."""
    partes = (usuario.nombre or '').split()
    if not partes:
        return 'Usuario'
    return partes[0] + (f' {partes[1][0]}.' if len(partes) > 1 else '')
