"""
Servicio de subida de imágenes.
- Si Cloudinary está configurado → sube a la nube
- Si no → guarda localmente en static/uploads/
"""
import os, uuid
from flask import current_app


def subir_imagen(file_obj, carpeta='buscapieza'):
    """
    Recibe un FileStorage de Flask (ya validado con services.archivos.es_imagen_valida).
    Retorna (url, public_id)
    """
    cfg = current_app.config
    if cfg.get('CLOUDINARY_CLOUD_NAME') and cfg.get('CLOUDINARY_API_KEY') and cfg.get('CLOUDINARY_API_SECRET'):
        return _subir_cloudinary(file_obj, carpeta)
    return _subir_local(file_obj)


def eliminar_imagen(public_id):
    """Elimina imagen de Cloudinary o del disco local"""
    try:
        if not public_id:
            return
        if public_id.startswith('local_'):
            fname = public_id[len('local_'):]
            path = os.path.join(current_app.root_path, current_app.config['UPLOAD_FOLDER'], os.path.basename(fname))
            if os.path.exists(path):
                os.remove(path)
        elif current_app.config.get('CLOUDINARY_CLOUD_NAME'):
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
    folder = os.path.join(current_app.root_path, current_app.config['UPLOAD_FOLDER'])
    os.makedirs(folder, exist_ok=True)
    file_obj.save(os.path.join(folder, fname))
    return f"/static/uploads/{fname}", f"local_{fname}"
