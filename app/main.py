from fastapi import FastAPI

from app.api.routes import router
from app.runtime import lifespan


def create_app() -> FastAPI:
    app = FastAPI(
        title="Clock HA Orchestrator",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )
    app.include_router(router)
    return app


app = create_app()
