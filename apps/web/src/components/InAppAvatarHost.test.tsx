// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const avatar = vi.hoisted(() => ({ render: vi.fn() }));

vi.mock("../avatar/IrisAvatarCanvas", () => ({
  IrisAvatarCanvas: () => {
    avatar.render();
    return <div data-testid="three-avatar" />;
  },
}));

import { InAppAvatarHost } from "./InAppAvatarHost";

describe("InAppAvatarHost", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("renders the DOM-owned Three.js avatar instead of a native host", async () => {
    render(<InAppAvatarHost />);
    expect(await screen.findByTestId("three-avatar")).toBeInTheDocument();
    expect(avatar.render).toHaveBeenCalledTimes(1);
  });
});
