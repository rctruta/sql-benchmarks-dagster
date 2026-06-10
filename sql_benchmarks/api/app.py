from fastapi import FastAPI

from .routers import catalog, experiments, recommend, results


def create_app() -> FastAPI:
    app = FastAPI(
        title="SQL Benchmarks API",
        description=(
            "Ground-truth SQL performance data for researchers and AI agents. "
            "Query pre-computed benchmark results across PostgreSQL, DuckDB, and Actian Vector, "
            "or submit new experiments to run against the lab.\n\n"
            "See [AGENTS.md](https://github.com/your-repo/blob/main/AGENTS.md) for the agentic protocol."
        ),
        version="1.0.0",
        docs_url="/docs",
        openapi_url="/openapi.json",
    )

    app.include_router(catalog.router)
    app.include_router(results.router)
    app.include_router(recommend.router)
    app.include_router(experiments.router)

    @app.get("/health", tags=["meta"])
    def health():
        """Health check."""
        return {"status": "ok"}

    return app
