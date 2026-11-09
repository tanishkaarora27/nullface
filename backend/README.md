# NullFace backend

FastAPI gateway + the three engines. See the root README for the full picture.

```bash
pip install -r requirements.txt          # CPU-only baseline
uvicorn app.main:app --reload            # http://localhost:8000 (PWA) · /docs (Swagger)
pytest -q                                # end-to-end tests
```
