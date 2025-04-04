import asyncio
import os
from typing import Callable, Coroutine

from botbuilder.core import TurnContext
from botbuilder.schema import Activity, ActivityTypes, Attachment, AttachmentLayoutTypes
from browser_use import Agent, Browser, BrowserConfig
from browser_use.agent.views import AgentOutput
from browser_use.browser.context import BrowserContext
from browser_use.browser.views import BrowserState
from langchain_openai import AzureChatOpenAI, ChatOpenAI

from cards import create_final_card, create_progress_card
from config import Config
from storage.session import Session, SessionState, SessionStepState

MAX_EXECUTION_TIME_SECONDS = 600  # 10 minutes


class WrappedAgent(Agent):
    """
    We are wrapping the Agent class to add a post_step_callback that is called after each step.
    The Agent class calls a callback before the execution of each step, but not after.
    Without this, we wouldn't be able to get the latest screenshot after each step, which
    isn't the worst, but it it does lead to added latency to show what the agent just did
    and also doesn't provide the last _actual_ screenshot after the agent has finished.
    """

    def __init__(self, *args, **kwargs):
        self.register_new_post_step_callback: Callable[
            [AgentOutput], Coroutine[None, None, None]
        ] = kwargs.get("register_post_step_callback")
        # Remove the callback from kwargs so it's not passed to the superclass
        kwargs.pop("register_post_step_callback", None)
        super().__init__(*args, **kwargs)

    async def step(self) -> None:
        await super().step()
        if self.register_new_post_step_callback:
            model_outputs = self.history.model_outputs()
            if model_outputs:
                last_model_output = model_outputs[-1]
                await self.register_new_post_step_callback(last_model_output)

class BrowserAgent:
    def __init__(self, context: TurnContext, session: Session, activity_id: str):
        self.context = context
        self.session = session
        self.activity_id = activity_id
        self.browser = Browser(
            config=BrowserConfig(
                headless=True if os.environ.get("IS_DOCKER_ENV", None) else False,
            )
        )
        self.browser_context = BrowserContext(browser=self.browser)
        self.llm = self._setup_llm()
        self.agent = None

    @staticmethod
    def _setup_llm():
        if Config.AZURE_OPENAI_API_KEY:
            return AzureChatOpenAI(
                azure_endpoint=Config.AZURE_OPENAI_API_BASE,
                azure_deployment=Config.AZURE_OPENAI_DEPLOYMENT,
                openai_api_version=Config.AZURE_OPENAI_API_VERSION,
                model_name=Config.AZURE_OPENAI_DEPLOYMENT,  # BrowserUse has a bug where this model_name is required
            )
        return ChatOpenAI(
            model=Config.OPENAI_MODEL_NAME,
            api_key=Config.OPENAI_API_KEY,
        )

    async def _handle_screenshot_and_emit(
        self,
        output: AgentOutput,
    ) -> None:
        screenshot_new = await self.browser_context.take_screenshot()
        actions = (
            [action.model_dump_json(exclude_unset=True) for action in output.action]
            if output.action
            else []
        )

        step = SessionStepState(
            screenshot=screenshot_new,
            action=output.current_state.evaluation_previous_goal,
            memory=output.current_state.memory,
            next_goal=output.current_state.next_goal,
            actions=actions,
        )

        self.session.session_state.append(step)

        # Transform agent history into simple facts list
        history_facts = None
        if self.agent_history and self.agent_history.history:
            thoughts = self.agent_history.model_thoughts()
            actions = self.agent_history.model_actions()

            history_facts = []
            for thought, action in zip(thoughts, actions):
                action_name = list(action.keys())[0] if action else "No action"
                history_facts.append(
                    {
                        "thought": thought.evaluation_previous_goal,
                        "goal": thought.next_goal,
                        "action": action_name,
                    }
                )

        # Update the Teams message with card
        activity = Activity(
            id=self.activity_id,
            type="message",
            attachment_layout=AttachmentLayoutTypes.list,
            attachments=[
                Attachment(
                    content_type="application/vnd.microsoft.card.adaptive",
                    content=create_progress_card(
                        screenshot=step.screenshot,
                        next_goal=step.next_goal,
                        action=step.action,
                        history_facts=history_facts,
                    ),
                )
            ],
        )
        await self.context.update_activity(activity=activity)

    def step_callback(
        self, state: BrowserState, output: AgentOutput, step_number: int
    ) -> None:
        if self.session.state == SessionState.CANCELLATION_REQUESTED and self.agent:
            self.agent.stop()
            asyncio.create_task(
                self._send_final_activity(
                    "Session stopped by user",
                    include_screenshot=False,
                    override_title="🛑 Stopped",
                )
            )
            return

    async def post_step_callback(self, output: AgentOutput) -> None:
        await self._handle_screenshot_and_emit(output)

    async def _send_final_activity(
        self, message: str, include_screenshot: bool = True, override_title: str = None
    ) -> None:
        # Get the last screenshot if available and if requested
        last_screenshot = (
            self.session.session_state[-1].screenshot
            if self.session.session_state and include_screenshot
            else None
        )

        # Transform agent history into simple facts list
        history_facts = None
        if self.agent_history and self.agent_history.history:
            thoughts = self.agent_history.model_thoughts()
            actions = self.agent_history.model_actions()

            history_facts = []
            for thought, action in zip(thoughts, actions):
                action_name = list(action.keys())[0] if action else "No action"
                history_facts.append(
                    {
                        "thought": thought.evaluation_previous_goal,
                        "goal": thought.next_goal,
                        "action": action_name,
                    }
                )

        # First update the progress card
        step = SessionStepState(action=message, screenshot=last_screenshot)
        self.session.session_state.append(step)
        activity = Activity(
            id=self.activity_id,
            type="message",
            attachment_layout=AttachmentLayoutTypes.list,
            attachments=[
                Attachment(
                    content_type="application/vnd.microsoft.card.adaptive",
                    content=create_progress_card(
                        screenshot=None,
                        action="The session concluded",
                        history_facts=history_facts,
                    ),
                )
            ],
        )
        await self.context.update_activity(activity=activity)

        # Then send a final results card
        await self.context.send_activity(
            Activity(
                type=ActivityTypes.message,
                attachments=[
                    Attachment(
                        content_type="application/vnd.microsoft.card.adaptive",
                        content=create_final_card(
                            message, last_screenshot, override_title
                        ),
                    )
                ],
            )
        )

    def done_callback(self, result) -> None:
        self.session.state = SessionState.DONE

        action_results = result.action_results()
        if action_results and (last_result := action_results[-1]):
            final_result = last_result.extracted_content
            asyncio.create_task(self._send_final_activity(final_result))
        else:
            asyncio.create_task(self._send_final_activity("No results found"))

    async def run(self, query: str) -> str:
        agent = WrappedAgent(
            task=query,
            llm=self.llm,
            register_new_step_callback=self.step_callback,
            register_done_callback=self.done_callback,
            register_post_step_callback=self.post_step_callback,
            browser_context=self.browser_context,
            generate_gif=False,
        )
        self.agent = agent
        self.agent_history = agent.history

        try:
            # Run the agent with a 10-minute timeout
            result = await asyncio.wait_for(
                agent.run(), timeout=MAX_EXECUTION_TIME_SECONDS
            )

            action_results = result.action_results()
            return (
                action_results[-1].extracted_content
                if action_results and action_results[-1]
                else "No results found"
            )

        except asyncio.TimeoutError:
            self.session.state = SessionState.ERROR
            error_message = "Browser agent execution timed out after 10 minutes"
            await self._send_final_activity(
                error_message, include_screenshot=False, override_title="⏰ Timeout"
            )
            # Make sure to close the browser even on timeout
            asyncio.create_task(self.browser_context.close())
            return error_message
        except Exception as e:
            self.session.state = SessionState.ERROR
            error_message = f"Error during browser agent execution: {str(e)}"
            await self._send_final_activity(
                error_message, include_screenshot=False, override_title="🚨 Error"
            )
            return error_message
