// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest";
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { IrisPortalBackground } from "./IrisPortalBackground";

describe("IrisPortalBackground", () => {
  it("renders canvas element inside backdrop container", () => {
    const { container } = render(
      <IrisPortalBackground
        emotion="neutral"
        voiceState="idle"
        loading={false}
        isDialogActive={false}
      />
    );

    const backdrop = container.querySelector(".iris-portal-backdrop");
    expect(backdrop).toBeInTheDocument();
    expect(backdrop?.querySelector(".iris-portal-canvas")).toBeInTheDocument();
  });

  it("updates smoothly when props change without throwing errors", () => {
    const { rerender, container } = render(
      <IrisPortalBackground
        emotion="joy"
        voiceState="speaking"
        loading={false}
        isDialogActive={true}
        showInAppAvatar={true}
      />
    );

    expect(container.querySelector(".iris-portal-canvas")).toBeInTheDocument();

    rerender(
      <IrisPortalBackground
        emotion="thinking"
        voiceState="thinking"
        loading={true}
        isDialogActive={true}
        showInAppAvatar={false}
      />
    );

    expect(container.querySelector(".iris-portal-canvas")).toBeInTheDocument();
  });
});
