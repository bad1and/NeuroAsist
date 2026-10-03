// @vitest-environment jsdom
import React, { createRef, useState } from "react";
import { afterEach, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { MaterialButton, MaterialButtonGroup } from "./MaterialButton";
import { buttonSeed, materialStyle } from "./buttonMaterial";

afterEach(cleanup);

it("keeps each entity's seed through reordering, state changes and remounting", () => {
  const list = (ids: string[], busy = false) => <>{ids.map(id => <MaterialButton key={id} materialKey={`history.${id}.open`} disabled={busy}>{busy ? "Подождите" : id}</MaterialButton>)}</>;
  const view = render(list(["a", "b"]));
  const a = screen.getByRole("button", { name: "a" }).dataset.materialSeed;
  const b = screen.getByRole("button", { name: "b" }).dataset.materialSeed;
  expect(a).not.toBe(b);
  view.rerender(list(["b", "a"], true));
  expect(screen.getAllByRole("button").map(button => button.dataset.materialSeed)).toEqual([b, a]);
  view.unmount();
  render(list(["a", "b"]));
  expect(screen.getByRole("button", { name: "a" })).toHaveAttribute("data-material-seed", a);
});

it("forwards the native ref and retains submit, keyboard focus and disabled semantics", () => {
  const ref = createRef<HTMLButtonElement>();
  let submissions = 0;
  const view = render(<form onSubmit={event => { event.preventDefault(); submissions++; }}>
    <MaterialButton materialKey="form.save" ref={ref}>Сохранить</MaterialButton>
  </form>);
  expect(ref.current).toBe(screen.getByRole("button", { name: "Сохранить" }));
  ref.current!.focus();
  expect(ref.current).toHaveFocus();
  fireEvent.click(ref.current!);
  expect(submissions).toBe(1);
  view.rerender(<MaterialButton materialKey="form.save" ref={ref} disabled>Сохранить</MaterialButton>);
  fireEvent.click(ref.current!);
  expect(ref.current).toBeDisabled();
  expect(submissions).toBe(1);
  expect(ref.current!.querySelector(".dp-hover-surface")).toHaveAttribute("aria-hidden", "true");
});

it("preserves a navigation seed when selected and leaves bare actions without a material", () => {
  const view = render(<MaterialButton materialKey="navigation.chat" className="navigation-button">Диалог</MaterialButton>);
  const seed = screen.getByRole("button").dataset.materialSeed;
  expect(screen.getByRole("button")).toHaveAttribute("data-material", "quiet");
  view.rerender(<MaterialButton materialKey="navigation.chat" className="navigation-button is-active" aria-current="page">Диалог</MaterialButton>);
  expect(screen.getByRole("button")).toHaveAttribute("data-material-seed", seed);
  expect(screen.getByRole("button")).toHaveClass("dp-accent");
  view.rerender(<MaterialButton materialKey="chat.send" className="send-button">Отправить</MaterialButton>);
  expect(screen.getByRole("button")).toHaveAttribute("data-material", "plain");
  expect(screen.getByRole("button").querySelector(".dp-material")).toBeNull();
});

it("reproduces seeds and limits production material variation", () => {
  expect(buttonSeed("chat.microphone")).toBe(buttonSeed("chat.microphone"));
  expect(buttonSeed("chat.microphone")).not.toBe(buttonSeed("chat.sound"));
  for (let index = 0; index < 50; index++) {
    const style = materialStyle(buttonSeed(`action.${index}`), .35) as Record<string, number | string>;
    expect(parseFloat(String(style["--dp-light-x"]))).toBeGreaterThanOrEqual(40.2);
    expect(parseFloat(String(style["--dp-light-x"]))).toBeLessThanOrEqual(59.8);
    expect(Number(style["--dp-fill-factor"])).toBeGreaterThanOrEqual(.919);
  }
});

it("shares one media face while each mute action keeps its own state and seed", () => {
  function MediaControls() {
    const [mic, muteMic] = useState(false);
    const [sound, muteSound] = useState(false);
    return <MaterialButtonGroup materialKey="chat.media-controls" muted={[mic, sound]} role="group" aria-label="Микрофон и звук">
      <MaterialButton materialKey="chat.microphone" appearance="joined" tone={mic ? "danger" : "graphite"} aria-pressed={!mic} onClick={() => muteMic(!mic)}>Микрофон</MaterialButton>
      <MaterialButton materialKey="chat.sound" appearance="joined" tone={sound ? "danger" : "graphite"} aria-pressed={!sound} onClick={() => muteSound(!sound)}>Наушники</MaterialButton>
    </MaterialButtonGroup>;
  }
  render(<MediaControls />);
  const group = screen.getByRole("group");
  const mic = screen.getByRole("button", { name: "Микрофон" });
  const sound = screen.getByRole("button", { name: "Наушники" });
  const seeds = [group, mic, sound].map(el => el.dataset.materialSeed);
  expect(group.querySelectorAll(":scope > .dp-hover-surface")).toHaveLength(1);
  expect(group.querySelectorAll(".dp-material")).toHaveLength(1);
  fireEvent.click(mic);
  expect(mic).toHaveClass("dp-danger");
  expect(mic).toHaveAttribute("aria-pressed", "false");
  expect(group.querySelector('.dp-joined-half[data-side="0"]')).not.toBeNull();
  expect(group.querySelector('.dp-joined-half[data-side="1"]')).toBeNull();
  fireEvent.click(sound);
  expect(sound).toHaveClass("dp-danger");
  expect(sound).toHaveAttribute("aria-pressed", "false");
  expect(group).toHaveClass("dp-danger");
  expect(group.querySelectorAll(".dp-material")).toHaveLength(1);
  expect(group.querySelectorAll(".dp-joined-half")).toHaveLength(0);
  fireEvent.click(mic);
  expect(group.querySelector('.dp-joined-half[data-side="0"]')).toBeNull();
  expect(group.querySelector('.dp-joined-half[data-side="1"]')).not.toBeNull();
  expect(sound).toHaveClass("dp-danger");
  expect([group, mic, sound].map(el => el.dataset.materialSeed)).toEqual(seeds);
});
