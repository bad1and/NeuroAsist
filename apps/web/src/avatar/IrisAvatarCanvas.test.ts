import { describe, expect, it } from "vitest";

import { isSpeechGesture, speechClipId } from "./IrisAvatarCanvas";

describe("speech animation routing", () => {
  it("keeps continuous speaking directives out of the one-shot gesture path", () => {
    for (const gesture of ["talk", "explanation", "question", "talkingquestion", "auto", "none"]) {
      expect(isSpeechGesture(gesture)).toBe(true);
    }
    expect(isSpeechGesture("greeting")).toBe(false);
  });

  it("selects the questioning loop only for question directives", () => {
    expect(speechClipId("question")).toBe("talkingquestion");
    expect(speechClipId("talkingquestion")).toBe("talkingquestion");
    expect(speechClipId("talk")).toBe("talk");
    expect(speechClipId("greeting")).toBe("talk");
  });
});
