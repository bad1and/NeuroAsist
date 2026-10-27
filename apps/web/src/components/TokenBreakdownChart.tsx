import { useState } from "react";
import { PieChart } from "./charts/pie-chart";
import { PieSlice } from "./charts/pie-slice";
import { PieCenter } from "./charts/pie-center";
import { ExpenseNumber } from "./ExpenseNumber";
import { MaterialButton } from "./MaterialButton";
import { formatCompactTokens, formatTokens } from "./expenses";

type BreakdownItem = { key: string; label: string; total: number; request_count: number };

export function TokenBreakdownChart({ title, items, loading, unavailable, onInspect }:
  { title: string; items: BreakdownItem[]; loading: boolean; unavailable?: boolean; onInspect?: (key: string) => void }) {
  const [hovered, setHovered] = useState<number | null>(null);
  const data = items.filter(item => item.total > 0).sort((a, b) => b.total - a.total)
    .map((item, index) => ({ ...item, value: item.total, color: `var(--chart-${index % 5 + 1})` }));
  const total = data.reduce((sum, item) => sum + item.total, 0);
  const active = hovered !== null ? data[hovered] : null;
  return <section className="expense-breakdown" aria-label={title} aria-busy={loading}>
    <div className="expense-breakdown-heading"><h3>{title}</h3><span>По токенам</span></div>
    {loading || unavailable || !data.length ? <div className="expense-breakdown-empty" role="status">
      <div className="expense-empty-ring" aria-hidden="true" /><span>{loading ? "Загружаем распределение…" : unavailable ? "Данные недоступны" : "Нет записей за период"}</span>
    </div> : <div className="expense-breakdown-body">
      <div className="expense-donut" role="img" aria-label={data.map(item => `${item.label}: ${formatTokens(item.total)} токенов`).join("; ")}>
        <PieChart data={data} size={166} innerRadius={57} padAngle={.035} cornerRadius={4}
          hoverOffset={4} hoveredIndex={hovered} onHoverChange={setHovered} enterStaggerScale={.4}
          enterTransition={{ type: "tween", duration: .7 }}>
          {data.map((item, index) => <PieSlice key={item.key} index={index} hoverEffect="grow" />)}
          <PieCenter defaultLabel="токенов">{() => <div className="expense-donut-center"><strong><ExpenseNumber value={active ? active.total / total * 100 : total} format={active ? percent : formatCompactTokens} /></strong><span>{active ? "доля токенов" : "токенов"}</span></div>}</PieCenter>
        </PieChart>
      </div>
      <div className="expense-breakdown-legend" onMouseLeave={() => setHovered(null)}>
        {data.map((item, index) => <MaterialButton key={item.key} appearance="plain" materialKey={`expenses.breakdown.${title}.${item.key}`}
          className={`expense-breakdown-row ${hovered === index ? "is-highlighted" : ""}`} onMouseEnter={() => setHovered(index)}
          onFocus={() => setHovered(index)} onBlur={() => setHovered(null)} onClick={() => onInspect ? onInspect(item.key) : setHovered(hovered === index ? null : index)}
          aria-label={`${item.label}: ${formatTokens(item.total)} токенов, ${percent(item.total / total * 100)}${onInspect ? ". Открыть запросы" : ""}`}>
          <span className="expense-breakdown-marker" style={{ background: item.color }} />
          <span className="expense-breakdown-label"><strong title={item.label}>{item.label}</strong><small>{formatTokens(item.request_count)} запросов</small></span>
          <span className="expense-breakdown-value"><strong>{percent(item.total / total * 100)}</strong><small>{formatCompactTokens(item.total)}</small></span>
        </MaterialButton>)}
      </div>
    </div>}
  </section>;
}
const percent = (value: number) => `${value.toLocaleString("ru-RU", { maximumFractionDigits: 1 })}%`;
