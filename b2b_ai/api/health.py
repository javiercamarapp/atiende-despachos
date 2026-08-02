# -*- coding: utf-8 -*-
"""health.py — Deployment readiness engine para el MVP.

Verifica que TODOS los módulos del piloto estén conectados y funcionales
antes de salir a producción:

    1. Import  — cada feature module importa sin errores.
    2. Rutas   — el builder `build_*_router` del módulo construye un
                 APIRouter con ≥1 ruta (las rutas se registran bien).
    3. Modelos — los modelos del módulo (Pydantic en este MVP) se importan
                 y son construibles / serializables (schema válido).
    4. DB      — conectividad al backend (SELECT 1) y conteo de tenants.

Este motor lo comparten el script `scripts/deployment_readiness.py` y los
endpoints de health check (`b2b_ai/api/health_routes.py`), así el reporte es
idéntico en ambos canales.

NOTA de arquitectura: este MVP NO usa SQLAlchemy. Los "modelos" de cada
feature module son Pydantic (v2) con stores en memoria; la persistencia real
va por `b2b_ai.db.db.Database` (sqlite3 o psycopg). Por eso la verificación de
modelos valida constructibilidad/schema en lugar de `create_all`.
"""
from __future__ import annotations

import importlib
import inspect
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from b2b_ai import __version__

# Ruta al paquete b2b_ai (para descubrir b2b_ai/features/*).
_PKG_DIR = Path(__file__).resolve().parent.parent
_FEATURES_DIR = _PKG_DIR / "features"

# Módulos que no tienen `routes.py` / `models.py` pero sí son features reales.
# Se listan explícitamente para no reportarlos como "missing" por estructura.


def discover_feature_modules() -> List[str]:
    """Devuelve los nombres de los feature modules en `b2b_ai/features/`.

    Un módulo cuenta si su directorio tiene `__init__.py`. Orden alfabético
    para que el reporte sea determinista.
    """
    if not _FEATURES_DIR.is_dir():
        return []
    names = [
        d.name
        for d in sorted(_FEATURES_DIR.iterdir())
        if d.is_dir()
        and (d / "__init__.py").is_file()
        and not d.name.startswith("_")
        and not d.name == "__pycache__"
    ]
    return names


def _module_imports(module_name: str) -> bool:
    """¿El módulo importa sin error? (verdadero si ya está en sys.modules o importa)."""
    if module_name in sys.modules:
        return True
    try:
        importlib.import_module(module_name)
        return True
    except Exception:  # noqa: BLE001 — reportar el traceback al caller
        return False


def check_import(module_name: str) -> Dict[str, Any]:
    """Chequea que el feature module (y sus sub-módulos clave) importen."""
    result: Dict[str, Any] = {
        "module": f"b2b_ai.features.{module_name}",
        "status": "ok",
        "detail": "import ok",
    }
    targets = [f"b2b_ai.features.{module_name}", f"b2b_ai.features.{module_name}.routes"]
    for target in targets:
        try:
            importlib.import_module(target)
        except Exception as exc:  # noqa: BLE001
            result["status"] = "error"
            result["detail"] = f"import failed: {target}: {exc}"
            result["traceback"] = traceback.format_exc(limit=6)
            return result
    return result


def _find_router_builder(routes_module: Any) -> Optional[Callable[..., Any]]:
    """Busca el builder principal de router en un módulo de rutas.

    Prefiere el nombre exacto `build_<feature>_router` si existe; si no,
    el primer callable cuyo nombre empiece por `build_` y termine en `router`.
    """
    mod_name = getattr(routes_module, "__name__", "")
    feature = mod_name.rsplit(".", 1)[-1]  # "b2b_ai.features.alertas.routes" -> "routes"
    exact = f"build_{feature}_router"
    if hasattr(routes_module, exact) and callable(getattr(routes_module, exact)):
        return getattr(routes_module, exact)
    # Fallback: cualquier `build_*_router`.
    for name in dir(routes_module):
        if name.startswith("build_") and name.endswith("router"):
            attr = getattr(routes_module, name)
            if callable(attr):
                return attr
    return None


def _stub_require_api_key(deps: Any = None) -> Callable[..., Dict[str, Any]]:
    """Stub de `require_api_key` para construir routers sin autenticación real."""
    def _stub(*args, **kwargs):  # noqa: ANN002, ANN003
        return {"tenant_id": None, "role": "service"}
    return _stub


def _build_router(builder: Callable[..., Any], db: Any = None) -> Any:
    """Construye un router pasando deps compatibles con su firma."""
    sig = inspect.signature(builder)
    kwargs: Dict[str, Any] = {}
    for pname, param in sig.parameters.items():
        if pname == "db":
            kwargs["db"] = db
        elif pname == "require_api_key":
            kwargs["require_api_key"] = _stub_require_api_key()
    # Pasar args posicionales mínimos si no hay kwargs.
    if not kwargs:
        positional = []
        for pname, param in sig.parameters.items():
            if param.default is inspect.Parameter.empty:
                positional.append(None)
            else:
                break
        return builder(*positional)
    return builder(**kwargs)


def check_routes(module_name: str, db: Any = None) -> Dict[str, Any]:
    """Construye el router del módulo y cuenta sus rutas registradas."""
    result: Dict[str, Any] = {
        "module": f"b2b_ai.features.{module_name}",
        "status": "error",
        "detail": "no routes module or no build_*_router found",
        "route_count": 0,
    }
    try:
        routes_mod = importlib.import_module(f"b2b_ai.features.{module_name}.routes")
    except ImportError as exc:
        result["detail"] = f"routes module import failed: {exc}"
        result["traceback"] = traceback.format_exc(limit=5)
        return result
    except Exception as exc:  # noqa: BLE001
        result["detail"] = f"routes module import failed: {exc}"
        result["traceback"] = traceback.format_exc(limit=5)
        return result

    builder = _find_router_builder(routes_mod)
    if builder is None:
        result["detail"] = "no build_*_router callable in routes module"
        return result

    try:
        router = _build_router(builder, db=db)
        routes = getattr(router, "routes", [])
        count = len(routes)
        result["route_count"] = count
        if count > 0:
            result["status"] = "ok"
            result["detail"] = f"{count} route(s) registered"
        else:
            result["detail"] = "router built but 0 routes"
    except Exception as exc:  # noqa: BLE001
        result["detail"] = f"router build failed: {exc}"
        result["traceback"] = traceback.format_exc(limit=6)
    return result


def check_models(module_name: str) -> Dict[str, Any]:
    """Valida que los modelos del módulo (Pydantic) sean construibles.

    Como este MVP no usa SQLAlchemy, "model sync" se interpreta como: el
    módulo `models` importa y cada clase Pydantic BaseModel tiene un schema
    JSON válido (i.e. es instanciable/serializable). Detecta modelos rotos
    (validadores inválidos, referencias circulares, campos mal definidos).
    """
    result: Dict[str, Any] = {
        "module": f"b2b_ai.features.{module_name}",
        "status": "ok",
        "detail": "no models.py (models OK by absence)",
        "model_count": 0,
    }
    try:
        models_mod = importlib.import_module(f"b2b_ai.features.{module_name}.models")
    except ModuleNotFoundError:
        # Sin models.py no hay modelos que validar → ok.
        return result
    except Exception as exc:  # noqa: BLE001
        result["status"] = "error"
        result["detail"] = f"models import failed: {exc}"
        result["traceback"] = traceback.format_exc(limit=6)
        return result

    from pydantic import BaseModel

    models = [
        obj
        for name, obj in vars(models_mod).items()
        if inspect.isclass(obj) and issubclass(obj, BaseModel) and obj is not BaseModel
    ]
    result["model_count"] = len(models)
    if not models:
        result["status"] = "ok"
        result["detail"] = "models.py present but no BaseModel classes"
        return result

    broken = []
    for model in models:
        try:
            model.model_json_schema()  # dispara validación de campos/schema
        except Exception as exc:  # noqa: BLE001
            broken.append(f"{model.__name__}: {exc}")
    if broken:
        result["status"] = "error"
        result["detail"] = "model schema error(s): " + "; ".join(broken[:3])
    else:
        result["detail"] = f"{len(models)} model(s) valid"
    return result


def check_database(db: Any = None) -> Dict[str, Any]:
    """Chequea conectividad a la base de datos (SELECT 1) y estado básico."""
    result: Dict[str, Any] = {
        "name": "database",
        "status": "not_configured",
        "detail": "no db instance provided",
    }
    if db is None:
        return result
    try:
        start = time.perf_counter()
        db.conn.execute("SELECT 1").fetchone()
        latency = (time.perf_counter() - start) * 1000
        backend = "postgresql" if getattr(db, "_is_pg", False) else "sqlite"
        try:
            tenants = len(db.list_tenants())
        except Exception:  # noqa: BLE001
            tenants = -1
        result["status"] = "ok"
        result["detail"] = f"{backend} connected ({tenants} tenants)"
        result["latency_ms"] = round(latency, 2)
        result["backend"] = backend
    except Exception as exc:  # noqa: BLE001
        result["status"] = "error"
        result["detail"] = f"db check failed: {exc}"
        result["traceback"] = traceback.format_exc(limit=6)
    return result


def run_readiness(db: Any = None, module_names: Optional[List[str]] = None) -> Dict[str, Any]:
    """Ejecuta el readiness completo y devuelve el reporte.

    Args:
        db: instancia opcional de `b2b_ai.db.db.Database` para la comprobación
            de DB. Si es None, la DB se reporta como `not_configured`.
        module_names: lista opcional de features a chequear (por defecto,
            todas las descubiertas en b2b_ai/features/).

    Returns:
        Dict con: status, version, timestamp, summary (counts) y `modules`
        (detalle por feature: import/routes/models).
    """
    names = module_names if module_names is not None else discover_feature_modules()
    modules: List[Dict[str, Any]] = []

    for name in names:
        entry: Dict[str, Any] = {
            "name": name,
            "path": f"b2b_ai.features.{name}",
            "import": check_import(name),
            "routes": check_routes(name, db=db),
            "models": check_models(name),
        }
        statuses = [entry["import"]["status"], entry["routes"]["status"],
                    entry["models"]["status"]]
        entry["status"] = "ok" if all(s == "ok" for s in statuses) else "error"
        modules.append(entry)

    db_check = check_database(db)

    summary = {
        "total": len(modules),
        "ok": sum(1 for m in modules if m["status"] == "ok"),
        "error": sum(1 for m in modules if m["status"] == "error"),
        "missing": 0,
        "route_count": sum(m["routes"].get("route_count", 0) for m in modules),
        "model_count": sum(m["models"].get("model_count", 0) for m in modules),
    }

    errors = [
        {"module": m["name"], "detail": _first_error_detail(m)}
        for m in modules if m["status"] != "ok"
    ]

    overall = "ok"
    if errors:
        overall = "error"
    elif db_check["status"] == "not_configured":
        overall = "degraded"

    return {
        "status": overall,
        "service": "b2b-ai-enterprise",
        "version": __version__,
        "timestamp": round(time.time(), 3),
        "database": db_check,
        "summary": summary,
        "modules": modules,
        "errors": errors,
    }


def _first_error_detail(module_entry: Dict[str, Any]) -> str:
    """Devuelve el primer detalle de error de un módulo."""
    for check_name in ("import", "routes", "models"):
        c = module_entry.get(check_name, {})
        if c.get("status") == "error":
            return f"{check_name}: {c.get('detail', 'error')}"
    return "unknown"


# --------------------------------------------------------------------------- #
# Endpoint handlers compartidos (los usa health_routes.py)
# --------------------------------------------------------------------------- #

def basic_health_payload() -> Dict[str, Any]:
    """GET /api/v1/health — status básico (app up + versión)."""
    return {
        "status": "ok",
        "service": "b2b-ai-enterprise",
        "version": __version__,
        "uptime_seconds": round(time.monotonic(), 1),
        "checks": ["basic"],
    }


def deep_health_payload(db: Any = None) -> Dict[str, Any]:
    """GET /api/v1/health/deep — readiness completo por módulo."""
    return run_readiness(db=db)
