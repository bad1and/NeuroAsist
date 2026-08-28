// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest";
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import React from "react";
import { IrisSubtitles, splitIntoSubtitleCues } from "./IrisSubtitles";
import type { ChatMessage } from "../types";

describe("splitIntoSubtitleCues", () => {
  it("возвращает пустой массив для пустых строк", () => {
    expect(splitIntoSubtitleCues("")).toEqual([]);
    expect(splitIntoSubtitleCues("   ")).toEqual([]);
  });

  it("возвращает один фрагмент, если текст короткий", () => {
    const text = "Привет! Я Iris.";
    expect(splitIntoSubtitleCues(text, 90)).toEqual(["Привет! Я Iris."]);
  });

  it("разбивает по предложениям при превышении лимита длины", () => {
    const text = "Первое предложение короткое. Второе предложение тоже достаточно короткое. Третье предложение завершает мысль.";
    const cues = splitIntoSubtitleCues(text, 50);
    expect(cues.length).toBeGreaterThan(1);
    expect(cues.every((cue) => cue.length <= 50)).toBe(true);
    expect(cues.join(" ")).toBe(text);
  });

  it("разбивает длинные предложения по знакам препинания и клаузам", () => {
    const longSentence = "Я сегодня хотела рассказать тебе о том, как устроен наш новый модуль памяти, и почему он работает намного быстрее.";
    const cues = splitIntoSubtitleCues(longSentence, 60);
    expect(cues.length).toBeGreaterThan(1);
    expect(cues.every((cue) => cue.length <= 60)).toBe(true);
  });

  it("разбивает по словам при отсутствии знаков препинания", () => {
    const longWordSequence = "слово1 слово2 слово3 слово4 слово5 слово6 слово7 слово8 слово9 слово10";
    const cues = splitIntoSubtitleCues(longWordSequence, 30);
    expect(cues.length).toBeGreaterThan(1);
    expect(cues.every((cue) => cue.length <= 30)).toBe(true);
    expect(cues.join(" ")).toBe(longWordSequence);
  });

  it("корректно обрабатывает переносы строк", () => {
    const text = "Строка один.\n\nСтрока два.";
    const cues = splitIntoSubtitleCues(text, 90);
    expect(cues).toEqual(["Строка один.", "Строка два."]);
  });
});

describe("IrisSubtitles Component", () => {
  it("отображает статус размышления, когда loading=true", () => {
    render(
      <IrisSubtitles
        messages={[]}
        loading={true}
        voiceState="idle"
      />
    );
    expect(screen.getByText("Думаю . . .")).toBeInTheDocument();
  });

  it("отображает статус записи и распознавания голоса", () => {
    const { rerender } = render(
      <IrisSubtitles
        messages={[]}
        loading={false}
        voiceState="recording"
      />
    );
    expect(screen.getByText("Слушаю . . .")).toBeInTheDocument();

    rerender(
      <IrisSubtitles
        messages={[]}
        loading={false}
        voiceState="transcribing"
      />
    );
    expect(screen.getByText("Распознаю . . .")).toBeInTheDocument();
  });

  it("отображает субтитры для ответа ассистента", () => {
    const messages: ChatMessage[] = [
      { id: "u1", role: "user", content: "Привет" },
      { id: "a1", role: "assistant", content: "Привет! Рада тебя слышать." },
    ];
    render(
      <IrisSubtitles
        messages={messages}
        loading={false}
        voiceState="idle"
      />
    );
    expect(screen.getByText("Привет! Рада тебя слышать.")).toBeInTheDocument();
  });

  it("переключает активный фрагмент субтитров при смене livePlaybackSegment", () => {
    const messages: ChatMessage[] = [
      {
        id: "a1",
        role: "assistant",
        content: "Первая фраза ответа длинная. Вторая фраза ответа продолжается.",
      },
    ];
    const { rerender } = render(
      <IrisSubtitles
        messages={messages}
        loading={false}
        voiceState="speaking"
        livePlaybackSegment="Первая фраза ответа длинная."
      />
    );
    expect(screen.getByText(/Первая фраза/)).toBeInTheDocument();

    rerender(
      <IrisSubtitles
        messages={messages}
        loading={false}
        voiceState="speaking"
        livePlaybackSegment="Вторая фраза ответа"
      />
    );
    expect(screen.getByText(/Вторая фраза/)).toBeInTheDocument();
  });
});
