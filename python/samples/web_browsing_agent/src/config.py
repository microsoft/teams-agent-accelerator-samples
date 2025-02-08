"""
Copyright (c) Microsoft Corporation. All rights reserved.
Licensed under the MIT License.
"""

import os

from dotenv import load_dotenv

load_dotenv()


class Config:
    """Bot Configuration"""

    PORT = 3978
    APP_ID = os.environ.get("BOT_ID", "")
    APP_PASSWORD = os.environ.get("BOT_PASSWORD", "")

    # LLM Configuration
    AZURE_OPENAI_API_BASE = os.environ.get("AZURE_OPENAI_ENDPOINT", None)
    AZURE_OPENAI_API_KEY = os.environ.get("AZURE_OPENAI_API_KEY", None)
    AZURE_OPENAI_DEPLOYMENT = os.environ.get("AZURE_OPENAI_MODEL_DEPLOYMENT_NAME", None)
    AZURE_OPENAI_API_VERSION = os.environ.get("AZURE_OPENAI_API_VERSION", None)
    OPENAI_MODEL_NAME = os.environ.get("OPENAI_MODEL_NAME", None)
    OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", None)
