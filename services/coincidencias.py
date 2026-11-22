"""
Cruce automático entre lo que se busca (solicitudes) y lo que se vende (publicaciones).

Puntaje = 2 por cada palabra clave en común (3 si es un número: año, medida, capacidad)
          + 3 si es la misma categoría + 1 si es la misma provincia.
Hay coincidencia si comparten ≥ 2 palabras clave, o 1 palabra y la misma categoría,
el puntaje llega a PUNTAJE_MINIMO y además el ARTÍCULO PRINCIPAL de un título (su primera
palabra clave: "alternador", "nevera", "iphone") aparece en el otro. Así "Bomba de agua Corolla
2015" no coincide con "Alternador Corolla 2015" solo por compartir el modelo del carro.

Cada pareja (solicitud, publicación) se guarda una sola vez en la tabla `coincidencias`,
así el broker recibe un único aviso por pareja.
"""
import re
import unicodedata

from extensions import db

PUNTAJE_MINIMO = 5
MAX_CANDIDATOS = 500

PALABRAS_VACIAS = {
    # artículos, preposiciones, conectores
    'el', 'la', 'los', 'las', 'un', 'una', 'unos', 'unas', 'de', 'del', 'al', 'en', 'con', 'sin', 'para',
    'por', 'que', 'y', 'o', 'a', 'se', 'su', 'sus', 'mi', 'mis', 'es', 'muy', 'mas', 'como', 'tipo',
    # verbos y palabras típicas de anuncios que no describen el artículo
    'busco', 'buscando', 'necesito', 'vendo', 'venta', 'vende', 'compro', 'urgente', 'tengo', 'quiero',
    'favor', 'buen', 'buena', 'bueno', 'estado', 'excelente', 'nuevo', 'nueva', 'usado', 'usada',
    'original', 'originales', 'barato', 'precio', 'disponible', 'casi', 'poco', 'uso', 'año', 'anos', 'ano',
}
NUMERO = re.compile(r'^\d+[a-z]{0,3}$')       # 2015, 18, 128gb, 17in


def palabras_clave(texto: str) -> list:
    """Palabras clave en orden: minúsculas, sin acentos, sin palabras vacías, singular simple."""
    texto = unicodedata.normalize('NFKD', texto or '').encode('ascii', 'ignore').decode().lower()
    palabras = []
    for p in re.findall(r'[a-z0-9]+', texto):
        if p in PALABRAS_VACIAS:
            continue
        if not NUMERO.match(p):
            if len(p) < 3:
                continue
            if len(p) > 4 and p.endswith('es'):      # alternadores → alternador
                p = p[:-2]
            elif len(p) > 3 and p.endswith('s'):     # aros → aro, neveras → nevera
                p = p[:-1]
        palabras.append(p)
    return palabras


def normalizar(texto: str) -> set:
    return set(palabras_clave(texto))


def articulo_principal(titulo: str):
    """Primera palabra clave no numérica del título (lo que se busca/vende)."""
    return next((p for p in palabras_clave(titulo) if not NUMERO.match(p)), None)


def _texto_solicitud(sol):
    return f'{sol.titulo} {sol.titulo} {sol.descripcion or ""}'   # el título pesa más


def _texto_publicacion(pub):
    return f'{pub.titulo} {pub.titulo} {pub.descripcion or ""}'


def puntuar(palabras_a: set, palabras_b: set, misma_categoria: bool, misma_provincia: bool,
            principal_a=None, principal_b=None):
    """Devuelve (puntaje, comunes) o (0, comunes) si no llega a ser coincidencia."""
    comunes = palabras_a & palabras_b
    if not comunes:
        return 0, comunes
    if (principal_a or principal_b) and principal_a not in palabras_b and principal_b not in palabras_a:
        return 0, comunes
    if len(comunes) < 2 and not misma_categoria:
        return 0, comunes
    puntaje = sum(3 if NUMERO.match(p) else 2 for p in comunes)
    puntaje += 3 if misma_categoria else 0
    puntaje += 1 if misma_provincia else 0
    return (puntaje if puntaje >= PUNTAJE_MINIMO else 0), comunes


def _guardar(sol, pub, puntaje, comunes):
    """Crea la coincidencia si la pareja es nueva. Devuelve el objeto creado o None."""
    from models import Coincidencia
    if Coincidencia.query.filter_by(solicitud_id=sol.id, publicacion_id=pub.id).first():
        return None
    c = Coincidencia(solicitud_id=sol.id, publicacion_id=pub.id, puntaje=puntaje,
                     palabras=', '.join(sorted(comunes))[:300])
    db.session.add(c)
    return c


def detectar_para_publicacion(pub):
    """Busca solicitudes abiertas para un artículo recién publicado. Devuelve las coincidencias nuevas."""
    from models import Solicitud
    if pub.estado != 'publicada':
        return []
    claves = normalizar(_texto_publicacion(pub))
    nuevas = []
    candidatas = (Solicitud.query.filter(Solicitud.estado.in_(['pendiente', 'en_gestion']))
                  .order_by(Solicitud.created_at.desc()).limit(MAX_CANDIDATOS).all())
    for sol in candidatas:
        if sol.cliente_id == pub.vendedor_id or not sol.acepta_ofertas:
            continue
        puntaje, comunes = puntuar(claves, normalizar(_texto_solicitud(sol)),
                                   sol.categoria_id is not None and sol.categoria_id == pub.categoria_id,
                                   sol.provincia_id is not None and sol.provincia_id == pub.provincia_id,
                                   articulo_principal(pub.titulo), articulo_principal(sol.titulo))
        if puntaje:
            c = _guardar(sol, pub, puntaje, comunes)
            if c:
                nuevas.append(c)
    db.session.commit()
    return nuevas


def detectar_para_solicitud(sol):
    """Busca artículos en venta para una solicitud nueva. Devuelve las coincidencias nuevas."""
    from models import Publicacion
    if not sol.acepta_ofertas:
        return []
    claves = normalizar(_texto_solicitud(sol))
    nuevas = []
    candidatas = (Publicacion.query.filter_by(estado='publicada')
                  .order_by(Publicacion.publicada_en.desc()).limit(MAX_CANDIDATOS).all())
    for pub in candidatas:
        if pub.vendedor_id == sol.cliente_id:
            continue
        puntaje, comunes = puntuar(normalizar(_texto_publicacion(pub)), claves,
                                   sol.categoria_id is not None and sol.categoria_id == pub.categoria_id,
                                   sol.provincia_id is not None and sol.provincia_id == pub.provincia_id,
                                   articulo_principal(pub.titulo), articulo_principal(sol.titulo))
        if puntaje:
            c = _guardar(sol, pub, puntaje, comunes)
            if c:
                nuevas.append(c)
    db.session.commit()
    return nuevas


def recalcular_todo():
    """Revisa todos los artículos publicados contra las solicitudes abiertas (botón del admin)."""
    from models import Publicacion
    total = 0
    for pub in Publicacion.query.filter_by(estado='publicada').all():
        total += len(detectar_para_publicacion(pub))
    return total
