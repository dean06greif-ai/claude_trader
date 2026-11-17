"""17.11.2026: Frontend-Modellliste muss den Backend-Katalog abdecken.

Fehlte ein Modell im Frontend (GPT-6 Luna Pro, Claude Haiku 5.5, DeepSeek V4.1 Flash),
zeigte das KI-Team „Haupt-Modell (erben)“/„keine“, obwohl die Rolle das Modell nutzte."""
import re
from pathlib import Path

from services import ai_providers as ap

FE = Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "aiModels.js"


def _frontend_models():
    return set(re.findall(r"provider: '([a-z]+)', model: '([^']+)'", FE.read_text(encoding="utf-8")))


def test_frontend_lists_every_backend_model():
    fe = _frontend_models()
    be = {(p, m) for p, ms in ap.ALLOWED_MODELS.items() for m in ms}
    assert be <= fe, f"im Frontend fehlen: {sorted(be - fe)}"


def test_frontend_offers_no_migrated_dead_model():
    fe = {m for _, m in _frontend_models()}
    assert not fe & set(ap.MODEL_MIGRATIONS), sorted(fe & set(ap.MODEL_MIGRATIONS))


def test_role_presets_use_catalog_models():
    from services.ai_roles import ROLE_PRESETS
    for role, cfg in ROLE_PRESETS.items():
        for prefix in ("", "fallback_", "fallback2_"):
            prov, model = cfg.get(f"{prefix}provider"), cfg.get(f"{prefix}model")
            if model:
                assert model in ap.ALLOWED_MODELS.get(prov, []), (role, prefix, prov, model)
