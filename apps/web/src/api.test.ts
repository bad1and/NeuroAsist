import { afterEach, describe, expect, it, vi } from "vitest";

import { getAvatarOverlay, getAvatarStatus, sendAvatarTestEmotion, sendAvatarTestGesture, sendAvatarTestPhrase, stopAvatar, updateAvatarOverlay } from "./api";

describe("avatar API", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("uses avatar routes with JSON payloads", async () => {
    const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ enabled: true, client_count: 1 }) });
    vi.stubGlobal("fetch", fetch);

    await getAvatarStatus();
    await getAvatarOverlay();
    await updateAvatarOverlay({ visible: false });
    await sendAvatarTestPhrase({ text: "hello", emotion: "happy" });
    await sendAvatarTestEmotion({ emotion: "happy", intensity: 1 });
    await sendAvatarTestGesture({ gesture: "greeting", intensity: 0.8 });
    await stopAvatar();

    expect(fetch.mock.calls.map(([url]) => url)).toEqual([
      "http://127.0.0.1:8000/avatar/status",
      "http://127.0.0.1:8000/avatar/overlay",
      "http://127.0.0.1:8000/avatar/overlay",
      "http://127.0.0.1:8000/avatar/test/speak",
      "http://127.0.0.1:8000/avatar/test/emotion",
      "http://127.0.0.1:8000/avatar/test/gesture",
      "http://127.0.0.1:8000/avatar/stop",
    ]);
    expect(fetch.mock.calls[3][1].body).toContain("hello");
  });
});
