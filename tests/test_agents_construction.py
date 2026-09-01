"""
Construction smoke test for the two Google ADK agents in the pipeline.
No network call (that needs a real NEBIUS_API_KEY and lives outside CI) -
this only proves the agents + a Runner wire together without raising.
"""

import os

os.environ.setdefault("NEBIUS_API_KEY", "dummy-for-construction-check")

from google.adk.runners import InMemoryRunner

from agents.promise_auditor import create_promise_auditor_agent
from agents.promise_extractor import create_promise_extractor_agent


def test_pipeline_agents_construct_and_wire_to_a_runner():
    agents = [
        create_promise_extractor_agent(api_key="dummy"),
        create_promise_auditor_agent(api_key="dummy"),
    ]
    for agent in agents:
        runner = InMemoryRunner(agent=agent, app_name="promiseproof-test")
        assert runner.agent is agent
        assert runner.session_service is not None
        assert agent.model is not None
