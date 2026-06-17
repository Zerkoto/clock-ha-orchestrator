from fastapi import FastAPI

from app.api.routes import router


def create_app() -> FastAPI:
    app = FastAPI(
        title="Clock HA Orchestrator",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )
    app.include_router(router)
    return app


app = create_app()

