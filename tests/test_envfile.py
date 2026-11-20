from studio.envfile import load_openai_api_key, read_openai_key, write_openai_key


def test_env_file_round_trip_and_missing(tmp_path):
    assert read_openai_key(tmp_path) == ""
    write_openai_key(tmp_path, "sk-test-local-only")
    assert read_openai_key(tmp_path) == "sk-test-local-only"


def test_process_env_is_read_before_file(tmp_path, monkeypatch):
    write_openai_key(tmp_path, "from-file")
    monkeypatch.setenv("OPENAI_API_KEY", "from-process")
    assert load_openai_api_key(tmp_path) == "from-process"


def test_file_is_read_when_process_env_is_absent(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    write_openai_key(tmp_path, "from-file")
    assert load_openai_api_key(tmp_path) == "from-file"
