// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest";
import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { TokenBadge } from "./TokenBadge";
import type { TokenMetadata } from "../types";

describe("TokenBadge component", () => {
  it("renders null if tokens are null or empty", () => {
    const { container: c1 } = render(<TokenBadge tokens={null} role="user" />);
    expect(c1.firstChild).toBeNull();

    const { container: c2 } = render(<TokenBadge tokens={{ prompt_tokens: 0, completion_tokens: 0, total_tokens: 0 }} role="assistant" />);
    expect(c2.firstChild).toBeNull();
  });

  it("renders user badge with input tokens", () => {
    const tokens: TokenMetadata = {
      prompt_tokens: 1240,
      total_tokens: 1240,
    };
    render(<TokenBadge tokens={tokens} role="user" />);
    expect(screen.getByText("1.2k in")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Токены: 1\.2k in/i })).toBeInTheDocument();
  });

  it("renders assistant badge with output tokens", () => {
    const tokens: TokenMetadata = {
      prompt_tokens: 1240,
      completion_tokens: 185,
      total_tokens: 1425,
      reasoning_tokens: 42,
      latency_ms: 350,
      model: "deepseek-flash",
    };
    render(<TokenBadge tokens={tokens} role="assistant" />);
    expect(screen.getByText("185 out")).toBeInTheDocument();
  });

  it("opens popover with detailed statistics and raw JSON on click", () => {
    const tokens: TokenMetadata = {
      prompt_tokens: 1000,
      completion_tokens: 200,
      total_tokens: 1200,
      prompt_cache_hit_tokens: 800,
      prompt_cache_miss_tokens: 200,
      reasoning_tokens: 50,
      latency_ms: 420,
      model: "deepseek-flash",
      raw_usage: {
        prompt_tokens: 1000,
        completion_tokens: 200,
        total_tokens: 1200,
      },
    };
    render(<TokenBadge tokens={tokens} role="assistant" />);
    const badgeButton = screen.getByRole("button", { name: /Токены: 200 out/i });
    fireEvent.click(badgeButton);

    // Popover is opened in portal
    expect(screen.getByText("Статистика токенов")).toBeInTheDocument();
    expect(screen.getByText("deepseek-flash")).toBeInTheDocument();
    expect(screen.getByText("Входящие (Prompt)")).toBeInTheDocument();
    expect(screen.getByText(/1[\s\u00a0,.]?000/)).toBeInTheDocument();
    expect(screen.getByText(/Hit:\s*800/)).toBeInTheDocument();
    expect(screen.getByText(/Miss:\s*200/)).toBeInTheDocument();
    expect(screen.getByText("(80%)")).toBeInTheDocument();
    expect(screen.getByText("Исходящие (Output)")).toBeInTheDocument();
    expect(screen.getByText("200")).toBeInTheDocument();
    expect(screen.getByText(/Мысли:\s*50/)).toBeInTheDocument();
    expect(screen.getByText("Задержка: 420 мс")).toBeInTheDocument();

    // Toggle raw JSON
    const rawBtn = screen.getByRole("button", { name: /Сырой JSON ответа/i });
    fireEvent.click(rawBtn);
    expect(screen.getByText("Копировать")).toBeInTheDocument();

    // Close button
    const closeBtn = screen.getByRole("button", { name: /Закрыть/i });
    fireEvent.click(closeBtn);
    expect(screen.queryByText("Статистика токенов")).not.toBeInTheDocument();
  });
});
