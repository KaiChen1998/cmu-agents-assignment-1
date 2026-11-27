"""The Part 1 coding agent: fix a software issue and submit a git patch."""

from __future__ import annotations

import json
from typing import Any

from assignment.agent.base import (
    DEFAULT_COMPACTION_KEEP_RECENT_STEPS,
    DEFAULT_COMPACTION_MAX_TOKENS,
    Agent,
    format_tool_output,
)
from assignment.agent.tools import EXECUTE_TOOL, SEND_MESSAGE_TOOL
from assignment.env import Environment

class CodeAgent(Agent):
    """An agent that fixes a software issue and submits a git patch."""

    def __init__(
        self,
        task: str,
        environment: Environment,
        model: str | None = None,
        logs_save_path: str | None = None,
        step_limit: int = 100,
        skills_path: str | None = None,
        auto_stop_environment: bool = True,
        compact_threshold_tokens: int | None = None,
        compaction_keep_recent_steps: int = DEFAULT_COMPACTION_KEEP_RECENT_STEPS,
        compaction_max_tokens: int = DEFAULT_COMPACTION_MAX_TOKENS,
    ):
        super().__init__(
            environment=environment,
            model=model,
            logs_save_path=logs_save_path,
            step_limit=step_limit,
            skills_path=skills_path,
            auto_stop_environment=auto_stop_environment,
            compact_threshold_tokens=compact_threshold_tokens,
            compaction_keep_recent_steps=compaction_keep_recent_steps,
            compaction_max_tokens=compaction_max_tokens,
        )
        self.task = task
        self.submitted_patch = ""

        # TODO(Part 1.3): Make the `execute` and `send_message` tools available
        # to the agent.
        self.tools.extend([EXECUTE_TOOL, SEND_MESSAGE_TOOL])

        # TODO(1.1.b): Construct the system prompt and task_prompt. These
        # should be usable by the `Agent.build_prompt` method.
        system_information = json.dumps(
            {
                "machine": environment.machine,
                "release": environment.release,
                "system": environment.system,
                "version": environment.version,
            },
            indent=2,
        )
        self.system_prompt = (
            "You are a coding agent working in a terminal sandbox. "
            "Investigate the task, make focused changes, and verify your work "
            "with relevant tests. Use tool results to decide your next action.\n\n"
            f"<system_information>\n{system_information}\n</system_information>"
        )
        self.task_prompt = task

        # TODO(1.4): If any skills are available to the agent, make their
        # descriptions/metadata available to the agent in the prompt.
        if self.skills:
            catalog = "\n\n".join(skill["metadata"] for skill in self.skills.values())
            self.system_prompt += (
                "\n\nIf a skill applies to your task, call `invoke_skill` with its "
                "listed name to read the full instructions.\n\n"
                f"<skills>\n{catalog}\n</skills>"
            )

    def execute_tool_calls(
        self, tool_calls: list[dict[str, Any]]
    ) -> list[dict[str, str]]:
        """Execute ``execute`` and ``send_message`` calls in the code sandbox."""

        # TODO(Part 1.3): Parse each call, execute recognized tools, and return
        # one message per call (there may be multiple tool calls in one agent
        # response!). Malformed JSON and unknown tools must become recoverable
        # observations relayed to the agent instead of exceptions.
        # raise NotImplementedError
    
        #################
        # tool_calls: {"id", "type", "function"}
        # observations: {"role": "tool", "tool_call_id", "content"}
        #################
        observations: list[dict[str, str]] = []
        for call in tool_calls:
            try:
                if self.finished:
                    raise ValueError("The task is already finished.")

                # Parse outputs for function calling
                function = call.get("function")
                if not isinstance(function, dict):
                    raise ValueError("Expected a function tool call.")
                name = function.get("name")
                arguments = json.loads(function.get("arguments", ""))
                if not isinstance(arguments, dict):
                    raise ValueError("Tool arguments must be a JSON object.")

                if name == "execute":
                    content = self._execute_command(arguments)
                elif name == "invoke_skill" and self.skills:
                    skill_name = arguments.get("name")
                    if arguments.keys() != {"name"} or not isinstance(skill_name, str):
                        raise ValueError("invoke_skill requires a single string name.")
                    skill = self.skills.get(skill_name)
                    if skill is None:
                        raise ValueError(f"Unknown skill {skill_name!r}.")
                    content = skill["content"]
                elif name == "send_message":
                    summary = arguments.get("summary")
                    if arguments.keys() != {"summary"} or not isinstance(summary, str):
                        raise ValueError("send_message requires a single string summary.")
                    print(summary, flush=True)
                    self.finished = True
                    content = "Message sent."
                else:
                    raise ValueError(f"Unknown tool {name!r}.")
            except json.JSONDecodeError as exc:
                content = f"Invalid JSON arguments. {exc.msg}"
            except (TypeError, ValueError) as exc:
                content = f"Tool call failed. {exc}"

            observations.append(
                {"role": "tool", "tool_call_id": call["id"], "content": content}
            )
        return observations

    def _execute_command(self, arguments: dict[str, Any]) -> str:
        """Run a command with the options exposed by the execute tool."""
        properties = EXECUTE_TOOL["function"]["parameters"]["properties"]
        unexpected = arguments.keys() - properties.keys()
        if unexpected:
            raise ValueError(f"Unexpected execute arguments {', '.join(sorted(unexpected))}.")

        command = arguments.get("command")
        if isinstance(command, str) or (
            isinstance(command, list) and all(isinstance(part, str) for part in command)
        ):
            return format_tool_output(self.env.execute(**arguments))
        raise ValueError("execute requires a command string or a list of strings.")
