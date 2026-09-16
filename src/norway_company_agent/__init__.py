"""Norway company intelligence agent."""
import os
from pathlib import Path


def load_environment(env_file: Path | str | None = None) -> None:
    """Load key-value pairs from .env file into os.environ if not already set."""
    candidates = (
        [Path(env_file)] if env_file
        else [
            Path.cwd() / ".env",
            Path(__file__).resolve().parent.parent.parent / ".env",
        ]
    )
    for env_path in candidates:
        if env_path.is_file():
            try:
                for line in env_path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        k = k.strip()
                        v = v.strip().strip("'\"")
                        if k and k not in os.environ:
                            os.environ[k] = v
            except Exception:
                pass
            break


load_environment()
