import { useState, useRef, useEffect, useLayoutEffect, useId, ReactNode, Children, isValidElement, ReactElement } from "react";
import { ChevronDown } from "lucide-react";
import { isTestEnvironment, prefersReducedMotion, runSafeAnimation } from "../animations/core";
import { ButtonMaterialLayers } from "./MaterialButton";
import { materialStyle } from "./buttonMaterial";
import { useMaterialFeedback } from "./useMaterialFeedback";
import "./MaterialButton.css";
import "./CustomSelect.css";

interface CustomSelectProps {
  value: string | number;
  onChange?: (event: { target: { value: string } }) => void;
  disabled?: boolean;
  children: ReactNode;
  className?: string;
  id?: string;
  prefixIcon?: ReactNode;
  style?: React.CSSProperties;
}

interface SelectOption {
  value: string;
  label: ReactNode;
  disabled?: boolean;
}

function SelectRow({ option, selected, highlighted, optionId, attach, onHighlight, onSelect } : {
  option: SelectOption; selected: boolean; highlighted: boolean; optionId: string;
  attach: (element: HTMLDivElement | null) => void; onHighlight: () => void; onSelect: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useMaterialFeedback(ref, { disabled: option.disabled, seed: 42, pressSurface: true, pressScale: false });
  useEffect(() => {
    const surface = ref.current?.querySelector<HTMLElement>(".dp-hover-surface");
    if (!surface || isTestEnvironment()) return;
    const animation = runSafeAnimation(surface, {
      opacity: option.disabled ? 0 : highlighted || selected ? 1 : 0,
      duration: 150, ease: "outQuad",
    });
    return () => { animation?.cancel(); };
  }, [selected, highlighted, option.disabled]);
  return <div ref={(element) => { ref.current = element; attach(element); }}
    id={optionId} role="option" aria-selected={selected} aria-disabled={option.disabled || undefined}
    className={`custom-select-option dp-lens ${selected ? "selected" : ""} ${highlighted ? "highlighted" : ""} ${option.disabled ? "disabled" : ""}`}
    style={materialStyle(42, .35)}
    onMouseEnter={() => !option.disabled && onHighlight()}
    onClick={() => !option.disabled && onSelect()}>
    <ButtonMaterialLayers />
    <span className="custom-select-option-label">{option.label}</span>
  </div>;
}

function extractOptions(children: ReactNode): SelectOption[] {
  const result: SelectOption[] = [];

  const traverse = (node: ReactNode) => {
    Children.forEach(node, (child) => {
      if (!isValidElement(child)) return;
      if (child.type === "option") {
        const el = child as ReactElement<any>;
        result.push({
          value: String(el.props.value ?? ""),
          label: el.props.children ?? el.props.value,
          disabled: Boolean(el.props.disabled),
        });
      } else if (
        child.props &&
        typeof child.props === "object" &&
        "children" in child.props &&
        child.props.children
      ) {
        traverse((child.props as { children?: ReactNode }).children);
      }
    });
  };

  traverse(children);
  return result;
}

export function CustomSelect({
  value,
  onChange,
  disabled,
  children,
  className = "",
  id,
  prefixIcon,
  style,
}: CustomSelectProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [placement, setPlacement] = useState<"bottom" | "top">("bottom");
  const [highlightedIndex, setHighlightedIndex] = useState<number>(-1);
  const instanceId = useId();
  const listboxId = `${instanceId}-listbox`;
  const triggerId = `${instanceId}-trigger`;

  const containerRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const optionRefs = useRef<(HTMLDivElement | null)[]>([]);

  const options = extractOptions(children);
  const selectedOption = options.find((o) => o.value === String(value)) || options[0];

  // The joined shell follows the real field size, including compact settings.
  useLayoutEffect(() => {
    const container = containerRef.current;
    const trigger = triggerRef.current;
    if (!isOpen || !container || !trigger) return;
    const measure = () => {
      const computed = getComputedStyle(trigger);
      const rect = trigger.getBoundingClientRect();
      container.style.setProperty("--select-header-height", `${rect.height}px`);
      container.style.setProperty("--select-shell-radius", computed.borderTopLeftRadius || "var(--radius-control)");
      const dropdownHeight = Math.min(dropdownRef.current?.scrollHeight || 240, 240);
      const spaceBelow = Math.max(0, window.innerHeight - rect.bottom - 8);
      const spaceAbove = Math.max(0, rect.top - 8);
      const opensAbove = spaceBelow < dropdownHeight && spaceAbove > spaceBelow;
      setPlacement(opensAbove ? "top" : "bottom");
      container.style.setProperty("--select-menu-max-height", `${Math.max(38, Math.min(240, opensAbove ? spaceAbove : spaceBelow))}px`);
    };
    measure();
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(measure);
    observer?.observe(trigger);
    window.addEventListener("resize", measure);
    return () => { observer?.disconnect(); window.removeEventListener("resize", measure); };
  }, [isOpen]);

  useEffect(() => { if (disabled) setIsOpen(false); }, [disabled]);

  // Animate only the menu and chevron, keeping the recessed field stationary.
  useEffect(() => {
    const icon = triggerRef.current?.querySelector<SVGSVGElement>(".custom-select-icon");
    if (!icon) return;
    if (prefersReducedMotion()) {
      icon.style.transform = `rotate(${isOpen ? 180 : 0}deg)`;
      return;
    }
    const animation = runSafeAnimation(icon, { rotate: isOpen ? 180 : 0, duration: 180, ease: "outCubic" });
    return () => { animation?.cancel(); };
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen || !dropdownRef.current || isTestEnvironment()) return;
    const animation = runSafeAnimation(dropdownRef.current, {
      opacity: [0, 1], y: [placement === "bottom" ? -4 : 4, 0], duration: 180, ease: "outCubic",
    });
    return () => { animation?.cancel(); };
  }, [isOpen, placement]);

  // Keep highlighted index synced on open
  useEffect(() => {
    if (isOpen) {
      const idx = options.findIndex((o) => o.value === String(value));
      setHighlightedIndex(idx >= 0 && !options[idx].disabled ? idx : options.findIndex((option) => !option.disabled));
    }
  }, [isOpen, value]);

  // Scroll highlighted item into view
  useEffect(() => {
    if (isOpen && highlightedIndex >= 0 && optionRefs.current[highlightedIndex]) {
      const el = optionRefs.current[highlightedIndex];
      if (typeof el?.scrollIntoView === "function") {
        el.scrollIntoView({
          block: "nearest",
        });
      }
    }
  }, [highlightedIndex, isOpen]);

  // Click outside to close
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const handleSelect = (optionValue: string) => {
    if (disabled) return;
    onChange?.({ target: { value: optionValue } });
    setIsOpen(false);
    triggerRef.current?.focus();
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (disabled) return;

    if (!isOpen) {
      if (e.key === "Enter" || e.key === " " || e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        setIsOpen(true);
      }
      return;
    }

    if (e.key === "Escape") {
      e.preventDefault();
      setIsOpen(false);
      triggerRef.current?.focus();
      return;
    }

    if (e.key === "Tab") {
      setIsOpen(false);
      return;
    }

    if (e.key === "Home" || e.key === "End") {
      e.preventDefault();
      const enabled = options.flatMap((option, index) => option.disabled ? [] : [index]);
      setHighlightedIndex((e.key === "Home" ? enabled[0] : enabled[enabled.length - 1]) ?? -1);
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      setHighlightedIndex((prev) => {
        let next = prev + 1;
        while (next < options.length && options[next].disabled) next++;
        return next < options.length ? next : prev;
      });
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setHighlightedIndex((prev) => {
        let next = prev - 1;
        while (next >= 0 && options[next].disabled) next--;
        return next >= 0 ? next : prev;
      });
    } else if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      if (highlightedIndex >= 0 && highlightedIndex < options.length) {
        const opt = options[highlightedIndex];
        if (!opt.disabled) {
          handleSelect(opt.value);
        }
      }
    }
  };

  return (
    <div
      className={`custom-select-container ${disabled ? "disabled" : ""} ${isOpen ? "open" : ""} ${className}`}
      data-placement={placement}
      ref={containerRef}
      onKeyDown={handleKeyDown}
      style={style}
    >
      {/* Hidden native select for accessibility & automated tests compatibility */}
      <select
        value={value}
        onChange={onChange ?? (() => {})}
        disabled={disabled}
        id={id}
        tabIndex={-1}
        className="custom-select-native-hidden"
      >
        {children}
      </select>

      <button
        ref={triggerRef}
        type="button"
        className="custom-select-trigger"
        id={triggerId}
        onClick={() => !disabled && setIsOpen((prev) => !prev)}
        disabled={disabled}
        aria-haspopup="listbox"
        aria-expanded={isOpen}
        aria-controls={isOpen ? listboxId : undefined}
      >
        {prefixIcon && <span className="custom-select-prefix">{prefixIcon}</span>}
        <span className="custom-select-value">{selectedOption ? selectedOption.label : ""}</span>
        <ChevronDown size={16} className="custom-select-icon" />
      </button>

      {isOpen && (
        <div className={`custom-select-popup placement-${placement}`}>
        <div
          ref={dropdownRef}
          id={listboxId}
          className="custom-select-dropdown"
          role="listbox"
          aria-labelledby={triggerId}
          tabIndex={-1}
        >
          {options.map((option, index) => {
            const isSelected = option.value === String(value);
            const isHighlighted = highlightedIndex === index;
            return (
              <SelectRow
                key={option.value || index}
                option={option}
                selected={isSelected}
                highlighted={isHighlighted}
                optionId={`${instanceId}-option-${index}`}
                attach={(el) => {
                  optionRefs.current[index] = el;
                }}
                onHighlight={() => setHighlightedIndex(index)}
                onSelect={() => handleSelect(option.value)}
              />
            );
          })}
        </div>
        </div>
      )}
    </div>
  );
}
