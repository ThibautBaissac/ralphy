"""Tests pour le module validation."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ralphy.validation import HumanValidator, ValidationResult


class TestValidationResult:
    """Tests pour ValidationResult."""

    def test_approved_result(self):
        """Test d'un résultat approuvé."""
        result = ValidationResult(approved=True)
        assert result.approved is True
        assert result.comment is None

    def test_rejected_result(self):
        """Test d'un résultat rejeté."""
        result = ValidationResult(approved=False)
        assert result.approved is False
        assert result.comment is None

    def test_result_with_comment(self):
        """Test d'un résultat avec commentaire."""
        result = ValidationResult(approved=False, comment="Need more tests")
        assert result.approved is False
        assert result.comment == "Need more tests"


class TestHumanValidator:
    """Tests pour HumanValidator."""

    @pytest.fixture
    def validator(self):
        """Crée un validateur avec console mockée."""
        console = MagicMock()
        return HumanValidator(console=console)

    @pytest.fixture
    def temp_feature_dir(self):
        """Crée un répertoire feature temporaire."""
        with tempfile.TemporaryDirectory() as tmpdir:
            feature_dir = Path(tmpdir)
            yield feature_dir

    def test_request_validation_approved(self, validator):
        """Test de validation approuvée."""
        with patch("ralphy.validation.Confirm.ask", return_value=True):
            result = validator.request_validation(
                title="Test",
                files_generated=["file1.md", "file2.md"],
            )
            assert result.approved is True

    def test_request_validation_rejected(self, validator):
        """Test de validation rejetée."""
        with patch("ralphy.validation.Confirm.ask", return_value=False):
            result = validator.request_validation(
                title="Test",
                files_generated=["file1.md"],
            )
            assert result.approved is False

    def test_request_validation_with_summary(self, validator):
        """Test de validation avec résumé."""
        with patch("ralphy.validation.Confirm.ask", return_value=True):
            result = validator.request_validation(
                title="Test",
                files_generated=["file.md"],
                summary="This is a summary",
            )
            assert result.approved is True
            # Verify console.print was called with a Panel
            validator.console.print.assert_called()

    def test_request_validation_without_summary(self, validator):
        """Test de validation sans résumé."""
        with patch("ralphy.validation.Confirm.ask", return_value=True):
            result = validator.request_validation(
                title="Test",
                files_generated=["file.md"],
                summary=None,
            )
            assert result.approved is True

    def test_request_spec_validation_with_existing_spec(
        self, validator, temp_feature_dir
    ):
        """Test de validation spec avec SPEC.md existant."""
        # Create SPEC.md with content
        spec_content = "# Specification\n\nThis is the spec content.\n\n## Overview"
        spec_path = temp_feature_dir / "SPEC.md"
        spec_path.write_text(spec_content, encoding="utf-8")

        with patch("ralphy.validation.Confirm.ask", return_value=True):
            result = validator.request_spec_validation(
                feature_dir=temp_feature_dir,
                tasks_count=5,
            )
            assert result.approved is True

    def test_request_spec_validation_without_spec_file(
        self, validator, temp_feature_dir
    ):
        """Test de validation spec sans fichier SPEC.md."""
        with patch("ralphy.validation.Confirm.ask", return_value=True):
            result = validator.request_spec_validation(
                feature_dir=temp_feature_dir,
                tasks_count=3,
            )
            assert result.approved is True

    def test_request_spec_validation_files_generated_format(
        self, validator, temp_feature_dir
    ):
        """Test que les fichiers générés incluent le compte des tâches."""
        with patch("ralphy.validation.Confirm.ask", return_value=True):
            with patch.object(
                validator, "request_validation", wraps=validator.request_validation
            ) as mock_request:
                validator.request_spec_validation(
                    feature_dir=temp_feature_dir,
                    tasks_count=7,
                )
                # Verify request_validation was called with correct files
                call_args = mock_request.call_args
                files_generated = call_args.kwargs.get(
                    "files_generated"
                ) or call_args.args[1]
                assert "SPEC.md" in files_generated
                assert any("7 tâches" in f for f in files_generated)

    def test_request_qa_validation_approved(self, validator, temp_feature_dir):
        """Test de validation QA approuvée."""
        qa_summary = {"score": "8/10", "critical_issues": 2}

        with patch("ralphy.validation.Confirm.ask", return_value=True):
            result = validator.request_qa_validation(
                feature_dir=temp_feature_dir,
                qa_summary=qa_summary,
            )
            assert result.approved is True

    def test_request_qa_validation_rejected(self, validator, temp_feature_dir):
        """Test de validation QA rejetée."""
        qa_summary = {"score": "3/10", "critical_issues": 15}

        with patch("ralphy.validation.Confirm.ask", return_value=False):
            result = validator.request_qa_validation(
                feature_dir=temp_feature_dir,
                qa_summary=qa_summary,
            )
            assert result.approved is False

    def test_request_qa_validation_with_missing_summary_keys(
        self, validator, temp_feature_dir
    ):
        """Test de validation QA avec clés de résumé manquantes."""
        qa_summary = {}  # Empty dict, should use defaults

        with patch("ralphy.validation.Confirm.ask", return_value=True):
            result = validator.request_qa_validation(
                feature_dir=temp_feature_dir,
                qa_summary=qa_summary,
            )
            assert result.approved is True

    def test_request_qa_validation_summary_format(self, validator, temp_feature_dir):
        """Test du format du résumé QA."""
        qa_summary = {"score": "9/10", "critical_issues": 0}

        with patch("ralphy.validation.Confirm.ask", return_value=True):
            with patch.object(
                validator, "request_validation", wraps=validator.request_validation
            ) as mock_request:
                validator.request_qa_validation(
                    feature_dir=temp_feature_dir,
                    qa_summary=qa_summary,
                )
                call_args = mock_request.call_args
                summary = call_args.kwargs.get("summary") or call_args.args[2]
                assert "9/10" in summary
                assert "0" in summary


class TestHumanValidatorEdgeCases:
    """Tests pour les cas limites de HumanValidator."""

    @pytest.fixture
    def temp_feature_dir(self):
        """Crée un répertoire feature temporaire."""
        with tempfile.TemporaryDirectory() as tmpdir:
            feature_dir = Path(tmpdir)
            yield feature_dir

    def test_spec_validation_with_long_spec_file(self, temp_feature_dir):
        """Test avec un fichier SPEC.md très long."""
        # Create a long SPEC.md
        lines = ["# Line " + str(i) for i in range(1000)]
        spec_content = "\n".join(lines)
        spec_path = temp_feature_dir / "SPEC.md"
        spec_path.write_text(spec_content, encoding="utf-8")

        validator = HumanValidator(console=MagicMock())
        with patch("ralphy.validation.Confirm.ask", return_value=True):
            result = validator.request_spec_validation(
                feature_dir=temp_feature_dir,
                tasks_count=10,
            )
            assert result.approved is True

    def test_spec_validation_with_unicode_content(self, temp_feature_dir):
        """Test avec contenu Unicode dans SPEC.md."""
        spec_content = "# Spécification 日本語\n\nContenu avec émojis 🚀 et accents éèà"
        spec_path = temp_feature_dir / "SPEC.md"
        spec_path.write_text(spec_content, encoding="utf-8")

        validator = HumanValidator(console=MagicMock())
        with patch("ralphy.validation.Confirm.ask", return_value=True):
            result = validator.request_spec_validation(
                feature_dir=temp_feature_dir,
                tasks_count=5,
            )
            assert result.approved is True

    def test_validation_with_empty_files_list(self):
        """Test de validation avec liste de fichiers vide."""
        validator = HumanValidator(console=MagicMock())
        with patch("ralphy.validation.Confirm.ask", return_value=True):
            result = validator.request_validation(
                title="Test",
                files_generated=[],
            )
            assert result.approved is True

    def test_qa_validation_with_none_values_in_summary(self, temp_feature_dir):
        """Test de validation QA avec valeurs None dans le résumé."""
        qa_summary = {"score": None, "critical_issues": None}

        validator = HumanValidator(console=MagicMock())
        with patch("ralphy.validation.Confirm.ask", return_value=True):
            # Should not raise, should use defaults
            result = validator.request_qa_validation(
                feature_dir=temp_feature_dir,
                qa_summary=qa_summary,
            )
            assert result.approved is True


class TestHumanValidatorNonInteractive:
    """Tests pour HumanValidator en mode non-interactif."""

    def test_eof_error_handling(self):
        """Test de gestion EOFError en environnement non-interactif."""
        validator = HumanValidator(console=MagicMock())

        # Simulate non-interactive environment (CI/CD)
        with patch("ralphy.validation.Confirm.ask", side_effect=EOFError):
            with pytest.raises(EOFError):
                validator.request_validation(
                    title="Test",
                    files_generated=["file.md"],
                )

    def test_keyboard_interrupt_handling(self):
        """Test de gestion KeyboardInterrupt."""
        validator = HumanValidator(console=MagicMock())

        with patch("ralphy.validation.Confirm.ask", side_effect=KeyboardInterrupt):
            with pytest.raises(KeyboardInterrupt):
                validator.request_validation(
                    title="Test",
                    files_generated=["file.md"],
                )
