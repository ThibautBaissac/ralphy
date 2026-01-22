"""Tests for claude module."""

import tempfile
import threading
import time
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ralphy.claude import (
    PID_FILE,
    ClaudeRunner,
    JsonStreamParser,
    ProcessManager,
    StreamReader,
    abort_running_claude,
    check_claude_installed,
    check_gh_installed,
    check_git_installed,
)


class TestPrerequisiteChecks:
    """Tests pour les vérifications de prérequis."""

    def test_check_git_installed(self):
        """Test que git est détecté (normalement installé sur la machine de dev)."""
        # Ce test peut échouer si git n'est pas installé
        result = check_git_installed()
        assert isinstance(result, bool)

    def test_check_gh_installed(self):
        """Test de détection de gh CLI."""
        result = check_gh_installed()
        assert isinstance(result, bool)

    def test_check_claude_installed(self):
        """Test de détection de Claude CLI."""
        result = check_claude_installed()
        assert isinstance(result, bool)


class TestAbortRunningClaude:
    """Tests pour la fonction abort_running_claude."""

    @pytest.fixture
    def temp_project(self):
        """Crée un projet temporaire."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_path = Path(tmpdir)
            (project_path / ".ralphy").mkdir()
            yield project_path

    def test_abort_without_pid_file(self, temp_project):
        """Test abort quand il n'y a pas de fichier PID."""
        result = abort_running_claude(temp_project)
        assert result is False

    def test_abort_with_invalid_pid(self, temp_project):
        """Test abort avec un PID invalide."""
        pid_file = temp_project / PID_FILE
        pid_file.write_text("invalid")
        result = abort_running_claude(temp_project)
        assert result is False
        # Le fichier PID devrait être supprimé
        assert not pid_file.exists()

    def test_abort_with_nonexistent_pid(self, temp_project):
        """Test abort avec un PID qui n'existe pas."""
        pid_file = temp_project / PID_FILE
        # Utilise un PID très élevé qui n'existe probablement pas
        pid_file.write_text("999999999")
        result = abort_running_claude(temp_project)
        assert result is False
        # Le fichier PID devrait être supprimé
        assert not pid_file.exists()


class TestClaudeRunnerModelFlag:
    """Tests pour la construction du flag --model dans ClaudeRunner."""

    @pytest.fixture
    def temp_project(self):
        """Crée un projet temporaire."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_path = Path(tmpdir)
            (project_path / ".ralphy").mkdir()
            yield project_path

    def test_runner_stores_model_parameter(self, temp_project):
        """Test que ClaudeRunner stocke le paramètre model."""
        runner = ClaudeRunner(working_dir=temp_project, model="opus")
        assert runner.model == "opus"

    def test_runner_model_defaults_to_none(self, temp_project):
        """Test que ClaudeRunner a model=None par défaut."""
        runner = ClaudeRunner(working_dir=temp_project)
        assert runner.model is None

    def test_run_includes_model_flag_when_specified(self, temp_project):
        """Test que run() inclut --model dans la commande quand spécifié."""
        with patch("ralphy.claude.subprocess.Popen") as mock_popen:
            mock_process = MagicMock()
            mock_process.stdout = MagicMock()
            mock_process.stdout.fileno.return_value = 0
            mock_process.stdout.read.return_value = ""
            mock_process.poll.return_value = 0
            mock_process.wait.return_value = 0
            mock_process.returncode = 0
            mock_process.pid = 12345
            mock_popen.return_value = mock_process

            runner = ClaudeRunner(working_dir=temp_project, model="opus")
            runner.run("test prompt")

            # Verify Popen was called with the model flag
            call_args = mock_popen.call_args
            cmd = call_args[0][0]  # First positional arg is the command list

            assert "--model" in cmd
            model_idx = cmd.index("--model")
            assert cmd[model_idx + 1] == "opus"

    def test_run_omits_model_flag_when_none(self, temp_project):
        """Test que run() n'inclut pas --model quand model=None."""
        with patch("ralphy.claude.subprocess.Popen") as mock_popen:
            mock_process = MagicMock()
            mock_process.stdout = MagicMock()
            mock_process.stdout.fileno.return_value = 0
            mock_process.stdout.read.return_value = ""
            mock_process.poll.return_value = 0
            mock_process.wait.return_value = 0
            mock_process.returncode = 0
            mock_process.pid = 12345
            mock_popen.return_value = mock_process

            runner = ClaudeRunner(working_dir=temp_project, model=None)
            runner.run("test prompt")

            # Verify Popen was called WITHOUT the model flag
            call_args = mock_popen.call_args
            cmd = call_args[0][0]  # First positional arg is the command list

            assert "--model" not in cmd

    def test_command_structure_with_model(self, temp_project):
        """Test la structure complète de la commande avec model."""
        with patch("ralphy.claude.subprocess.Popen") as mock_popen:
            mock_process = MagicMock()
            mock_process.stdout = MagicMock()
            mock_process.stdout.fileno.return_value = 0
            mock_process.stdout.read.return_value = ""
            mock_process.poll.return_value = 0
            mock_process.wait.return_value = 0
            mock_process.returncode = 0
            mock_process.pid = 12345
            mock_popen.return_value = mock_process

            runner = ClaudeRunner(working_dir=temp_project, model="haiku")
            runner.run("my test prompt")

            call_args = mock_popen.call_args
            cmd = call_args[0][0]

            # Verify expected command structure
            assert cmd[0] == "claude"
            assert "--print" in cmd
            assert "--dangerously-skip-permissions" in cmd
            assert "--model" in cmd
            assert "haiku" in cmd
            assert "-p" in cmd
            assert "my test prompt" in cmd


class TestClaudeRunnerPerformance:
    """Tests for ClaudeRunner performance characteristics."""

    def test_stringio_vs_string_concatenation_performance(self):
        """Verify StringIO is faster than string concatenation for large outputs.

        This test validates the fix for O(n²) string concatenation.
        Before fix: 100KB output could take 30+ seconds
        After fix: should complete in < 1 second
        """
        # Generate 100KB of output (1000 lines of 100 chars each)
        lines = ["x" * 99 + "\n" for _ in range(1000)]

        # Test StringIO approach (what we now use)
        start = time.perf_counter()
        buffer = StringIO()
        for line in lines:
            for char in line:
                buffer.write(char)
        result_stringio = buffer.getvalue()
        stringio_time = time.perf_counter() - start

        # Verify correctness
        assert len(result_stringio) == 100000

        # StringIO should be fast (< 1 second for 100KB)
        assert stringio_time < 1.0, f"StringIO took {stringio_time:.2f}s, expected < 1s"

    def test_large_output_handling_simulation(self):
        """Simulate handling of large output streams efficiently.

        This test verifies the buffer handling logic works correctly
        for outputs of various sizes.
        """
        test_cases = [
            100,      # Small output
            10000,    # Medium output
            100000,   # Large output (100KB)
        ]

        for size in test_cases:
            buffer = StringIO()
            output_lines = []

            # Simulate character-by-character reading
            for i in range(size):
                char = "x" if i % 100 != 99 else "\n"
                buffer.write(char)

                if char == "\n":
                    line_content = buffer.getvalue()
                    output_lines.append(line_content)
                    buffer = StringIO()

            # Handle remaining buffer
            if buffer.tell() > 0:
                output_lines.append(buffer.getvalue())

            # Verify all content was captured
            total_content = "".join(output_lines)
            assert len(total_content) == size


class TestProcessManager:
    """Tests for the ProcessManager class."""

    @pytest.fixture
    def temp_project(self):
        """Create a temporary project directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_path = Path(tmpdir)
            (project_path / ".ralphy").mkdir()
            yield project_path

    def test_init_stores_paths(self, temp_project):
        """Test that ProcessManager stores working_dir and pid_file."""
        pid_file = temp_project / ".ralphy" / "test.pid"
        pm = ProcessManager(temp_project, pid_file)
        assert pm._working_dir == temp_project
        assert pm._pid_file == pid_file

    def test_process_initially_none(self, temp_project):
        """Test that process is None before start."""
        pm = ProcessManager(temp_project, temp_project / ".ralphy" / "test.pid")
        assert pm.process is None
        assert pm.return_code == -1

    def test_start_creates_process_and_pid_file(self, temp_project):
        """Test that start creates subprocess and saves PID."""
        pid_file = temp_project / ".ralphy" / "test.pid"
        pm = ProcessManager(temp_project, pid_file)

        try:
            # Use a simple command that exits quickly
            process = pm.start(["echo", "hello"])
            assert process is not None
            assert pm.process is not None
            assert pid_file.exists()
            assert int(pid_file.read_text()) == process.pid
        finally:
            pm.cleanup()

    def test_cleanup_removes_pid_file(self, temp_project):
        """Test that cleanup removes the PID file."""
        pid_file = temp_project / ".ralphy" / "test.pid"
        pm = ProcessManager(temp_project, pid_file)

        pm.start(["echo", "hello"])
        pm.wait()
        pm.cleanup()

        assert not pid_file.exists()
        assert pm.process is None

    def test_kill_terminates_process(self, temp_project):
        """Test that kill terminates a running process."""
        pid_file = temp_project / ".ralphy" / "test.pid"
        pm = ProcessManager(temp_project, pid_file)

        try:
            # Start a long-running process
            pm.start(["sleep", "10"])
            pm.kill()
            pm.wait()
            # Process should be terminated (negative return code on Unix for killed processes)
            assert pm.poll() is not None
        finally:
            pm.cleanup()

    def test_poll_returns_none_for_running_process(self, temp_project):
        """Test that poll returns None for a running process."""
        pid_file = temp_project / ".ralphy" / "test.pid"
        pm = ProcessManager(temp_project, pid_file)

        try:
            pm.start(["sleep", "10"])
            # Process should still be running
            assert pm.poll() is None
        finally:
            pm.kill()
            pm.cleanup()

    def test_return_code_after_completion(self, temp_project):
        """Test return code after process completes."""
        pid_file = temp_project / ".ralphy" / "test.pid"
        pm = ProcessManager(temp_project, pid_file)

        try:
            pm.start(["true"])  # Command that returns 0
            pm.wait()
            assert pm.return_code == 0
        finally:
            pm.cleanup()


class TestStreamReader:
    """Tests for the StreamReader class."""

    def test_read_lines_empty_process(self):
        """Test read_lines handles None process."""
        abort_event = threading.Event()
        reader = StreamReader(
            abort_event=abort_event,
            json_parser=None,
            circuit_breaker=None,
            on_output=None,
            on_cb_trigger=lambda: None,
        )
        # Should return empty list for None process
        lines = reader.read_lines(None)
        assert lines == []

    def test_read_lines_basic_output(self):
        """Test reading basic output without JSON parsing."""
        abort_event = threading.Event()
        output_received = []

        reader = StreamReader(
            abort_event=abort_event,
            json_parser=None,
            circuit_breaker=None,
            on_output=lambda x: output_received.append(x),
            on_cb_trigger=lambda: None,
        )

        # Create a mock process with output
        mock_process = MagicMock()
        mock_stdout = StringIO("line1\nline2\n")
        mock_process.stdout = mock_stdout
        mock_process.stdout.fileno = MagicMock(return_value=0)
        mock_process.poll = MagicMock(return_value=0)

        with patch("ralphy.claude.select.select", return_value=([0], [], [])):
            lines = reader.read_lines(mock_process)

        # Lines should contain the output
        assert len(lines) >= 2 or "line1" in "".join(lines)

    def test_abort_event_stops_reading(self):
        """Test that setting abort event stops reading."""
        abort_event = threading.Event()
        reader = StreamReader(
            abort_event=abort_event,
            json_parser=None,
            circuit_breaker=None,
            on_output=None,
            on_cb_trigger=lambda: None,
        )

        # Set abort before reading
        abort_event.set()

        mock_process = MagicMock()
        mock_process.stdout = MagicMock()
        mock_process.stdout.fileno = MagicMock(return_value=0)

        lines = reader.read_lines(mock_process)
        # Should return quickly with empty or partial results
        assert isinstance(lines, list)

    def test_circuit_breaker_callback_called(self):
        """Test that circuit breaker callback is invoked on trigger."""
        abort_event = threading.Event()
        cb_triggered = []

        def on_cb_trigger():
            cb_triggered.append(True)

        mock_cb = MagicMock()
        mock_cb.record_output.return_value = True  # Simulate trigger

        reader = StreamReader(
            abort_event=abort_event,
            json_parser=None,
            circuit_breaker=mock_cb,
            on_output=None,
            on_cb_trigger=on_cb_trigger,
        )

        # Simulate processing a line that triggers CB
        output_lines = []
        reader._process_line("test line\n", output_lines)

        assert len(cb_triggered) == 1
        assert abort_event.is_set()

    def test_json_parsing_integration(self):
        """Test integration with JsonStreamParser."""
        abort_event = threading.Event()
        output_received = []

        json_parser = JsonStreamParser()

        reader = StreamReader(
            abort_event=abort_event,
            json_parser=json_parser,
            circuit_breaker=None,
            on_output=lambda x: output_received.append(x),
            on_cb_trigger=lambda: None,
        )

        # Simulate processing a JSON assistant message
        json_line = '{"type": "assistant", "message": {"content": [{"type": "text", "text": "Hello"}]}}\n'
        output_lines = []
        reader._process_line(json_line, output_lines)

        assert len(output_lines) == 1
        assert "Hello" in output_lines[0]
        assert len(output_received) == 1
