"""Tests for response latency feedback (badge tiers + avg_latency_ms)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cli import _latency_badge
from german_pipeline import storage


@pytest.mark.parametrize(
    "ms, expected",
    [
        (1200, "⚡ 1.2s"),
        (1, "⚡ 0.0s"),
        (2999, "⚡ 3.0s"),
        (3000, "🕐 3.0s"),
        (4800, "🕐 4.8s"),
        (7999, "🕐 8.0s"),
        (8000, "🐢 8.0s"),
        (11300, "🐢 11.3s"),
    ],
)
def test_badge_tiers(ms, expected):
    assert _latency_badge(ms) == expected


@pytest.mark.parametrize("ms", [0, None, -5])
def test_badge_unknown_latency(ms):
    assert _latency_badge(ms) == ""


def _db():
    con = storage.connect(":memory:")
    storage.init_db(con)
    con.execute(
        "INSERT INTO vocab_items (id, de, en, source) VALUES (1, 'Hund', 'dog', 'pipeline:t')"
    )
    return con


def _add(con, correct, latency):
    con.execute(
        "INSERT INTO attempts (vocab_id, drill_type, prompt, user_answer, "
        "is_correct, error_tags, latency_ms, ts) "
        "VALUES (1, 'en_to_de', 'p', 'a', ?, '', ?, '2026-01-02T00:00:00+00:00')",
        (correct, latency),
    )


def test_avg_latency_correct_only():
    con = _db()
    _add(con, 1, 2000)
    _add(con, 1, 4000)
    _add(con, 0, 20000)  # incorrect: ignored
    _add(con, 1, 0)      # unknown: ignored
    con.commit()
    s = storage.query_stats(con, "2026-01-01T00:00:00")
    assert s["avg_latency_ms"] == pytest.approx(3000)


def test_avg_latency_none_when_no_correct():
    con = _db()
    _add(con, 0, 5000)
    con.commit()
    s = storage.query_stats(con, "2026-01-01T00:00:00")
    assert s["avg_latency_ms"] is None


def test_avg_response_line_threshold():
    from cli import _avg_response_line
    assert _avg_response_line([]) == ""
    assert _avg_response_line([1000, 2000]) == ""
    assert (
        _avg_response_line([2000, 3000, 5200])
        == "   Avg response   : 3.4s  (correct answers only)\n"
    )


def _stats_dict(avg):
    return {
        "attempts_count": 3, "near_miss_count": 0, "near_miss_rate": 0.0,
        "filter_label": "x", "vocab_count": 1, "accuracy": 1.0,
        "last_seen": "2026-01-02T00:00:00", "avg_latency_ms": avg,
    }


def test_stats_block_avg_latency(capsys):
    from cli import _print_stats_block
    _print_stats_block(_stats_dict(3400.0), 30)
    assert "   Avg latency    : 3.4s  (correct answers)" in capsys.readouterr().out
    _print_stats_block(_stats_dict(None), 30, header="📋 Practice report")
    assert "   Avg latency    : —" in capsys.readouterr().out


def test_stats_and_report_commands(tmp_path):
    from typer.testing import CliRunner
    from cli import app
    db = tmp_path / "t.db"
    con = storage.connect(db)
    storage.init_db(con)
    con.execute(
        "INSERT INTO vocab_items (id, de, en, source) VALUES (1, 'Hund', 'dog', 'pipeline:t')"
    )
    for ms in (2000, 3000, 5200):
        con.execute(
            "INSERT INTO attempts (vocab_id, drill_type, prompt, user_answer, "
            "is_correct, error_tags, latency_ms, ts) VALUES "
            "(1,'en_to_de','p','a',1,'',?,?)",
            (ms, __import__("datetime").datetime.now().isoformat(timespec="seconds")),
        )
    con.commit()
    con.close()
    for cmd in ("stats", "report"):
        r = CliRunner().invoke(app, [cmd, "--db", str(db)])
        assert r.exit_code == 0, r.output
        assert "Avg latency    : 3.4s  (correct answers)" in r.output
