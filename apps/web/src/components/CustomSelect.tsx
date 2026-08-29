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
}

export function CustomSelect({ value, onChange, disabled, children, className = "", id }: CustomSelectProps) {
  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const options: { value: string; label: ReactNode; disabled?: boolean }[] = [];
  Children.forEach(children, (child) => {
    if (isValidElement(child) && child.type === "option") {
      const el = child as ReactElement<any>;
      options.push({
        value: String(el.props.value),
        label: el.props.children,
        disabled: el.props.disabled,
      });
    } else if (Array.isArray(child)) {
       child.forEach(c => {
         if (isValidElement(c) && c.type === "option") {
           const el = c as ReactElement<any>;
           options.push({
             value: String(el.props.value),
             label: el.props.children,
             disabled: el.props.disabled,
           });
         }
       })
    }
  });

  const selectedOption = options.find((o) => o.value === String(value)) || options[0];

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  return (
    <div 
      className={`custom-select-container ${disabled ? "disabled" : ""} ${className}`} 
      ref={containerRef}
      id={id}
    >
      <button
        type="button"
        className="custom-select-trigger"
        onClick={() => !disabled && setIsOpen(!isOpen)}
        disabled={disabled}
      >
        <span className="custom-select-value">{selectedOption ? selectedOption.label : ""}</span>
        <ChevronDown size={16} className="custom-select-icon" />
      </button>
      {isOpen && (
        <div className="custom-select-dropdown">
          {options.map((option, index) => (
            <div
              key={index}
              className={`custom-select-option ${option.value === String(value) ? "selected" : ""} ${option.disabled ? "disabled" : ""}`}
              onClick={() => {
                if (!option.disabled) {
                  onChange?.({ target: { value: option.value } });
                  setIsOpen(false);
                }
              }}
            >
              {option.label}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
