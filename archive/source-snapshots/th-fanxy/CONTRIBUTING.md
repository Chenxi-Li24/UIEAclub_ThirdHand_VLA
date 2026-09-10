# Contributing to ThirdHand VLA

## Development Setup

```bash
git clone https://github.com/Chenxi-Li24/UIEAclub_ThirdHand_VLA
cd UIEAclub_ThirdHand_VLA
pip install -e ".[dev]"
```

## Code Style

- Python 3.10+, type hints (mypy strict)
- Ruff for linting: `ruff check src/ tests/`
- Line length: 100 chars

## Testing

```bash
pytest tests/ -v
```

## Pull Requests

1. Fork the repo
2. Create a feature branch
3. Add tests for new functionality
4. Ensure CI passes (`ruff check`, `mypy`, `pytest`)
5. Submit PR against `main` branch

## Module Guidelines

- Each module implements its interface contract (see `docs/module_guide.md`)
- Config is validated at load time via Pydantic models
- Safety checks wrap all robot motions
- New tasks implement `BaseTask` ABC
- New detectors implement `BaseDetector` ABC
