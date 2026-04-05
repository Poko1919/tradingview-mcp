"""
macro_filter.py のユニットテスト

実行: pytest tests/test_macro_filter.py -v
"""

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# scripts/ をパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import macro_filter


# ──────────────────────────────────────────────
# calc_lot_multiplier
# ──────────────────────────────────────────────

class TestCalcLotMultiplier:
    def test_vix_low(self):
        mult, note = macro_filter.calc_lot_multiplier(15.0)
        assert mult == 1.0
        assert "full size" in note

    def test_vix_boundary_20(self):
        mult, _ = macro_filter.calc_lot_multiplier(20.0)
        assert mult == 1.0

    def test_vix_mid_low(self):
        mult, note = macro_filter.calc_lot_multiplier(22.0)
        assert mult == 0.75
        assert "75%" in note

    def test_vix_boundary_25(self):
        mult, _ = macro_filter.calc_lot_multiplier(25.0)
        assert mult == 0.75

    def test_vix_mid_high(self):
        mult, note = macro_filter.calc_lot_multiplier(27.5)
        assert mult == 0.5
        assert "50%" in note

    def test_vix_boundary_30(self):
        mult, _ = macro_filter.calc_lot_multiplier(30.0)
        assert mult == 0.5

    def test_vix_extreme(self):
        mult, note = macro_filter.calc_lot_multiplier(35.0)
        assert mult == 0.25
        assert "25%" in note

    def test_vix_very_extreme(self):
        mult, _ = macro_filter.calc_lot_multiplier(80.0)
        assert mult == 0.25


# ──────────────────────────────────────────────
# build_payload
# ──────────────────────────────────────────────

class TestBuildPayload:
    def test_normal(self):
        payload = macro_filter.build_payload(18.0, 103.5)
        assert payload["vix"] == 18.0
        assert payload["dxy"] == 103.5
        assert payload["lot_multiplier"] == 1.0
        assert "timestamp" in payload
        assert "note" in payload

    def test_vix_none_uses_conservative(self):
        payload = macro_filter.build_payload(None, 103.5)
        assert payload["vix"] is None
        assert payload["lot_multiplier"] == 0.5
        assert "unavailable" in payload["note"]

    def test_dxy_none_is_ok(self):
        payload = macro_filter.build_payload(22.0, None)
        assert payload["dxy"] is None
        assert payload["lot_multiplier"] == 0.75

    def test_rounding(self):
        payload = macro_filter.build_payload(18.123456, 103.999)
        assert payload["vix"] == 18.12
        assert payload["dxy"] == 104.0


# ──────────────────────────────────────────────
# write_json
# ──────────────────────────────────────────────

class TestWriteJson:
    def test_writes_valid_json(self, tmp_path):
        output = tmp_path / "macro_filter.json"
        payload = {"lot_multiplier": 0.75, "vix": 22.0, "dxy": 103.5, "timestamp": "2026-01-01T00:00:00Z", "note": "test"}
        macro_filter.write_json(payload, output)
        data = json.loads(output.read_text())
        assert data["lot_multiplier"] == 0.75
        assert data["vix"] == 22.0

    def test_dry_run_does_not_write(self, tmp_path):
        output = tmp_path / "macro_filter.json"
        payload = {"lot_multiplier": 1.0, "vix": 18.0, "dxy": 103.0, "timestamp": "2026-01-01T00:00:00Z", "note": "test"}
        macro_filter.write_json(payload, output, dry_run=True)
        assert not output.exists()

    def test_creates_parent_dirs(self, tmp_path):
        output = tmp_path / "deep" / "nested" / "macro_filter.json"
        payload = {"lot_multiplier": 0.5, "vix": 27.0, "dxy": 102.0, "timestamp": "2026-01-01T00:00:00Z", "note": "test"}
        macro_filter.write_json(payload, output)
        assert output.exists()


# ──────────────────────────────────────────────
# fetch_via_study_values
# ──────────────────────────────────────────────

class TestFetchViaStudyValues:
    def test_returns_value_when_found(self):
        mock_response = {
            "success": True,
            "study_count": 1,
            "studies": [{"name": "VIX", "values": {"Value": "18.50"}}],
        }
        with patch.object(macro_filter, "run_tv", return_value=mock_response):
            result = macro_filter.fetch_via_study_values("VIX")
        assert result == 18.50

    def test_returns_none_when_empty(self):
        mock_response = {"success": True, "study_count": 0, "studies": []}
        with patch.object(macro_filter, "run_tv", return_value=mock_response):
            result = macro_filter.fetch_via_study_values("VIX")
        assert result is None

    def test_returns_none_on_tv_failure(self):
        with patch.object(macro_filter, "run_tv", return_value=None):
            result = macro_filter.fetch_via_study_values("VIX")
        assert result is None

    def test_handles_comma_in_number(self):
        mock_response = {
            "success": True,
            "study_count": 1,
            "studies": [{"name": "DXY", "values": {"Value": "1,034.50"}}],
        }
        with patch.object(macro_filter, "run_tv", return_value=mock_response):
            result = macro_filter.fetch_via_study_values("DXY")
        assert result == 1034.50


# ──────────────────────────────────────────────
# run_once (統合)
# ──────────────────────────────────────────────

class TestRunOnce:
    def test_writes_json_with_mocked_tv(self, tmp_path):
        output = tmp_path / "macro_filter.json"

        def fake_run_tv(args, timeout=15):
            if "values" in args:
                filter_val = args[args.index("--filter") + 1] if "--filter" in args else ""
                if "VIX" in filter_val:
                    return {"success": True, "study_count": 1, "studies": [{"name": "VIX", "values": {"Value": "19.80"}}]}
                if "DXY" in filter_val:
                    return {"success": True, "study_count": 1, "studies": [{"name": "DXY", "values": {"Value": "103.20"}}]}
            return None

        with patch.object(macro_filter, "run_tv", side_effect=fake_run_tv):
            payload = macro_filter.run_once(output)

        data = json.loads(output.read_text())
        assert data["vix"] == 19.80
        assert data["dxy"] == 103.20
        assert data["lot_multiplier"] == 1.0

    def test_falls_back_when_tv_unavailable(self, tmp_path):
        output = tmp_path / "macro_filter.json"
        with patch.object(macro_filter, "run_tv", return_value=None):
            with patch.object(macro_filter, "fetch_via_symbol_switch", return_value=None):
                payload = macro_filter.run_once(output)

        assert payload["vix"] is None
        assert payload["lot_multiplier"] == 0.5

    def test_push_windows_called_when_flag_set(self, tmp_path):
        output = tmp_path / "macro_filter.json"
        with patch.object(macro_filter, "run_tv", return_value=None):
            with patch.object(macro_filter, "fetch_via_symbol_switch", return_value=None):
                with patch.object(macro_filter, "push_to_windows", return_value=True) as mock_push:
                    macro_filter.run_once(output, push_windows=True)
        mock_push.assert_called_once()

    def test_push_windows_not_called_by_default(self, tmp_path):
        output = tmp_path / "macro_filter.json"
        with patch.object(macro_filter, "run_tv", return_value=None):
            with patch.object(macro_filter, "fetch_via_symbol_switch", return_value=None):
                with patch.object(macro_filter, "push_to_windows", return_value=True) as mock_push:
                    macro_filter.run_once(output)
        mock_push.assert_not_called()


# ──────────────────────────────────────────────
# push_to_windows
# ──────────────────────────────────────────────

class TestPushToWindows:
    def test_dry_run_returns_true(self):
        result = macro_filter.push_to_windows('{"lot_multiplier": 1.0}', dry_run=True)
        assert result is True

    def test_connection_error_returns_false(self):
        import urllib.error
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("connection refused")):
            result = macro_filter.push_to_windows('{"lot_multiplier": 1.0}')
        assert result is False

    def test_nonzero_returncode_returns_false(self):
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({"returncode": 1, "stderr": "error"}).encode()
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=mock_response):
            result = macro_filter.push_to_windows('{"lot_multiplier": 1.0}')
        assert result is False

    def test_success_returns_true(self):
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({"returncode": 0, "stdout": ""}).encode()
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=mock_response):
            result = macro_filter.push_to_windows('{"lot_multiplier": 1.0}')
        assert result is True
