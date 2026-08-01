# -*- coding: utf-8 -*-
"""auto_classifier.py — ML-based CFDI classifier for accounting categories.

Uses scikit-learn (GradientBoostingClassifier) with TF-IDF on text features
and numeric/categorical features. Generates synthetic training data based on
SAT catalog rules and common accounting patterns.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

try:
    from sklearn.ensemble import GradientBoostingClassifier
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.pipeline import Pipeline
    from sklearn.compose import ColumnTransformer
    from sklearn.preprocessing import OneHotEncoder, StandardScaler
    from sklearn.model_selection import cross_val_score
    import joblib
    HAS_SKLEARN = True
except ImportError:
    HAS_SKLEARN = False

from b2b_ai.features.bookkeeping.models import CFDIClassification

log = logging.getLogger(__name__)

# ===================================================================
# Synthetic training data generator
# ===================================================================

# Patterns: (category, tipo_cfdi, keywords, typical_amount_range, uso_cfdis, regimenes)
SYNTHETIC_PATTERNS: List[Dict[str, Any]] = [
    {
        "category": "servicios_profesionales",
        "tipo_cfdi": "I",
        "keywords": [
            "honorarios", "consultoría", "asesoría", "servicio profesional",
            "servicios legales", "contabilidad", "auditoría", "dictamen",
            "ingeniería", "arquitectura", "desarrollo software", "diseño",
        ],
        "amount_range": (5000, 200000),
        "uso_cfdis": ["G03", "G01"],
        "regimenes": ["612", "601", "605"],
    },
    {
        "category": "renta_oficina",
        "tipo_cfdi": "I",
        "keywords": [
            "renta", "arrendamiento", "local comercial", "oficina",
            "lease", "alquiler", "subarrendamiento",
        ],
        "amount_range": (10000, 150000),
        "uso_cfdis": ["G03", "G01"],
        "regimenes": ["601", "612", "605"],
    },
    {
        "category": "materia_prima",
        "tipo_cfdi": "I",
        "keywords": [
            "materia prima", "material", "insumo", "componente",
            "suministro", "empaque", "envase",
        ],
        "amount_range": (3000, 500000),
        "uso_cfdis": ["G01"],
        "regimenes": ["601", "612"],
    },
    {
        "category": "publicidad",
        "tipo_cfdi": "I",
        "keywords": [
            "publicidad", "marketing", "campaña", "anuncio",
            "redes sociales", "google ads", "facebook ads",
            "promoción", "mercadotecnia",
        ],
        "amount_range": (2000, 100000),
        "uso_cfdis": ["G03"],
        "regimenes": ["601", "612", "605"],
    },
    {
        "category": "honorarios_legales",
        "tipo_cfdi": "I",
        "keywords": [
            "honorarios abogado", "notario", "legal", "jurídico",
            "constitución", "poder", "escritura", "litigio",
        ],
        "amount_range": (3000, 300000),
        "uso_cfdis": ["G03"],
        "regimenes": ["612", "601"],
    },
    {
        "category": "comision_bancaria",
        "tipo_cfdi": "I",
        "keywords": [
            "comisión", "banco", "comisión bancaria", "transferencia",
            "dispersión", "tarjeta", "TPV",
        ],
        "amount_range": (50, 10000),
        "uso_cfdis": ["G03"],
        "regimenes": ["601"],
    },
    {
        "category": "intereses_bancarios",
        "tipo_cfdi": "I",
        "keywords": [
            "intereses", "rendimiento", "interés", "cetes",
            "inversión", "fondo",
        ],
        "amount_range": (10, 50000),
        "uso_cfdis": ["G03"],
        "regimenes": ["601"],
    },
    {
        "category": "nomina",
        "tipo_cfdi": "I",
        "keywords": [
            "nómina", "sueldo", "salario", "pago empleados",
            "compensación", "prestaciones", "aguinaldo", "prima vacacional",
        ],
        "amount_range": (5000, 100000),
        "uso_cfdis": ["G03"],
        "regimenes": ["601", "612"],
    },
    {
        "category": "arrendamiento",
        "tipo_cfdi": "I",
        "keywords": [
            "arrendamiento", "renta vehículo", "renta equipo",
            "leasing", "renta maquinaria",
        ],
        "amount_range": (3000, 80000),
        "uso_cfdis": ["G03"],
        "regimenes": ["601", "612", "605"],
    },
    {
        "category": "seguros",
        "tipo_cfdi": "I",
        "keywords": [
            "seguro", "póliza", "prima seguro", "aseguradora",
            "cobertura", "siniestro",
        ],
        "amount_range": (2000, 50000),
        "uso_cfdis": ["G03"],
        "regimenes": ["601"],
    },
    {
        "category": "telefonia",
        "tipo_cfdi": "I",
        "keywords": [
            "teléfono", "internet", "telecomunicaciones", "celular",
            "fibra óptica", "datos", "Telmex", "Telcel", "AT&T",
        ],
        "amount_range": (500, 20000),
        "uso_cfdis": ["G03"],
        "regimenes": ["601"],
    },
    {
        "category": "transporte",
        "tipo_cfdi": "I",
        "keywords": [
            "transporte", "flete", "envío", "paquetería",
            "logística", "DHL", "FedEx", "Uber",
        ],
        "amount_range": (200, 30000),
        "uso_cfdis": ["G03"],
        "regimenes": ["601", "612"],
    },
    {
        "category": "equipo_computo",
        "tipo_cfdi": "I",
        "keywords": [
            "computadora", "laptop", "monitor", "impresora",
            "equipo cómputo", "servidor", "disco", "SSD",
        ],
        "amount_range": (5000, 100000),
        "uso_cfdis": ["G01"],
        "regimenes": ["601", "612"],
    },
    {
        "category": "mantenimiento",
        "tipo_cfdi": "I",
        "keywords": [
            "mantenimiento", "reparación", "limpieza", "jardinería",
            "plomería", "electricidad", "albañilería",
        ],
        "amount_range": (1000, 50000),
        "uso_cfdis": ["G03"],
        "regimenes": ["612", "601"],
    },
    {
        "category": "papeleria",
        "tipo_cfdi": "I",
        "keywords": [
            "papelería", "artículos oficina", "material oficina",
            "tinta", "papel", "carpeta", "oficina",
        ],
        "amount_range": (200, 10000),
        "uso_cfdis": ["G01"],
        "regimenes": ["601", "612"],
    },
    {
        "category": "venta_servicios",
        "tipo_cfdi": "E",
        "keywords": [
            "servicio", "consultoría", "honorarios", "factura",
            "proyecto", "desarrollo",
        ],
        "amount_range": (10000, 500000),
        "uso_cfdis": ["G03"],
        "regimenes": ["601", "612"],
    },
    {
        "category": "venta_mercancia",
        "tipo_cfdi": "E",
        "keywords": [
            "venta", "mercancía", "producto", "artículo",
            "venta de", "importe",
        ],
        "amount_range": (1000, 300000),
        "uso_cfdis": ["G01"],
        "regimenes": ["601"],
    },
]


def generate_synthetic_dataset(
    n_samples_per_category: int = 60,
    seed: int = 42,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Generate synthetic CFDI training data.

    Returns (cfdis, labels) where each cfdi is a dict with features
    and each label is the category string.
    """
    rng = np.random.RandomState(seed)
    cfdis: List[Dict[str, Any]] = []
    labels: List[str] = []

    for pattern in SYNTHETIC_PATTERNS:
        for _ in range(n_samples_per_category):
            # Pick random keywords and combine
            kw_indices = rng.choice(
                len(pattern["keywords"]),
                size=rng.randint(1, 4),
                replace=False,
            )
            desc_parts = [pattern["keywords"][i] for i in kw_indices]
            descripcion = " ".join(desc_parts)

            # Add some noise words
            noise_words = ["pago", "factura", "CFDI", "México", "CDMX", "empresa"]
            noise_idx = rng.choice(len(noise_words), size=rng.randint(0, 2), replace=False)
            for ni in noise_idx:
                pos = rng.randint(0, len(desc_parts) + 1)
                desc_parts.insert(pos, noise_words[ni])
            descripcion = " ".join(desc_parts)

            lo, hi = pattern["amount_range"]
            subtotal = round(rng.uniform(lo, hi), 2)
            tasa_iva = 0.16 if rng.random() > 0.1 else 0.0
            iva = round(subtotal * tasa_iva, 2)

            cfdis.append({
                "descripcion": descripcion,
                "subtotal": subtotal,
                "iva": iva,
                "total": round(subtotal + iva, 2),
                "tasa_iva": tasa_iva,
                "tipo_cfdi": pattern["tipo_cfdi"],
                "uso_cfdi": pattern["uso_cfdis"][rng.randint(0, len(pattern["uso_cfdis"]))],
                "regimen_emisor": pattern["regimenes"][rng.randint(0, len(pattern["regimenes"]))],
                "rfc_emisor": f"XAXX01010100{rng.randint(0, 9)}",
            })
            labels.append(pattern["category"])

    return cfdis, labels


# ===================================================================
# Feature extraction
# ===================================================================

def _build_feature_df(cfdis: List[Dict[str, Any]]):
    """Build a feature DataFrame from CFDI dicts."""
    import pandas as pd

    rows = []
    for cfdi in cfdis:
        rows.append({
            "descripcion": cfdi.get("descripcion", ""),
            "subtotal": float(cfdi.get("subtotal", 0)),
            "iva": float(cfdi.get("iva", 0)),
            "total": float(cfdi.get("total", 0)),
            "tasa_iva": float(cfdi.get("tasa_iva", 0.16)),
            "tipo_cfdi": cfdi.get("tipo_cfdi", "I"),
            "uso_cfdi": cfdi.get("uso_cfdi", ""),
            "regimen_emisor": cfdi.get("regimen_emisor", ""),
        })
    return pd.DataFrame(rows)


# ===================================================================
# AutoClassifier
# ===================================================================

class AutoClassifier:
    """ML classifier for CFDI → accounting category.

    Uses GradientBoosting with mixed feature types:
    - Text: TF-IDF on description
    - Numeric: subtotal, IVA, total, IVA rate
    - Categorical: tipo_cfdi, uso_cfdi, regimen_emisor

    Falls back to rule-based classification when scikit-learn is
    not available.
    """

    CONFIDENCE_HIGH = 0.85
    CONFIDENCE_MEDIUM = 0.60

    def __init__(self, model_path: Optional[str] = None):
        self._model = None
        self._column_transformer = None
        self._categories: List[str] = []
        self._trained = False
        self._overrides: Dict[str, str] = {}  # rfc → last category override

        if model_path and os.path.exists(model_path):
            self._load(model_path)
        elif HAS_SKLEARN:
            self._build_pipeline()

    def _build_pipeline(self) -> None:
        """Build the scikit-learn pipeline."""
        if not HAS_SKLEARN:
            return

        text_transformer = TfidfVectorizer(
            max_features=500, ngram_range=(1, 2), stop_words=None
        )
        numeric_features = ["subtotal", "iva", "total", "tasa_iva"]
        categorical_features = ["tipo_cfdi", "uso_cfdi", "regimen_emisor"]

        self._column_transformer = ColumnTransformer(
            transformers=[
                ("text", text_transformer, "descripcion"),
                ("num", StandardScaler(), numeric_features),
                ("cat", OneHotEncoder(handle_unknown="ignore", sparse_output=False), categorical_features),
            ],
            sparse_threshold=0.0,
        )

        self._model = Pipeline([
            ("features", self._column_transformer),
            ("classifier", GradientBoostingClassifier(
                n_estimators=150,
                max_depth=5,
                min_samples_split=10,
                learning_rate=0.1,
                random_state=42,
            )),
        ])

    def train(
        self,
        cfdis: Optional[List[Dict[str, Any]]] = None,
        labels: Optional[List[str]] = None,
        n_synthetic: int = 60,
    ) -> Dict[str, Any]:
        """Train the classifier.

        If cfdis/labels are None, generates synthetic training data.
        Returns training metrics.
        """
        if not HAS_SKLEARN:
            return {"status": "skipped", "reason": "scikit-learn not installed"}

        if cfdis is None or labels is None:
            cfdis, labels = generate_synthetic_dataset(n_samples_per_category=n_synthetic)

        X = _build_feature_df(cfdis)
        y = np.array(labels)
        self._categories = sorted(set(labels))

        # Cross-validation
        scores = cross_val_score(self._model, X, y, cv=min(5, len(set(labels))), scoring="f1_macro")
        mean_f1 = float(np.mean(scores))

        # Final fit
        self._model.fit(X, y)
        self._trained = True

        return {
            "status": "trained",
            "n_samples": len(cfdis),
            "n_categories": len(self._categories),
            "categories": self._categories,
            "f1_macro_mean": round(mean_f1, 4),
            "f1_macro_std": round(float(np.std(scores)), 4),
        }

    def predict(self, cfdi: Dict[str, Any]) -> Tuple[str, float]:
        """Predict category and confidence for a single CFDI.

        Returns (category, confidence).
        """
        # Check overrides first
        rfc = cfdi.get("rfc_emisor", "")
        if rfc in self._overrides:
            return self._overrides[rfc], 1.0

        if not self._trained or not HAS_SKLEARN:
            return self._rule_based_predict(cfdi)

        X = _build_feature_df([cfdi])
        proba = self._model.predict_proba(X)[0]
        idx_max = int(np.argmax(proba))
        categoria = self._model.classes_[idx_max]
        confidence = float(proba[idx_max])

        return categoria, confidence

    def predict_batch(self, cfdis: List[Dict[str, Any]]) -> List[Tuple[str, float]]:
        """Predict categories for a batch of CFDIs."""
        return [self.predict(cfdi) for cfdi in cfdis]

    def add_override(self, rfc: str, category: str) -> None:
        """Record a human override for an RFC → category mapping."""
        self._overrides[rfc] = category

    def get_suggestions(self, cfdi: Dict[str, Any], top_n: int = 3) -> List[Dict[str, Any]]:
        """Get top-N category suggestions with confidence scores."""
        if not self._trained or not HAS_SKLEARN:
            cat, conf = self._rule_based_predict(cfdi)
            return [{"categoria": cat, "confidence": round(conf, 4)}]

        X = _build_feature_df([cfdi])
        proba = self._model.predict_proba(X)[0]
        indices = np.argsort(proba)[::-1][:top_n]

        return [
            {
                "categoria": self._model.classes_[i],
                "confidence": round(float(proba[i]), 4),
            }
            for i in indices
        ]

    def _rule_based_predict(self, cfdi: Dict[str, Any]) -> Tuple[str, float]:
        """Fallback rule-based classification using keyword matching."""
        desc = cfdi.get("descripcion", "").lower()
        tipo = cfdi.get("tipo_cfdi", "I")

        best_cat = "otros"
        best_score = 0.0

        for pattern in SYNTHETIC_PATTERNS:
            if pattern["tipo_cfdi"] != tipo:
                continue
            matches = sum(1 for kw in pattern["keywords"] if kw.lower() in desc)
            if matches > best_score:
                best_score = matches
                best_cat = pattern["category"]

        confidence = min(0.5 + best_score * 0.15, 0.95) if best_score > 0 else 0.3
        return best_cat, confidence

    def save(self, path: str) -> None:
        """Save the trained model to disk."""
        if HAS_SKLEARN and self._trained:
            joblib.dump({"model": self._model, "categories": self._categories}, path)

    def _load(self, path: str) -> None:
        """Load a trained model from disk."""
        if HAS_SKLEARN:
            data = joblib.load(path)
            self._model = data["model"]
            self._categories = data.get("categories", [])
            self._trained = True

    @property
    def is_trained(self) -> bool:
        return self._trained

    @property
    def categories(self) -> List[str]:
        return list(self._categories)
