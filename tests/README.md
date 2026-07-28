# Tests - BuscaPieza RD

Esta carpeta contiene todos los tests automatizados para BuscaPieza RD.

## Estructura

```
tests/
├── __init__.py           # Inicialización del paquete
├── conftest.py           # Fixtures compartidas
├── test_models.py        # Tests de modelos de datos
├── test_auth.py          # Tests de autenticación
├── test_solicitudes.py   # Tests de solicitudes
└── README.md            # Este archivo
```

## Ejecutar Tests

### Todos los tests

```bash
pytest
```

### Con reporte de cobertura

```bash
pytest --cov=. --cov-report=html
```

Ver reporte: Abre `htmlcov/index.html` en tu navegador

### Tests específicos

```bash
# Solo tests de autenticación
pytest tests/test_auth.py

# Solo tests de modelos
pytest tests/test_models.py

# Solo tests de solicitudes
pytest tests/test_solicitudes.py

# Test específico
pytest tests/test_auth.py::TestLogin::test_login_successful
```

### Con más detalle

```bash
# Verbose mode
pytest -v

# Con print statements
pytest -s

# Detener en primer fallo
pytest -x
```

## Fixtures Disponibles

Las fixtures están definidas en `conftest.py`:

### Aplicación y Base de Datos
- `app`: Instancia de la aplicación Flask en modo testing
- `_db`: Base de datos configurada para tests
- `client`: Cliente de testing Flask

### Usuarios
- `admin_user`: Usuario con rol admin
- `cliente_user`: Usuario con rol cliente
- `proveedor_user`: Usuario con rol proveedor

### Clientes Autenticados
- `authenticated_client`: Cliente autenticado como cliente
- `admin_authenticated_client`: Cliente autenticado como admin

## Ejemplo de Uso

```python
def test_ejemplo(client, cliente_user):
    """Ejemplo de test usando fixtures"""
    # Hacer login
    response = client.post('/auth/login', data={
        'email': 'cliente@test.com',
        'password': 'TestPassword123!'
    })

    assert response.status_code == 302  # Redirect después de login
```

## Escribir Nuevos Tests

1. Crea un nuevo archivo `test_*.py`
2. Importa pytest y las fixtures necesarias
3. Organiza tests en clases (opcional pero recomendado)
4. Usa nombres descriptivos: `test_lo_que_debe_hacer`

Ejemplo:

```python
import pytest
from models import MiModelo

class TestMiModelo:
    """Tests para MiModelo"""

    def test_crear_modelo(self, _db):
        """Test: Descripción de lo que prueba"""
        obj = MiModelo(campo='valor')
        _db.session.add(obj)
        _db.session.commit()

        assert obj.id is not None
```

## Marcadores (Markers)

Puedes usar marcadores para categorizar tests:

```python
@pytest.mark.slow
def test_operacion_lenta():
    pass

@pytest.mark.integration
def test_integracion_completa():
    pass
```

Ejecutar solo tests marcados:

```bash
pytest -m slow
pytest -m "not slow"
```

## Cobertura de Código

Objetivo: Mantener cobertura > 80%

Para ver qué código no está cubierto:

```bash
pytest --cov=. --cov-report=term-missing
```

## Troubleshooting

### Error: "No module named 'app'"

Asegúrate de estar en la raíz del proyecto y con el venv activado:

```bash
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows
```

### Error: "Database locked"

Limpia la base de datos de testing:

```bash
rm -f test.db
pytest
```

### Los tests pasan individualmente pero fallan juntos

Problema de estado compartido. Verifica que cada test limpia después de sí mismo o usa fixtures con scope adecuado.

## CI/CD

Los tests se ejecutan automáticamente en:
- GitHub Actions (cada push/PR)
- Pre-commit hooks (si están configurados)

## Recursos

- [Pytest Documentation](https://docs.pytest.org/)
- [Flask Testing](https://flask.palletsprojects.com/en/stable/testing/)
- [pytest-flask](https://pytest-flask.readthedocs.io/)
