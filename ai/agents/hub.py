from crewai import Agent, LLM
from typing import Optional, Type, Generic, TypeVar, Any
from pydantic import BaseModel, Field
from dataclasses import dataclass, field
from settings import Config

T = TypeVar('T', bound=BaseModel)


@dataclass
class SingleAgent(Generic[T]):

    role: str
    goal: str
    backstory: str
    llm: LLM = field(default_factory=lambda: LLM(model='gpt-5.2', api_key=Config.OPENAI_API_KEY))
    schema: Optional[Type[BaseModel]] = None

    def _agent(self) -> Agent:
        return Agent(role=self.role, goal=self.goal, backstory=self.backstory, llm=self.llm, verbose=True)

    def run(self, prompt: str, tools: Optional[list] = None) -> Any:
        return self._agent().kickoff(messages=prompt, response_format=self.schema) if self.schema else self._agent().kickoff(messages=prompt)


class VoiceSchema(BaseModel):
    prompt:           str   = Field(description='users original prompt')
    fixed_prompt:     str   = Field(description='fixed prompt')
    confidence_score: float = Field(description='confidence score')


def voice_agent(prompt: str) -> dict:
    return SingleAgent(role='voice_agent', goal='accurately analyze the voice', backstory='voice agent', schema=VoiceSchema).run(prompt=prompt)


print(voice_agent('hi claude'))