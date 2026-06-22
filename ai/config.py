from settings import Config
from crewai import Agent, LLM
from pydantic import BaseModel
from dataclasses import dataclass
from typing import Optional, Generic, TypeVar, Type, Any

T = TypeVar('T', bound=BaseModel)


@dataclass
class SingleAgent(Generic[T]):

    name: str
    goal: str
    backstory: str
    schema: Optional[Type[BaseModel]] = None

    @property
    def llm(self) -> LLM:
        return LLM(model='gpt-5.2', api_key=Config.OPENAI_API_KEY)

    def _fetch_agent(self) -> Agent:
        return Agent(role=self.name, goal=self.goal, backstory=self.backstory, llm=self.llm)

    def run(self, prompt: str) -> Any:
        if self.schema:
            return self._fetch_agent().kickoff(prompt, response_format=self.schema)
        return self._fetch_agent().kickoff(prompt).raw


if __name__ == '__main__':
    print(SingleAgent(name='funny agent', backstory='funny', goal='funny').run('tell me a joke'))
