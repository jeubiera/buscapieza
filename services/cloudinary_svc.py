"""
Servicio de subida de imágenes.
- Si Cloudinary está configurado → sube a la nube
- Si no → guarda localmente en static/uploads/
"""
import os, uuid
from flask import current_app

def subir_imagen(file_obj, carpeta='buscapieza'):
    """
    Recibe un FileStorage de Flask.
    Retorna (url, public_id)
    """
    cloud_name = current_app.config.get('CLOUDINARY_CLOUD_NAME', '')

    if cloud_name:
        return _subir_cloudinary(file_obj, carpeta)
    else:
        return _subir_local(file_obj)

def eliminar_imagen(public_id):
    """Elimina imagen de Cloudinary si aplica"""
    try:
        cloud_name = current_app.config.get('CLOUDINARY_CLOUD_NAME', '')
        if cloud_name and public_id and not public_id.startswith('local_'):
            import cloudinary.uploader
            _configurar_cloudinary()
            cloudinary.uploader.destroy(public_id)
    except Exception as e:
        current_app.logger.error(f"Error eliminando imagen: {e}")

def _configurar_cloudinary():
    import cloudinary
    cloudinary.config(
        cloud_name = current_app.config['CLOUDINARY_CLOUD_NAME'],
        api_key    = current_app.config['CLOUDINARY_API_KEY'],
        api_secret = current_app.config['CLOUDINARY_API_SECRET'],
        secure     = True
    )

def _subir_cloudinary(file_obj, carpeta):
    import cloudinary.uploader
    _configurar_cloudinary()

    result = cloudinary.uploader.upload(
        file_obj,
        folder          = carpeta,
        resource_type   = 'image',
        transformation  = [
            {'width': 1200, 'height': 1200, 'crop': 'limit', 'quality': 'auto:good'},
        ]
    )
    return result['secure_url'], result['public_id']

def _subir_local(file_obj):
    ext    = file_obj.filename.rsplit('.', 1)[-1].lower()
    fname  = f"local_{uuid.uuid4().hex}.{ext}"
    folder = current_app.config['UPLOAD_FOLDER']
    os.makedirs(folder, exist_ok=True)
    path   = os.path.join(folder, fname)
    file_obj.save(path)
    return f"/static/uploads/{fname}", f"local_{fname}"
