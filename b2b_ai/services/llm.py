# -*- coding: utf-8 -*-
"""
llm.py — Servicio LLM del agente (FASE 4).

Interfaz de integración con proveedores de LLM (OpenAI / Anthropic / DeepSeek / OpenRouter)
para las tareas de inteligencia sobre facturas:

    - classify_invoice()  : clasificación contable de un CFDI.
    - extract_data()      : extracción estructurada de campos.
    - summarize()         : resumen ejecutivo.
    - detect_anomaly()    : detección de anomalías/irregularidades.

Principios de diseño (heredados de classify.py):

    * El LLM NUNCA decide por sí solo la deducibilidad ni el registro fiscal
      definitivo: produce una PROPUESTA con confianza + razón + flag de
      revisión humana (NIF manda criterio contable, CFF el fiscal).
    * Fallback obligatorio: si el LLM no está configurado, falla o devuelve
      JSON no parseable, se usan las REGLAS determinísticas (classify_cfdi)
      y se marca `source=rules`. El pipeline nunca se cae por culpa del LLM.

Sin API keys externas: por defecto usa MockLLM (determinístico, sin red).
Para conectar un proveedor real se configuran las env `B2B_LLM_PROVIDER` +
`B2B_OPENAI_API_KEY` / `B2B_ANTHROPIC_API_KEY` / `B2B_DEEPSEEK_API_KEY` /
`B2B_OPENROUTER_API_KEY`.

La clase `LLMService` es la fachada; acepta un cliente `BaseLLM` inyectable
(útil para tests y para swap entre proveedores sin tocar el flujo).
"""
from __future__ import annotations

import json
import os
import random
import re

from b2b_ai.services.classify import classify_cfdi, CATEGORIA_NOMBRE


class LLMError(Exception):
    """Error de llamada al LLM (red, auth, parseo, proveedor)."""


# ==========================================================================
# Prompt templates por tarea. Cada prompt lleva `[TASK:<id>]` y `[DATOS]`:
# la llave de tarea la usa MockLLM para responder determinísticamente, y la
# sección [DATOS] delimita el payload para el mock (los proveedores reales
# lo leen como instrucción normal).
# ==========================================================================
PROMPTS = {
    "classify": {
        "system": (
            "Eres un contador senior con 15 años de experiencia en pólizas y "
            "CFDI en México. Clasifica la factura en una SOLA categoría de "
            "este conjunto exacto: {categorias}. "
            "Devuelve SOLO JSON con las llaves: categoria, confianza (0-1), "
            "razon. Si hay duda, confianza baja. Nunca inventes la categoría."
        ),
        "user": (
            "[TASK:classify]\n"
            "Clasifica esta factura:\n\n[DATOS]\n{datos}\n[/DATOS]\n"
            "Respuesta JSON: {{'categoria': ..., 'confianza': ..., 'razon': ...}}"
        ),
    },
    "extract": {
        "system": (
            "Eres un extractor de datos de facturas/CFDI. Extrae los campos "
            "estructurados. Devuelve SOLO JSON."
        ),
        "user": (
            "[TASK:extract]\n"
            "Extrae los campos de esta factura:\n\n[DATOS]\n{datos}\n[/DATOS]\n"
            "Respuesta JSON: {{'emisor_rfc': ..., 'emisor_nombre': ..., "
            "'receptor_rfc': ..., 'fecha': ..., 'subtotal': ..., 'iva': ..., "
            "'total': ..., 'moneda': ..., 'folio_fiscal': ..., 'descripcion': ...}}"
        ),
    },
    "summarize": {
        "system": (
            "Eres un asistente ejecutivo. Resume la factura en 1-2 frases "
            "claras para un contador. Devuelve SOLO texto, sin JSON."
        ),
        "user": (
            "[TASK:summarize]\n"
            "Resume esta factura:\n\n[DATOS]\n{datos}\n[/DATOS]\n"
            "Resumen (texto plano):"
        ),
    },
    "anomaly": {
        "system": (
            "Eres un auditor. Revisa la factura e indica anomalías "
            "(montos irregulares, tipos raros, IVA mal calculado, proveedores "
            "desconocidos). Devuelve SOLO JSON: "
            "{{'anomalias': [lista de strings], 'nivel': 'normal'|'alerta'}}."
        ),
        "user": (
            "[TASK:anomaly]\n"
            "Audita esta factura:\n\n[DATOS]\n{datos}\n[/DATOS]\n"
            "Respuesta JSON:"
        ),
    },
}

_CATEGORIAS_PROMPT = ", ".join(CATEGORIA_NOMBRE.keys())


def _render_prompt(task, payload):
    p = PROMPTS[task]
    user = p["user"].format(datos=_json(payload))
    system = p["system"].format(categorias=_CATEGORIAS_PROMPT)
    return system, user


def _json(obj):
    return json.dumps(obj, ensure_ascii=False, default=str)


def _parse_json(value):
    """Parsea una respuesta LLM a dict. Acepta str JSON o dict (idempotente)."""
    if isinstance(value, dict):
        return value
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8", errors="replace")
    if not isinstance(value, str):
        return {}
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _extract_datos(user_prompt):
    """Extrae el payload entre [DATOS] y [/DATOS] (para el mock)."""
    m = re.search(r"\[DATOS\](.*?)\[/DATOS\]", user_prompt, re.S)
    if not m:
        return {}
    try:
        return json.loads(m.group(1))
    except Exception:  # noqa: BLE001
        return {"_raw": m.group(1)}


_TASK_RE = re.compile(r"\[TASK:(\w+)\]")


def _task_of(user_prompt):
    m = _TASK_RE.search(user_prompt)
    return m.group(1) if m else "unknown"


# ==========================================================================
# Clientes LLM (BaseLLM -> proveedores + mock)
# ==========================================================================
class BaseLLM:
    """Contrato de un cliente LLM. Implementar `complete`."""

    name = "base"

    def complete(self, messages, temperature=0.0, max_tokens=512) -> str:
        raise NotImplementedError


def _http_post_json(url, headers, body, timeout=15):
    """POST JSON vía stdlib urllib. Devuelve el dict parseado o lanza LLMError."""
    import urllib.request
    import urllib.error
    from urllib.parse import urlparse
    # Restringe esquema a http/https: bloquea file:, etc. (mitiga SSRF en
    # caso de que la base_url se configure mal o llegue de un origen externo).
    if (urlparse(url).scheme or "").lower() not in ("http", "https"):
        raise LLMError(f"Esquema de URL no permitido para el proveedor LLM.")
    req = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"),
        headers=headers, method="POST")
    try:
        # nosec B310: esquema http/https validado con urlparse justo arriba.
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        raise LLMError(f"HTTP {e.code} de {url}: {detail}") from e
    except Exception as e:  # noqa: BLE001
        raise LLMError(f"Fallo de red hacia {url}: {e}") from e


class OpenAIProvider(BaseLLM):
    """OpenAI Chat Completions (compatible con /v1/chat/completions)."""

    name = "openai"

    def __init__(self, api_key=None, base_url=None, model=None):
        self.api_key = api_key or os.environ.get("B2B_OPENAI_API_KEY", "")
        self.base_url = (base_url or os.environ.get("B2B_LLM_BASE_URL")
                         or "https://api.openai.com/v1").rstrip("/")
        self.model = model or os.environ.get("B2B_LLM_MODEL", "gpt-4o-mini")
        if not self.api_key:
            raise LLMError("OpenAIProvider requiere B2B_OPENAI_API_KEY.")

    def complete(self, messages, temperature=0.0, max_tokens=512):
        body = {"model": self.model, "messages": messages,
                "temperature": temperature, "max_tokens": max_tokens}
        data = _http_post_json(
            f"{self.base_url}/chat/completions",
            {"Authorization": f"Bearer {self.api_key}",
             "Content-Type": "application/json"}, body)
        return data["choices"][0]["message"]["content"]


class DeepSeekProvider(BaseLLM):
    """DeepSeek (API compatible con OpenAI)."""

    name = "deepseek"

    def __init__(self, api_key=None, base_url=None, model=None):
        self.api_key = api_key or os.environ.get("B2B_DEEPSEEK_API_KEY", "")
        self.base_url = (base_url or os.environ.get("B2B_LLM_BASE_URL")
                         or "https://api.deepseek.com/v1").rstrip("/")
        self.model = model or os.environ.get("B2B_LLM_MODEL", "deepseek-chat")
        if not self.api_key:
            raise LLMError("DeepSeekProvider requiere B2B_DEEPSEEK_API_KEY.")

    def complete(self, messages, temperature=0.0, max_tokens=512):
        body = {"model": self.model, "messages": messages,
                "temperature": temperature, "max_tokens": max_tokens}
        data = _http_post_json(
            f"{self.base_url}/chat/completions",
            {"Authorization": f"Bearer {self.api_key}",
             "Content-Type": "application/json"}, body)
        return data["choices"][0]["message"]["content"]


class AnthropicProvider(BaseLLM):
    """Anthropic Messages API."""

    name = "anthropic"

    def __init__(self, api_key=None, base_url=None, model=None):
        self.api_key = api_key or os.environ.get("B2B_ANTHROPIC_API_KEY", "")
        self.base_url = (base_url or os.environ.get("B2B_LLM_BASE_URL")
                         or "https://api.anthropic.com").rstrip("/")
        self.model = model or os.environ.get("B2B_LLM_MODEL",
                                             "claude-sonnet-4-20250514")
        if not self.api_key:
            raise LLMError("AnthropicProvider requiere B2B_ANTHROPIC_API_KEY.")

    def complete(self, messages, temperature=0.0, max_tokens=512):
        system = ""
        msgs = []
        for m in messages:
            if m["role"] == "system":
                system += (m["content"] + "\n")
            else:
                msgs.append({"role": m["role"], "content": m["content"]})
        body = {"model": self.model, "max_tokens": max_tokens,
                "temperature": temperature, "system": system, "messages": msgs}
        data = _http_post_json(
            f"{self.base_url}/v1/messages",
            {"x-api-key": self.api_key, "anthropic-version": "2023-06-01",
             "Content-Type": "application/json"}, body)
        return "".join(b.get("text", "") for b in data["content"]
                       if b.get("type") == "text")


class MockLLM(BaseLLM):
    """
    LLM simulado determinístico (sin red, sin API keys).

    Lee la llave de tarea `[TASK:...]` y el payload `[DATOS]...[/DATOS]` del
    prompt y responde con JSON bien formado, delegando el razonamiento a las
    reglas reales (classify_cfdi) para que el flujo LLM se pruebe de punta a
    punta (prompt → respuesta → parseo → normalización). Soporta fallo
    inducido para probar el fallback (`fail_next=True` o `error_rate>0`).
    """

    name = "mock"

    def __init__(self, error_rate=0.0):
        self.error_rate = error_rate
        self.fail_next = False
        self.calls = []
        self.last_prompt = ""

    def complete(self, messages, temperature=0.0, max_tokens=512):
        user = messages[-1]["content"]
        self.last_prompt = user
        self.calls.append(user)
        if self.fail_next:
            self.fail_next = False
            raise LLMError("Mock: fallo inducido (fail_next).")
        if self.error_rate and random.random() < self.error_rate:
            raise LLMError("Mock: fallo aleatorio.")
        task = _task_of(user)
        datos = _extract_datos(user)
        return self._respond(task, datos)

    def _respond(self, task, datos):
        if task == "classify":
            r = classify_cfdi(datos)
            return json.dumps({
                "categoria": r["categoria"],
                "confianza": r["confianza"],
                "razon": "Mock LLM: " + r["razon"],
            }, ensure_ascii=False)
        if task == "extract":
            base = {k: datos.get(k) for k in (
                "emisor_rfc", "emisor_nombre", "receptor_rfc", "fecha",
                "subtotal", "iva", "total", "moneda", "folio_fiscal",
                "descripcion") if datos.get(k) is not None}
            return json.dumps(base, ensure_ascii=False, default=str)
        if task == "summarize":
            total = datos.get("total")
            emisor = datos.get("emisor_nombre") or datos.get("emisor_rfc", "")
            fecha = datos.get("fecha", "")
            return (f"Factura de {emisor} por {total} "
                    f"registrada el {fecha}.")
        if task == "anomaly":
            return json.dumps(_rule_anomalies(datos), ensure_ascii=False)
        return json.dumps({"resultado": "ok"})

    def classify_invoice(self, datos):
        """Clasificación contable. Contrato igual a LLMClient.classify_invoice,
        delegando en _respond('classify', datos) para que los tests que
        sobreescriben _respond funcionen."""
        try:
            raw = self._respond("classify", datos)
            res = _parse_json(raw)
            cat = str(res.get("categoria") or "desconocido")
            if cat not in CATEGORIA_NOMBRE:
                cat = "desconocido"
            conf = float(res.get("confianza", 0.0))
            conf = max(0.0, min(1.0, conf))
            return {
                "categoria": cat,
                "confianza": round(conf, 2),
                "razon": str(res.get("razon", "")),
                "requires_human_review": conf < 0.70 or cat == "desconocido",
                "source": "llm",
            }
        except Exception:  # noqa: BLE001
            base = classify_cfdi(datos)
            base["source"] = "rules"
            return base

    def detect_anomaly(self, datos):
        """Detección de anomalías. Contrato igual a LLMClient.detect_anomaly,
        delegando en _respond('anomaly', datos)."""
        try:
            raw = self._respond("anomaly", datos)
            res = _parse_json(raw)
            anomalias = res.get("anomalias") or []
            if not isinstance(anomalias, list):
                anomalias = [str(anomalias)]
            nivel = res.get("nivel") if res.get("nivel") in ("normal", "alerta") \
                else ("alerta" if anomalias else "normal")
            return {"anomalias": [str(a) for a in anomalias],
                    "nivel": nivel, "source": "llm"}
        except Exception:  # noqa: BLE001
            out = _rule_anomalies(datos)
            out["source"] = "rules"
            return out

    def __repr__(self):
        return f"<MockLLM error_rate={self.error_rate}>"


class OpenRouterLLM(BaseLLM):
    """LLM vía OpenRouter API (openrouter.ai).

    OpenAI-compatible endpoint apuntando a OpenRouter. El modelo por defecto
    es DeepSeek V4 Flash (deepseek/deepseek-v4-flash). Usa B2B_OPENROUTER_API_KEY
    y sigue las mismas env que el resto (B2B_LLM_BASE_URL, B2B_LLM_MODEL).
    """

    name = "openrouter"

    def __init__(self, api_key=None, base_url=None, model=None):
        self.api_key = api_key or os.environ.get("B2B_OPENROUTER_API_KEY", "")
        self.base_url = (base_url or os.environ.get("B2B_LLM_BASE_URL")
                         or "https://openrouter.ai/api/v1").rstrip("/")
        self.model = model or os.environ.get("B2B_LLM_MODEL",
                                             "deepseek/deepseek-v4-flash")
        if not self.api_key:
            raise LLMError("OpenRouterLLM requiere B2B_OPENROUTER_API_KEY.")

    def _post(self, url, headers, body):
        """POST con urllib; extraído para poder mockearlo en tests."""
        return _http_post_json(url, headers, body)

    def complete(self, messages, temperature=0.0, max_tokens=512):
        body = {"model": self.model, "messages": messages,
                "temperature": temperature, "max_tokens": max_tokens}
        data = self._post(
            f"{self.base_url}/chat/completions",
            {"Authorization": f"Bearer {self.api_key}",
             "Content-Type": "application/json",
             "HTTP-Referer": "https://b2b-ai.app",
             "X-Title": "B2B AI Agent"},
            body)
        return data["choices"][0]["message"]["content"]

    def __repr__(self):
        return f"<OpenRouterLLM model={self.model}>"


def get_llm(provider=None):
    """Fábrica: devuelve el proveedor configurado por env o el MockLLM."""
    provider = (provider or os.environ.get("B2B_LLM_PROVIDER", "")).lower()
    if provider == "openai":
        return OpenAIProvider()
    if provider == "anthropic":
        return AnthropicProvider()
    if provider == "deepseek":
        return DeepSeekProvider()
    if provider == "openrouter":
        try:
            return OpenRouterLLM()
        except LLMError:
            return MockLLM()
    return MockLLM()


# ==========================================================================
# Reglas de fallback (detect_anomaly) y servicio LLM (fachada)
# ==========================================================================
def _rule_anomalies(datos):
    """Reglas determinísticas de anomalías (fallback / mock de anomaly)."""
    anomalias = []
    try:
        subtotal = float(datos.get("subtotal") or 0)
        iva = float(datos.get("iva") or 0)
        total = float(datos.get("total") or 0)
        if iva < 0 or subtotal < 0 or total < 0:
            anomalias.append("Montos negativos detectados.")
        # Nómina (N) y pago (P) NO llevan IVA; no aplicar la prueba del 16%.
        if datos.get("tipo") not in ("N", "P") and total > 0 and subtotal > 0 \
                and iva >= 0:
            iva_esp = round(subtotal * 0.16, 2)
            if abs(iva - iva_esp) > 1.0:
                anomalias.append(f"IVA ({iva}) no coincide con 16% ({iva_esp}).")
    except (TypeError, ValueError):
        anomalias.append("Montos no numéricos.")
    if datos.get("tipo") not in ("I", "E", "P", "T", "N"):
        anomalias.append(f"Tipo de comprobante atípico: {datos.get('tipo')}.")
    return {"anomalias": anomalias,
            "nivel": "alerta" if anomalias else "normal"}


class LLMService:
    """
    Fachada de inteligencia sobre facturas con fallback a reglas.

    Uso:
        svc = LLMService()            # usa get_llm() (mock por defecto)
        svc = LLMService(client=MockLLM())
        cl = svc.classify_invoice(datos)
        svc.last_source   # 'llm' | 'rules'
    """

    def __init__(self, client=None):
        self.client = client or get_llm()
        self.last_source = "rules"
        self.last_error = None

    # ---- helpers internos -------------------------------------------------
    def _run(self, task, payload):
        system, user = _render_prompt(task, payload)
        text = self.client.complete(
            [{"role": "system", "content": system},
             {"role": "user", "content": user}])
        if not text or not text.strip():
            raise LLMError("Respuesta LLM vacía.")
        return text

    def _run_json(self, task, payload):
        text = self._run(task, payload)
        data = json.loads(text)
        if not isinstance(data, dict):
            raise LLMError("Respuesta LLM no es objeto JSON.")
        return data

    def _failed(self, e):
        self.last_error = str(e)
        self.last_source = "rules"

    # ---- tareas públicas --------------------------------------------------
    def classify_invoice(self, datos):
        """
        Clasificación contable. Devuelve dict con categoria, confianza,
        razon, requires_human_review y source ('llm'|'rules').
        Fallback: classify_cfdi (reglas).
        """
        try:
            res = self._run_json("classify", datos)
            cat = str(res.get("categoria") or "desconocido")
            if cat not in CATEGORIA_NOMBRE:
                cat = "desconocido"
            conf = float(res.get("confianza", 0.0))
            conf = max(0.0, min(1.0, conf))
            self.last_source = "llm"
            return {
                "categoria": cat,
                "confianza": round(conf, 2),
                "razon": str(res.get("razon", "")),
                "requires_human_review": conf < 0.70 or cat == "desconocido",
                "source": "llm",
            }
        except Exception as e:  # noqa: BLE001
            self._failed(e)
            base = classify_cfdi(datos)
            base["source"] = "rules"
            return base

    def extract_data(self, texto):
        """
        Extracción estructurada de campos. `texto` puede ser un dict (CFDI ya
        parseado) o un string (factura/OCR). Fallback: devolver lo ya
        estructurado o el texto crudo.
        """
        try:
            res = self._run_json("extract", texto)
            # Normaliza tipos numéricos a str para consistencia con db
            for k in ("subtotal", "iva", "total"):
                if k in res and res[k] is not None:
                    res[k] = str(res[k])
            res["source"] = "llm"
            self.last_source = "llm"
            return res
        except Exception as e:  # noqa: BLE001
            self._failed(e)
            if isinstance(texto, dict):
                out = {k: texto.get(k) for k in (
                    "emisor_rfc", "emisor_nombre", "receptor_rfc", "fecha",
                    "subtotal", "iva", "total", "moneda", "folio_fiscal",
                    "descripcion") if texto.get(k) is not None}
                out["source"] = "rules"
                return out
            return {"descripcion": str(texto)[:1000], "source": "rules"}

    def summarize(self, datos):
        """Resumen ejecutivo (texto). Fallback: resumen genérico."""
        try:
            text = self._run("summarize", datos).strip()
            self.last_source = "llm"
            return text
        except Exception as e:  # noqa: BLE001
            self._failed(e)
            total = datos.get("total", "")
            emisor = datos.get("emisor_nombre") or datos.get("emisor_rfc", "")
            return f"Factura registrada: {emisor} por {total}."

    def detect_anomaly(self, datos):
        """Detección de anomalías. Fallback: reglas determinísticas."""
        try:
            res = self._run_json("anomaly", datos)
            anomalias = res.get("anomalias") or []
            if not isinstance(anomalias, list):
                anomalias = [str(anomalias)]
            nivel = res.get("nivel") if res.get("nivel") in ("normal", "alerta") \
                else ("alerta" if anomalias else "normal")
            self.last_source = "llm"
            return {"anomalias": [str(a) for a in anomalias],
                    "nivel": nivel, "source": "llm"}
        except Exception as e:  # noqa: BLE001
            self._failed(e)
            out = _rule_anomalies(datos)
            out["source"] = "rules"
            return out


def main():
    import sys
    from b2b_ai.cfdi.parser import parse_cfdi
    datos = parse_cfdi(sys.argv[1]) if len(sys.argv) > 1 else {
        "emisor_nombre": "Demo", "total": "100.00", "tipo": "I",
        "conceptos": [{"descripcion": "papeleria y consumibles"}]}
    svc = LLMService()
    print("Cliente :", svc.client)
    print("Clasif  :", json.dumps(svc.classify_invoice(datos),
                                  ensure_ascii=False, indent=2))
    print("Resumen :", svc.summarize(datos))
    print("Anomalía:", json.dumps(svc.detect_anomaly(datos),
                                   ensure_ascii=False, indent=2))
    print("Fuente  :", svc.last_source)


if __name__ == "__main__":
    main()