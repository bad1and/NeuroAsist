// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { SlidingSegments } from "./SlidingSegments";
import { AppCheckbox } from "./AppCheckbox";
import { AppSwitch } from "./AppSwitch";

afterEach(cleanup);

function Selection() {
  const [value, setValue] = useState("first");
  return <SlidingSegments value={value} aria-label="Фильтр">
    {["first", "disabled", "last"].map(id => <button key={id} disabled={id === "disabled"}
      aria-pressed={value === id} onClick={() => setValue(id)}>{id}</button>)}
  </SlidingSegments>;
}

describe("selection controls", () => {
  it("selects and focuses with arrows and Home/End, skipping disabled choices", () => {
    render(<Selection />);
    const first = screen.getByRole("button", { name: "first" });
    const last = screen.getByRole("button", { name: "last" });
    fireEvent.keyDown(first, { key: "ArrowRight" });
    expect(last.getAttribute("aria-pressed")).toBe("true");
    expect(document.activeElement).toBe(last);
    fireEvent.keyDown(last, { key: "ArrowRight" });
    expect(first.getAttribute("aria-pressed")).toBe("true");
    fireEvent.keyDown(first, { key: "End" });
    expect(document.activeElement).toBe(last);
    fireEvent.keyDown(last, { key: "Home" });
    expect(document.activeElement).toBe(first);
  });

  it("keeps labels and controlled change callbacks for checkbox and switch", () => {
    const checkboxChange = vi.fn();
    const switchChange = vi.fn();
    render(<><label><AppCheckbox checked={false} onChange={checkboxChange} />Заметки</label>
      <AppSwitch checked={false} label="Голос" onChange={switchChange} /></>);
    fireEvent.click(screen.getByRole("checkbox", { name: "Заметки" }));
    expect(checkboxChange).toHaveBeenCalledOnce();
    fireEvent.click(screen.getByRole("switch", { name: "Голос" }));
    expect(switchChange).toHaveBeenCalledWith(true);
  });

  it("keeps native form values and disabled semantics", () => {
    const change = vi.fn();
    const { container } = render(<form><label><AppCheckbox checked name="notes" value="yes" readOnly />Заметки</label>
      <AppSwitch checked disabled label="Голос" onChange={change} /></form>);
    expect(new FormData(container.querySelector("form")!).get("notes")).toBe("yes");
    expect((screen.getByRole("switch") as HTMLInputElement).disabled).toBe(true);
    expect(change).not.toHaveBeenCalled();
  });
});
