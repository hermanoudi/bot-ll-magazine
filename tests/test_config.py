import pytest

from productbot.config import ConfigError, interpolate_env, load_config


def test_interpolate_nested():
    out = interpolate_env({"a": ["x-${V}"], "b": {"c": "${V}"}}, {"V": "1"})
    assert out == {"a": ["x-1"], "b": {"c": "1"}}


def test_missing_env_raises():
    with pytest.raises(ConfigError, match="MISSING"):
        interpolate_env("${MISSING}", {})


def test_example_loads(app_config, site):
    assert site.base_url == "https://shop.test"
    assert site.auth.body["username"] == "bot"
    assert app_config.sites_for(123456789).keys() == {"llmagazine"}
    assert app_config.sites_for(1) == {}


def test_missing_file():
    with pytest.raises(ConfigError):
        load_config("/nope.yaml")
