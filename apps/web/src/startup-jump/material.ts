// Bake the Iris lens and rim once. Moving objects only copy these tiny sprites.
export function createJumpMaterial(width: number, height: number, radius: number, dpr: number, style: CSSStyleDeclaration) {
  const padding = 12;
  const sprite = document.createElement("canvas");
  sprite.width = Math.ceil((width + padding * 2) * dpr);
  sprite.height = Math.ceil((height + padding * 2) * dpr);
  const ctx = sprite.getContext("2d");
  if (!ctx) return sprite;
  const token = (name: string) => style.getPropertyValue(name).trim();
  ctx.setTransform(dpr, 0, 0, dpr, padding * dpr, padding * dpr);
  const face = ctx.createLinearGradient(0, 0, 0, height);
  face.addColorStop(0, token("--rim-light-lower"));
  face.addColorStop(0.36, token("--lens-accent"));
  face.addColorStop(1, token("--rim-tone"));
  ctx.fillStyle = face;
  ctx.shadowColor = token("--rim-glow");
  ctx.shadowBlur = 7 * dpr;
  ctx.beginPath(); ctx.roundRect(0, 0, width, height, radius); ctx.fill();
  ctx.shadowBlur = 0;
  const rim = ctx.createLinearGradient(0, 0, width * 0.7, height);
  rim.addColorStop(0, token("--rim-light-start"));
  rim.addColorStop(0.21, token("--rim-light-mid"));
  rim.addColorStop(0.45, token("--rim-tone"));
  rim.addColorStop(0.72, token("--rim-light-lower"));
  rim.addColorStop(1, token("--rim-light-end"));
  ctx.strokeStyle = rim;
  ctx.lineWidth = height > 12 ? 1.8 : 1.3;
  ctx.stroke();
  const shine = ctx.createLinearGradient(0, 0, 0, height);
  shine.addColorStop(0, "rgb(255 255 255 / .22)");
  shine.addColorStop(0.45, "rgb(255 255 255 / 0)");
  shine.addColorStop(1, "rgb(0 0 0 / .18)");
  ctx.fillStyle = shine;
  ctx.fill();
  return sprite;
}
