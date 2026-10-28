"""Run the loopback-only synthetic FastAPI backend with the existing .venv."""

import logging

import uvicorn

from src.api.gateway.app import create_app
from src.core.settings import Settings


app = create_app()


def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    settings = Settings.from_environment()
    uvicorn.run(app, host=settings.host, port=settings.port, access_log=False)


if __name__ == "__main__":
    main()
