"""Server log lines must always be valid JSON, whatever the message contains."""
import json
import logging
import sys

from infrawatch_server.main import JsonFormatter


def _record(msg, *args, exc_info=None):
    return logging.LogRecord("infrawatch.test", logging.WARNING, __file__, 1, msg, args, exc_info)


def test_hostile_messages_parse_as_json():
    f = JsonFormatter()
    for msg in ['failed: "quoted" value', "line1\nline2", "back\\slash \t tab", "unicode ☃ \x00"]:
        d = json.loads(f.format(_record(msg)))
        assert d["msg"] == msg
        assert d["level"] == "WARNING" and d["logger"] == "infrawatch.test"


def test_args_are_interpolated():
    assert json.loads(JsonFormatter().format(_record('x "%s"', "y")))["msg"] == 'x "y"'


def test_exception_info_included():
    try:
        raise ValueError('bad "thing"\nhere')
    except ValueError:
        d = json.loads(JsonFormatter().format(_record("boom", exc_info=sys.exc_info())))
    assert "ValueError" in d["exc"]
