"""Finds the Agent Engine instance psd-agents keeps its sessions and memories in, creating it the first time.

    uv run python infra/agent_engine.py [--project PROJECT] [--location us-central1]

Prints the instance id to set as GOOGLE_CLOUD_AGENT_ENGINE_ID on psd-agents, and makes sure the instance's Memory Bank
has the desk's settings. The instance runs no agent code: ADK's VertexAiSessionService stores each incident's run in
it as a session named after the incident, and app/learn.py writes the desk's observations to its Memory Bank.
"""

import argparse
import os

import agentplatform

DISPLAY_NAME = "psd-agent-engine"
# The four kinds of observation the desk keeps; app/learn.py labels every fact with one of them.
TOPICS = {
    "supplier_quality_history": "Durable facts about a supplier's recalls, labelling defects, case outcomes and "
    "response times. Third person. No customer details.",
    "product_incident_history": "Durable facts about a product's recalls, hazards, affected batches or lots, and "
    "label defects.",
    "store_execution_pattern": "How quickly and how a store executes and verifies hold or pull tasks.",
    "coordinator_playbook": "Rules coordinators apply when editing proposed actions and incident texts, stated as "
    "reusable guidance.",
}
TTL = f"{90 * 24 * 3600}s"
# Memory Bank's models come from the us multi-region: gemini-3.8-flash has no us-central1 endpoint, and Memory Bank
# takes gemini-embedding-2 only from global, us or eu.
MODEL_LOCATION = "us"


def memory_bank_config(project: str) -> dict:
    models = f"projects/{project}/locations/{MODEL_LOCATION}/publishers/google/models"
    return {
        "customization_configs": [
            {
                "memory_topics": [
                    {
                        "custom_memory_topic": {
                            "label": label,
                            "description": description,
                        }
                    }
                    for label, description in TOPICS.items()
                ],
                "enable_third_person_memories": True,
            }
        ],
        "similarity_search_config": {"embedding_model": f"{models}/gemini-embedding-2"},
        "generation_config": {"model": f"{models}/gemini-3.8-flash"},
        "ttl_config": {"default_ttl": TTL},
    }


def find_or_create(project: str, location: str) -> str:
    client = agentplatform.Client(project=project, location=location)
    config = {
        "display_name": DISPLAY_NAME,
        "description": "Product Safety Desk: incident sessions and observations. Runs no agent code.",
        "context_spec": {"memory_bank_config": memory_bank_config(project)},
    }
    found = list(
        client.runtimes.list(config={"filter": f'display_name="{DISPLAY_NAME}"'})
    )
    if not found:
        return client.runtimes.create(config=config).api_resource.name
    name = found[0].api_resource.name
    client.runtimes.update(name=name, config=config)
    return name


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--project", default=os.environ.get("GOOGLE_CLOUD_PROJECT"))
    parser.add_argument("--location", default="us-central1")
    args = parser.parse_args()
    if not args.project:
        raise SystemExit("set --project or GOOGLE_CLOUD_PROJECT")
    name = find_or_create(args.project, args.location)
    print(name)
    print(f"GOOGLE_CLOUD_AGENT_ENGINE_ID={name.rsplit('/', 1)[-1]}")


if __name__ == "__main__":
    main()
