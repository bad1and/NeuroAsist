// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { createRef } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { IrisSubtitles } from "./IrisSubtitles";
import { ConversationSurface } from "./ConversationSurface";
import * as animations from "../animations";
import { BackgroundConversationControls, BackgroundConversationExpandButton } from "./BackgroundConversationControls";

afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks(); });

it("advances subtitle cues while minimized and preserves the choice across section changes", () => {
  vi.useFakeTimers();
  const host = document.createElement("div");
  document.body.appendChild(host);
  const backgroundHost = { current: host };
  const messages = [{ id: "speech", role: "assistant" as const, content: "Первая фраза, вторая фраза, третья фраза." }];
  const view = (active: boolean) => <ConversationSurface active={active} backgroundVisible backgroundHost={backgroundHost}>
    {(background, minimized, toggle) => <>
      {background && minimized && <BackgroundConversationExpandButton onExpand={toggle} />}
      <div className="background-conversation-body" hidden={background && minimized}>
        {background && <BackgroundConversationControls microphoneActive microphoneStarting={false} microphoneDisabled={false} soundMuted={false} onMicrophone={() => {}} onSound={() => {}} onMinimize={toggle} />}
        <IrisSubtitles messages={messages} loading={false} voiceState="speaking" livePlaybackSegment={messages[0].content} livePlaybackDurationSeconds={9} compact={background} />
      </div>
    </>}
  </ConversationSurface>;
  try {
    const { rerender } = render(view(false));
    const region = screen.getByRole("region", { name: "Субтитры Iris" });
    fireEvent.click(screen.getByRole("button", { name: "Свернуть панель разговора" }));
    expect(region.closest("[hidden]")).not.toBeNull();
    act(() => { vi.advanceTimersByTime(7000); });
    expect(region.querySelector("[data-active-cue]")?.textContent).toContain("третья фраза");
    rerender(view(true));
    expect(screen.getByRole("region", { name: "Субтитры Iris" })).toBe(region);
    rerender(view(false));
    expect(screen.getByRole("button", { name: "Развернуть панель разговора" })).toBeDefined();
    fireEvent.click(screen.getByRole("button", { name: "Развернуть панель разговора" }));
    expect(screen.getByRole("region", { name: "Субтитры Iris" })).toBe(region);
    expect(region.querySelector("[data-active-cue]")?.textContent).toContain("третья фраза");
  } finally { host.remove(); }
});

it("keeps the same subtitles and advances cues while visiting another section", () => {
  vi.useFakeTimers();
  const host = document.createElement("div");
  document.body.appendChild(host);
  const backgroundHost = { current: host };
  const messages = [{ id: "speech", role: "assistant" as const, content: "Первая фраза, вторая фраза, третья фраза." }];
  const view = (active: boolean) => (
    <ConversationSurface active={active} backgroundVisible backgroundHost={backgroundHost}>
      <IrisSubtitles messages={messages} loading={false} voiceState="speaking"
        livePlaybackSegment={messages[0].content} livePlaybackDurationSeconds={9} compact={!active} />
    </ConversationSurface>
  );
  try {
    const { rerender } = render(view(true));
    const region = screen.getByRole("region", { name: "Субтитры Iris" });
    act(() => { vi.advanceTimersByTime(3500); });
    const cue = region.querySelector("[data-active-cue]")?.textContent;
    rerender(view(false));
    expect(host.contains(region)).toBe(true);
    expect(region.querySelector("[data-active-cue]")?.textContent).toBe(cue);
    act(() => { vi.advanceTimersByTime(3500); });
    expect(region.querySelector("[data-active-cue]")?.textContent).toContain("третья фраза");
    rerender(view(true));
    expect(screen.getByRole("region", { name: "Субтитры Iris" })).toBe(region);
    expect(host.contains(region)).toBe(false);
    expect(region.querySelector("[data-active-cue]")?.textContent).toContain("третья фраза");
  } finally { host.remove(); }
});

it("shows on the first render even when the notification host mounts later in the commit", async () => {
  const backgroundHost = createRef<HTMLDivElement>();
  await act(async () => {
    render(<>
      <ConversationSurface active={false} backgroundVisible backgroundHost={backgroundHost}>
        {(compact) => <span>{compact ? "В уведомлениях" : "В диалоге"}</span>}
      </ConversationSurface>
      <div ref={backgroundHost} />
    </>);
  });
  expect(backgroundHost.current!.contains(screen.getByText("В уведомлениях"))).toBe(true);
});

it("keeps compact subtitles until exit completes and cancels stale exits on rapid navigation", () => {
  const motions: { phase: string; finish?: () => void; cancel: ReturnType<typeof vi.fn> }[] = [];
  vi.spyOn(animations, "animateNotification").mockImplementation((_target, phase, finish) => {
    const motion = { phase, finish, cancel: vi.fn() };
    motions.push(motion);
    return motion as unknown as animations.Animation;
  });
  const host = document.createElement("div");
  document.body.appendChild(host);
  const backgroundHost = { current: host };
  const view = (active: boolean, enabled = true) => (
    <ConversationSurface active={active} backgroundVisible={enabled} backgroundHost={backgroundHost}>
      {(compact) => <div data-testid="cue">{compact ? "Компактно" : "В диалоге"}</div>}
    </ConversationSurface>
  );
  try {
    const { rerender } = render(view(false));
    const cue = screen.getByTestId("cue");
    expect(cue.textContent).toBe("Компактно");
    expect(motions[0].phase).toBe("enter");
    rerender(view(true));
    const firstExit = motions[motions.length - 1];
    expect(firstExit.phase).toBe("exit");
    expect(host.contains(cue)).toBe(true);
    expect(cue.textContent).toBe("Компактно");
    expect(cue.parentElement!.inert).toBe(true);
    rerender(view(false));
    expect(firstExit.cancel).toHaveBeenCalledOnce();
    act(() => firstExit.finish?.());
    expect(host.contains(cue)).toBe(true);
    expect(cue.parentElement!.inert).toBe(false);
    rerender(view(false, false));
    act(() => motions[motions.length - 1].finish?.());
    expect(host.contains(cue)).toBe(false);
    expect(screen.getByTestId("cue")).toBe(cue);
    expect(cue.textContent).toBe("В диалоге");
    expect(cue.parentElement!.style.transform).toBe("");
  } finally { host.remove(); }
});
