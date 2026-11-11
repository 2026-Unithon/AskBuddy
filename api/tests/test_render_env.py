"""계획 9D: Parameter Store 값을 env 파일 줄로 바꾼다."""
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("render_env", Path(__file__).resolve().parents[2] / "deploy" / "render_env.py")
render_env = importlib.util.module_from_spec(spec)
spec.loader.exec_module(render_env)
P = "/askbuddy/prod/"


def test_renders_sorted_key_value_lines():
    params = [{"Name": P + "JWT_SECRET", "Value": "s3"}, {"Name": P + "DATABASE_URL", "Value": "postgresql://x"}]
    assert render_env.render(params, P) == "DATABASE_URL=postgresql://x\nJWT_SECRET=s3\n"


def test_rejects_newline_in_value():
    with pytest.raises(ValueError):
        render_env.render([{"Name": P + "A", "Value": "x\ny"}], P)


def test_rejects_name_outside_prefix_or_not_env_shaped():
    for name in ["/other/A", P + "nested/A", P + "lower"]:
        with pytest.raises(ValueError):
            render_env.render([{"Name": name, "Value": "x"}], P)


def test_empty_result_is_an_error():
    with pytest.raises(ValueError):
        render_env.render([], P)
