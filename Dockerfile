# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# Modified by the Product Safety Desk team.

# One image serves both services: psd-agents runs the CMD below; psd-api is deployed from the same image with
# `uvicorn api.main:app` as its command. Both read the knowledge bundle and the SQL baked in here.
FROM python:3.12-slim

# Install uv
COPY --from=ghcr.io/astral-sh/uv:0.8.13 /uv /uvx /bin/

WORKDIR /code

COPY ./pyproject.toml ./README.md ./uv.lock* ./

COPY ./app ./app
COPY ./api ./api
COPY ./config ./config
COPY ./data ./data
COPY ./knowledge ./knowledge
COPY ./sql ./sql

RUN uv sync --frozen

ARG AGENT_VERSION=0.0.0
ENV AGENT_VERSION=${AGENT_VERSION}

# The commit the knowledge bundle was built from, set by Cloud Build; left empty (a --source deploy), the desk records a
# hash of the bundle instead.
ARG PSD_KNOWLEDGE_VERSION=
ENV PSD_KNOWLEDGE_VERSION=${PSD_KNOWLEDGE_VERSION}

EXPOSE 8080

CMD ["uv", "run", "uvicorn", "app.fast_api_app:app", "--host", "0.0.0.0", "--port", "8080"]
