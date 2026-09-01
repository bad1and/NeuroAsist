import { useState, useRef, useEffect, ReactNode, Children, isValidElement, ReactElement } from "react";
import { ChevronDown } from "lucide-react";
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

  const containerRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const optionRefs = useRef<(HTMLDivElement | null)[]>([]);

  const options = extractOptions(children);
  const selectedOption = options.find((o) => o.value === String(value)) || options[0];

  // Auto-flip placement if not enough room below
  useEffect(() => {
    if (!isOpen || !containerRef.current) return;
    const rect = containerRef.current.getBoundingClientRect();
    const dropdownHeight = 240;
    const spaceBelow = window.innerHeight - rect.bottom;
    const spaceAbove = rect.top;

    if (spaceBelow < dropdownHeight && spaceAbove > spaceBelow) {
      setPlacement("top");
    } else {
      setPlacement("bottom");
    }
  }, [isOpen]);

  // Keep highlighted index synced on open
  useEffect(() => {
    if (isOpen) {
      const idx = options.findIndex((o) => o.value === String(value));
      setHighlightedIndex(idx >= 0 ? idx : 0);
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

    if (e.key === "ArrowDown") {
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
        onClick={() => !disabled && setIsOpen((prev) => !prev)}
        disabled={disabled}
        aria-haspopup="listbox"
        aria-expanded={isOpen}
      >
        {prefixIcon && <span className="custom-select-prefix">{prefixIcon}</span>}
        <span className="custom-select-value">{selectedOption ? selectedOption.label : ""}</span>
        <ChevronDown size={16} className="custom-select-icon" />
      </button>

      {isOpen && (
        <div
          className={`custom-select-dropdown placement-${placement}`}
          role="listbox"
          tabIndex={-1}
        >
          {options.map((option, index) => {
            const isSelected = option.value === String(value);
            const isHighlighted = highlightedIndex === index;
            return (
              <div
                key={option.value || index}
                ref={(el) => {
                  optionRefs.current[index] = el;
                }}
                role="option"
                aria-selected={isSelected}
                className={`custom-select-option ${isSelected ? "selected" : ""} ${
                  isHighlighted ? "highlighted" : ""
                } ${option.disabled ? "disabled" : ""}`}
                onMouseEnter={() => !option.disabled && setHighlightedIndex(index)}
                onClick={() => {
                  if (!option.disabled) {
                    handleSelect(option.value);
                  }
                }}
              >
                <span className="custom-select-option-label">{option.label}</span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
