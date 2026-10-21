// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest";
import { afterEach, describe, it, expect } from "vitest";
import { cleanup, render, screen, fireEvent, within } from "@testing-library/react";
import { TokenBadge, TokenDialogContent } from "./TokenBadge";
import type { TokenMetadata } from "../types";

afterEach(cleanup);

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
    expect(screen.getByText("На входе")).toBeInTheDocument();
    expect(screen.getByText(/1[\s\u00a0,.]?000/)).toBeInTheDocument();
    const cache = screen.getByRole("region", { name: "Кэш запроса" });
    expect(within(cache).getByText("800")).toBeInTheDocument();
    expect(within(cache).getByText("200")).toBeInTheDocument();
    expect(within(cache).getByText("80%")).toBeInTheDocument();
    expect(screen.getByText("В ответе")).toBeInTheDocument();
    expect(screen.getByText("Рассуждения:")).toBeInTheDocument();
    expect(screen.getByText("50")).toBeInTheDocument();
    expect(screen.getByText("Время ответа")).toBeInTheDocument();
    expect(screen.getByText("0,42 с")).toBeInTheDocument();

    // Toggle raw JSON
    const rawBtn = screen.getByRole("button", { name: "JSON ответа" });
    expect(rawBtn).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(rawBtn);
    expect(rawBtn).toHaveAttribute("aria-expanded", "true");
    expect(document.getElementById(rawBtn.getAttribute("aria-controls")!)).toBeVisible();
    expect(screen.getByText("Копировать")).toBeInTheDocument();

    // Close button
    const closeBtn = screen.getByRole("button", { name: /Закрыть/i });
    fireEvent.click(closeBtn);
    expect(screen.queryByText("Статистика токенов")).not.toBeInTheDocument();
  });

  it("keeps missing usage unknown and does not treat partial cache data as a full cache hit", () => {
    render(<TokenDialogContent tokens={{ prompt_tokens: 1000, prompt_cache_hit_tokens: 400 }} role="assistant" onClose={() => {}} />);
    const cache = screen.getByRole("region", { name: "Кэш запроса" });
    expect(within(cache).getByText("40%")).toBeInTheDocument();
    expect(within(cache).getByText("Без кэша").nextElementSibling).toHaveTextContent("—");
    expect(screen.getByText("В ответе").nextElementSibling).toHaveTextContent("—");
    expect(screen.getByText("Всего токенов").nextElementSibling).toHaveTextContent("—");
  });
});
