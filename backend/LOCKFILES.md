# Python lockfiles

`requirements.lock` (production image) and `requirements-dev.lock` (CI tests)
pin every backend dependency to an exact version with hashes. The Docker
image and CI install from them, and CI runs `pip-audit` on
`requirements.lock`, so a dependency with a known vulnerability fails the
"Backend tests" check.

After changing `dependencies` or the `dev` extra in `pyproject.toml`, or to
pick up newer versions (for example when `pip-audit` flags one), regenerate
both files from the repo root. This runs in the same Linux Python image the
backend ships on, so the pins match production:

```
docker run --rm -v "$PWD/backend:/src" -w /src python:3.12-slim sh -c '
  pip install -q pip-tools &&
  pip-compile -q --upgrade --generate-hashes --strip-extras --allow-unsafe -o requirements.lock pyproject.toml &&
  pip-compile -q --upgrade --generate-hashes --strip-extras --allow-unsafe --extra dev -o requirements-dev.lock pyproject.toml &&
  rm -rf build *.egg-info'
```

On Windows Git Bash, prefix it with `MSYS_NO_PATHCONV=1` and use
`"$(pwd -W)/backend:/src"` for the volume. Drop `--upgrade` to change only
what `pyproject.toml` requires. Commit both lockfiles with the change.
