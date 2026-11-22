"""
Validación de imágenes subidas por usuarios.
Comprueba la extensión y además la firma real del archivo (magic bytes),
para que no se pueda subir otra cosa renombrada como .jpg.
"""
ALLOWED = {'png', 'jpg', 'jpeg', 'webp', 'gif'}


def extension_permitida(filename: str) -> bool:
    return bool(filename) and '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED


def _firma_de_imagen(cabecera: bytes) -> bool:
    return (
        cabecera.startswith(b'\x89PNG\r\n\x1a\n')
        or cabecera.startswith(b'\xff\xd8\xff')               # JPEG
        or cabecera[:6] in (b'GIF87a', b'GIF89a')
        or (cabecera[:4] == b'RIFF' and cabecera[8:12] == b'WEBP')
    )


def es_imagen_valida(file_storage) -> bool:
    """True si el FileStorage tiene extensión permitida y contenido de imagen real."""
    if not file_storage or not extension_permitida(file_storage.filename):
        return False
    stream = file_storage.stream
    pos = stream.tell()
    cabecera = stream.read(16)
    stream.seek(pos)
    return _firma_de_imagen(cabecera)
