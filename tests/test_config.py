def test_glm_ocr_settings_present():
    from backend.config import get_settings
    get_settings.cache_clear()
    settings = get_settings()
    assert hasattr(settings, "GLM_OCR_ENABLED")
    assert hasattr(settings, "GLM_OCR_MODEL")
    assert settings.GLM_OCR_ENABLED is True
    assert settings.GLM_OCR_MODEL == "glm-ocr"
    assert not hasattr(settings, "PADDLEOCR_ENABLED")
