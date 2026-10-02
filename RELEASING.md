# Releasing

What a release must deliver and how each channel is checked: [DEPLOY_CONTRACT.md](DEPLOY_CONTRACT.md).

1. Update `version` in `pyproject.toml` and `__version__` in `src/aiify/__init__.py`,
   and add a `CHANGELOG.md` section.
2. If the guide changed, regenerate `README_AI.md` and `aiify_context.json` with
   agentify's `context_export.py write --root . --package aiify --distribution ai-ify`
   (the test suite fails when they are stale).
3. Commit, then tag and push: `git tag vX.Y.Z && git push origin main vX.Y.Z`.

The `release` workflow then checks the tag against the package version, runs the
tests, builds the wheel and sdist, checks them with twine, installs the wheel into a
clean environment and reads the guide from it, publishes to PyPI with trusted
publishing (GitHub environment `pypi`, no token stored), and attaches the files to a
GitHub release.
