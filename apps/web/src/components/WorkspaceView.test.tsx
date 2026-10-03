// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { useEffect, useState } from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { WorkspaceView } from "./WorkspaceView";

it("preserves drafts and stops polling while hidden, then resumes once", () => {
  vi.useFakeTimers();
  const poll = vi.fn();
  function Screen() {
    const [draft, setDraft] = useState("");
    useEffect(() => {
      const timer = setInterval(poll, 1000);
      return () => clearInterval(timer);
    }, []);
    return <input aria-label="Черновик" value={draft} onChange={event => setDraft(event.target.value)} />;
  }
  const view = render(<WorkspaceView active><Screen /></WorkspaceView>);
  const input = screen.getByRole("textbox");
  fireEvent.change(input, { target: { value: "Несохранённый текст" } });
  act(() => vi.advanceTimersByTime(1000));
  expect(poll).toHaveBeenCalledTimes(1);
  view.rerender(<WorkspaceView active={false}><Screen /></WorkspaceView>);
  act(() => vi.advanceTimersByTime(5000));
  expect(poll).toHaveBeenCalledTimes(1);
  expect(screen.queryByRole("textbox")).toBeNull();
  view.rerender(<WorkspaceView active><Screen /></WorkspaceView>);
  expect(screen.getByRole("textbox")).toBe(input);
  expect(input).toHaveValue("Несохранённый текст");
  act(() => vi.advanceTimersByTime(1000));
  expect(poll).toHaveBeenCalledTimes(2);
  view.unmount();
  vi.useRealTimers();
});
