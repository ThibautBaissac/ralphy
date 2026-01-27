"""Tests for the config module."""

import tempfile
from pathlib import Path

import pytest

from ralphy.config import (
    ALLOWED_MODELS,
    ModelConfig,
    ProjectConfig,
    StackConfig,
    TimeoutConfig,
    ensure_feature_dir,
    ensure_ralph_dir,
    get_feature_dir,
    load_config,
    save_config,
    validate_model,
)


class TestModelConfig:
    """Tests for ModelConfig."""

    def test_default_values(self):
        """Tests default values."""
        config = ModelConfig()
        assert config.specification == "sonnet"
        assert config.implementation == "sonnet"
        assert config.qa == "sonnet"
        assert config.pr == "sonnet"


class TestValidateModel:
    """Tests for validate_model()."""

    def test_valid_alias_models(self):
        """Tests that valid aliases are accepted."""
        assert validate_model("sonnet") == "sonnet"
        assert validate_model("opus") == "opus"
        assert validate_model("haiku") == "haiku"

    def test_valid_full_model_names(self):
        """Tests that valid full model names are accepted."""
        assert validate_model("claude-sonnet-4-5-20250929") == "claude-sonnet-4-5-20250929"
        assert validate_model("claude-opus-4-5-20251101") == "claude-opus-4-5-20251101"
        assert validate_model("claude-haiku-4-5-20251001") == "claude-haiku-4-5-20251001"

    def test_invalid_model_falls_back_to_sonnet(self):
        """Tests that invalid model returns sonnet with warning."""
        assert validate_model("invalid-model") == "sonnet"
        assert validate_model("gpt-4") == "sonnet"
        assert validate_model("claude-unknown-version") == "sonnet"

    def test_empty_string_falls_back_to_sonnet(self):
        """Tests that empty string returns sonnet."""
        assert validate_model("") == "sonnet"

    def test_all_allowed_models_are_valid(self):
        """Tests that all whitelisted models are valid."""
        for model in ALLOWED_MODELS:
            assert validate_model(model) == model


class TestTimeoutConfig:
    """Tests for TimeoutConfig."""

    def test_default_values(self):
        """Tests default values."""
        config = TimeoutConfig()
        assert config.specification == 1800
        assert config.implementation == 14400
        assert config.qa == 1800
        assert config.pr == 600
        assert config.agent == 300


class TestStackConfig:
    """Tests for StackConfig."""

    def test_default_values(self):
        """Tests default values."""
        config = StackConfig()
        assert config.language == "typescript"
        assert config.test_command == "npm test"


class TestProjectConfig:
    """Tests for ProjectConfig."""

    def test_default_values(self):
        """Test des valeurs par défaut."""
        config = ProjectConfig()
        assert config.name == "my-project"
        assert config.stack.language == "typescript"
        assert config.stack.test_command == "npm test"

    def test_from_dict(self):
        """Test de création depuis un dictionnaire."""
        data = {
            "project": {"name": "test-project"},
            "stack": {"language": "python", "test_command": "pytest"},
            "timeouts": {"specification": 600},
            "models": {"implementation": "opus", "pr": "haiku"},
        }
        config = ProjectConfig.from_dict(data)
        assert config.name == "test-project"
        assert config.stack.language == "python"
        assert config.timeouts.specification == 600
        # Valeurs par défaut pour les non-spécifiées
        assert config.timeouts.implementation == 14400
        # Valeurs des modèles
        assert config.models.implementation == "opus"
        assert config.models.pr == "haiku"
        # Valeurs par défaut pour modèles non-spécifiés
        assert config.models.specification == "sonnet"
        assert config.models.qa == "sonnet"

    def test_to_dict(self):
        """Test de conversion en dictionnaire."""
        config = ProjectConfig(
            name="my-app",
            stack=StackConfig(language="go", test_command="go test"),
            models=ModelConfig(implementation="opus", pr="haiku"),
        )
        data = config.to_dict()
        assert data["project"]["name"] == "my-app"
        assert data["stack"]["language"] == "go"
        assert data["models"]["implementation"] == "opus"
        assert data["models"]["pr"] == "haiku"
        assert data["models"]["specification"] == "sonnet"


class TestConfigIO:
    """Tests pour les fonctions I/O de config."""

    @pytest.fixture
    def temp_project(self):
        """Crée un projet temporaire."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_load_missing_config(self, temp_project):
        """Test du chargement sans fichier config."""
        config = load_config(temp_project)
        assert config.name == "my-project"

    def test_save_and_load(self, temp_project):
        """Test de sauvegarde et chargement."""
        config = ProjectConfig(
            name="saved-project",
            stack=StackConfig(language="rust"),
        )
        save_config(temp_project, config)

        loaded = load_config(temp_project)
        assert loaded.name == "saved-project"
        assert loaded.stack.language == "rust"

    def test_ensure_ralph_dir(self, temp_project):
        """Test de création du dossier .ralphy."""
        ralph_dir = ensure_ralph_dir(temp_project)
        assert ralph_dir.exists()
        assert ralph_dir.name == ".ralphy"

    def test_get_feature_dir(self, temp_project):
        """Test du chemin du dossier feature."""
        feature_dir = get_feature_dir(temp_project, "my-feature")
        assert feature_dir == temp_project / "docs" / "features" / "my-feature"

    def test_ensure_feature_dir(self, temp_project):
        """Test de création du dossier feature."""
        feature_dir = ensure_feature_dir(temp_project, "test-feature")
        assert feature_dir.exists()
        assert feature_dir.name == "test-feature"
        assert feature_dir.parent.name == "features"
        assert feature_dir.parent.parent.name == "docs"

    def test_invalid_models_in_config_fallback_to_sonnet(self, temp_project):
        """Test qu'un modèle invalide dans le fichier config retombe sur sonnet."""
        config_path = temp_project / ".ralphy" / "config.yaml"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text("""
models:
  specification: invalid-model
  implementation: opus
  qa: sonnet
  pr: haiku
""")
        config = load_config(temp_project)
        # Invalid model should fallback to sonnet
        assert config.models.specification == "sonnet"
        # Valid models should be kept
        assert config.models.implementation == "opus"
        assert config.models.qa == "sonnet"
        assert config.models.pr == "haiku"
