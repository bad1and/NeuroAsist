/** V3 petals only use absolute M/C pairs. Preserve their command topology
 * so Anime can unfold their curves without replacing the logo silhouette. */
export function shapePetal(d: string, openness: number, index: number): string {
  let coordinate = 0;
  return d.replace(/-?\d*\.?\d+/g, (number) => {
    const value = Number(number);
    const isX = coordinate++ % 2 === 0;
    const root = isX ? 76 : 120;
    const spread = isX ? 0.1 + 0.9 * openness : 0.38 + 0.62 * openness;
    // The folded tip curves gently toward its own side; the base remains fixed.
    const curl = isX ? Math.sin((value - root) / 45) * (1 - openness) * (index === 0 ? 2 : 6) : 0;
    return (root + (value - root) * spread + curl).toFixed(4);
  });
}
