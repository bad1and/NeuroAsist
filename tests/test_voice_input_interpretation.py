import anyio

from apps.backend.app.agents.character.agent import CharacterAgent
from apps.backend.app.agents.character.voice_input import VoiceInputInterpreter
from apps.backend.app.llm.base import LLMResponse
from apps.backend.app.memory.service import MemoryService
from apps.backend.app.runtime.settings import RuntimeSettings
from apps.backend.app.storage.timeline import TimelineHistoryAdapter, TimelineStore


class RecordingProvider:
    def __init__(self) -> None:
        self.messages = []

    async def generate(self, messages):
        self.messages = messages
        return LLMResponse(
            content='{"reply":"Поняла.","emotion":"neutral","intent":"casual_chat"}',
            model="test",
        )


class StreamingRecordingProvider:
    def __init__(self) -> None:
        self.messages = []

    async def stream(self, messages):
        self.messages = messages
        yield "Поняла."


def _service_with_oleg(tmp_path):
    store = TimelineStore(tmp_path / "memory.sqlite3")
    store.init_db()
    service = MemoryService(store, RuntimeSettings(memory_mode="automatic"))
    source, _ = store.append_message(role="user", content="Меня зовут Олег", input_mode="text")
    service.extract_from_message(source)
    return store, service


def test_voice_interpreter_repairs_known_name_and_clear_common_typos(tmp_path) -> None:
    _store, service = _service_with_oleg(tmp_path)

    interpreted = VoiceInputInterpreter(service).interpret("Ривет, Лега, как твои елда?", "voice")

    assert interpreted.text == "Привет, Олег, как твои еда?"
    assert interpreted.replacement_count == 3


def test_voice_interpreter_leaves_text_input_and_unknown_words_unchanged(tmp_path) -> None:
    _store, service = _service_with_oleg(tmp_path)
    interpreter = VoiceInputInterpreter(service)

    assert interpreter.interpret("Ривет, Лега", "text").text == "Ривет, Лега"
    assert interpreter.interpret("ксвтри", "voice").text == "ксвтри"


def test_agent_uses_interpreted_voice_text_but_keeps_raw_transcript(tmp_path) -> None:
    store, service = _service_with_oleg(tmp_path)
    provider = RecordingProvider()
    agent = CharacterAgent(provider, TimelineHistoryAdapter(store), history_limit=5, memory_service=service)

    anyio.run(agent.handle_user_message, "voice-test", "Ривет, Лега, как твои елда?", "voice")

    assert provider.messages[-1].content == "Привет, Олег, как твои еда?"
    messages, _ = store.list_messages(20)
    user_message = [item for item in messages if item.content == "Ривет, Лега, как твои елда?"][0]
    assert user_message.effective_content == "Привет, Олег, как твои еда?"
    assert user_message.metadata["voice_interpretation"] == {"version": "v1", "replacement_count": 3}


def test_live_voice_path_uses_interpreted_text(tmp_path) -> None:
    store, service = _service_with_oleg(tmp_path)
    provider = StreamingRecordingProvider()
    agent = CharacterAgent(provider, TimelineHistoryAdapter(store), history_limit=5, memory_service=service)

    async def consume() -> None:
        async for _ in agent.stream_user_message("voice-test", "Ривет, Лега", input_mode="voice"):
            pass

    anyio.run(consume)

    assert provider.messages[-1].content == "Привет, Олег"
