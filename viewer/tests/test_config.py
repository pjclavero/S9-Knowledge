from app.config import Settings


def test_settings_default_provider_is_mock():
    settings = Settings(_env_file=None)
    assert settings.S9K_GRAPH_PROVIDER == "mock"
    assert settings.S9K_DEFAULT_WORKSPACE == "leyenda"
    assert settings.S9K_VIEWER_PORT == 8088


def test_neo4j_password_falls_back_to_direct_value_when_no_file():
    settings = Settings(_env_file=None, S9K_NEO4J_PASSWORD="secreto", S9K_NEO4J_PASSWORD_FILE="")
    assert settings.neo4j_password == "secreto"
